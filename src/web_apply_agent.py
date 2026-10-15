from __future__ import annotations

import json
import os
import re
from urllib.parse import urldefrag, urlparse, parse_qs
from dataclasses import dataclass
from typing import Any

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from src.agent_memory import (
    append_event,
    get_failure_memory_for_url,
    load_answer_bank_hints,
    record_failure_memory,
)
from src.browser_actions import ActionResult, execute_agent_action
from src.page_observer import compact_snapshot_for_prompt, observe_page
from src.safety_policy import (
    POLICY,
    documents_summary,
    is_final_submit_text,
    missing_document_mentions,
    page_has_human_verification,
    profile_summary,
)


@dataclass
class WebApplyResult:
    ok: bool
    method: str
    reason: str
    url: str = ""
    steps: int = 0


def web_apply_agent_enabled() -> bool:
    return str(os.getenv("WEB_APPLY_AGENT_ENABLED", "true")).strip().lower() not in {"0", "false", "no", "off"}


def _model_name() -> str:
    return os.getenv("WEB_APPLY_AGENT_MODEL", os.getenv("EXTERNAL_SITE_AGENT_MODEL", "gpt-5-mini")).strip() or "gpt-5-mini"


def _extract_json(text: str) -> dict[str, Any]:
    """Parse the model's one-action JSON, with small repairs for common model glitches."""
    raw = (text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I | re.S).strip()

    candidates: list[str] = []
    if raw:
        candidates.append(raw)
    match = re.search(r"\{.*\}", raw, flags=re.S)
    if match:
        candidates.append(match.group(0))

    last_error: Exception | None = None
    for candidate in candidates:
        repaired = candidate.strip()
        # Remove JS/Python-style trailing commas before closing braces/brackets.
        repaired = re.sub(r",\s*([}\]])", r"\1", repaired)
        # Convert blank JSON values like "target_ref": , to null.
        repaired = re.sub(r":\s*([,}])", r": null\1", repaired)
        try:
            parsed = json.loads(repaired)
            if isinstance(parsed, dict):
                return parsed
        except Exception as exc:
            last_error = exc
            continue

    raise ValueError(f"No valid JSON object in model response: {raw[:500]} ({last_error})")


def _compact_history(history: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    return history[-limit:]


def _has_missing_required_document(snapshot: dict[str, Any]) -> str | None:
    docs = documents_summary()
    controls = snapshot.get("controls") or []
    for control in controls:
        if not isinstance(control, dict):
            continue
        if control.get("role") != "file":
            continue
        label = str(control.get("label") or control.get("text") or "").lower()
        required = "required" in label or "*" in label
        if not required:
            # Many ATS file inputs do not include `required`, so only hard-stop
            # non-configured documents if their label is clearly a special doc.
            pass
        if "resume" in label and docs.get("resume"):
            continue
        if "transcript" in label and docs.get("transcript"):
            continue
        if "cover" in label and "letter" in label and not docs.get("cover_letter"):
            return "Required cover letter file requested, but no cover_letter document is configured."
        if any(term in label for term in ["portfolio", "project", "writing sample", "work sample", "other document"]):
            key = "portfolio" if "portfolio" in label else "project" if "project" in label else "writing_sample"
            if not docs.get(key):
                return f"Required {key.replace('_', ' ')} document requested, but no matching document is configured."
    return None


def _terminal_result(snapshot: dict[str, Any], *, external_final_submit: bool = False) -> WebApplyResult | None:
    state = str(snapshot.get("state") or "")
    url = str(snapshot.get("url") or "")
    body = str(snapshot.get("body_text") or "")

    if state == "greenhouse":
        return WebApplyResult(True, "greenhouse_reached", "Reached Greenhouse application flow.", url)
    if state == "human_verification" or page_has_human_verification(body):
        return WebApplyResult(True, "human_verification", "Reached human verification/CAPTCHA; manual action required.", url)
    if state == "email_verification":
        return WebApplyResult(True, "email_verification", "Reached email/security-code verification; manual action required.", url)

    missing_doc = _has_missing_required_document(snapshot)
    if missing_doc:
        return WebApplyResult(True, "missing_required_document", missing_doc, url)

    if external_final_submit:
        return WebApplyResult(True, "final_review", "Reached final external submit/review step. Stopping as requested.", url)

    return None




def _clean_url_for_compare(url: str) -> str:
    """Normalize only harmless fragments/trailing slash for safety comparisons."""
    value = str(url or "").strip()
    if not value:
        return ""
    try:
        value, _frag = urldefrag(value)
    except Exception:
        pass
    if value.endswith("/"):
        value = value[:-1]
    return value


def _observed_urls(snapshot: dict[str, Any], history: list[dict[str, Any]], initial_url: str = "") -> dict[str, str]:
    """Return normalized -> exact observed URLs.

    The agent may only open URLs that actually came from the browser/page/history.
    This prevents it from reconstructing session-heavy SuccessFactors URLs and
    losing requestParams/CSRF/session state.
    """
    urls: dict[str, str] = {}

    def add(url: Any) -> None:
        raw = str(url or "").strip()
        if not raw.lower().startswith(("http://", "https://")):
            return
        key = _clean_url_for_compare(raw)
        if key and key not in urls:
            urls[key] = raw

    add(initial_url)
    add(snapshot.get("url"))
    for control in snapshot.get("controls") or []:
        if isinstance(control, dict):
            add(control.get("href"))
    for item in history:
        if isinstance(item, dict):
            add(item.get("before_url"))
            add(item.get("after_url"))
            add(item.get("url"))
    return urls


def _url_query_value(url: str, key: str) -> str:
    try:
        qs = parse_qs(urlparse(url).query)
        values = qs.get(key) or []
        return str(values[0]) if values else ""
    except Exception:
        return ""


def _resolve_safe_open_url(action: dict[str, Any], snapshot: dict[str, Any], history: list[dict[str, Any]], initial_url: str) -> tuple[str | None, str]:
    """Validate or replace an AI-requested open_url with an observed URL.

    The model is allowed to choose URLs, but only from evidence it can see:
    current URL, previous URLs, or hrefs in observed controls. It is not allowed
    to invent shorter SuccessFactors URLs because those lose opaque requestParams.
    """
    proposed = str(action.get("url") or action.get("value") or "").strip()
    target_text = str(action.get("target_text") or action.get("text") or action.get("label") or "").strip().lower()
    allowed = _observed_urls(snapshot, history, initial_url)

    if not proposed:
        return None, "open_url was blocked because the agent did not provide a URL."

    proposed_key = _clean_url_for_compare(proposed)
    if proposed_key in allowed:
        return allowed[proposed_key], ""

    # If the model named a visible control rather than copying its href, use the observed href.
    if target_text:
        for control in snapshot.get("controls") or []:
            if not isinstance(control, dict):
                continue
            href = str(control.get("href") or "").strip()
            if not href:
                continue
            hay = " ".join(str(control.get(k) or "") for k in ["text", "label"]).lower()
            if target_text in hay or hay in target_text:
                key = _clean_url_for_compare(href)
                if key in allowed:
                    return allowed[key], f"Using observed href for visible control instead of reconstructed URL: {href}"

    current = str(snapshot.get("url") or "")
    proposed_host = urlparse(proposed).netloc.lower() if proposed else ""
    current_host = urlparse(current).netloc.lower() if current else ""

    if proposed_host in {"successfactors.com", "www.successfactors.com", "sap.com", "www.sap.com"}:
        return None, "open_url was blocked: SAP/SuccessFactors marketing pages are not part of the job application flow. Relaunch the employer job page instead."

    # Special guard for SuccessFactors: never reconstruct requestParams URLs.
    if "successfactors" in proposed_host or "successfactors" in current_host:
        proposed_req = _url_query_value(proposed, "career_job_req_id")
        current_req = _url_query_value(current, "career_job_req_id")
        if current and proposed_req and current_req and proposed_req == current_req:
            return None, (
                "open_url was blocked: the agent tried to reconstruct a SuccessFactors URL for the same job. "
                "Stay on the current session-specific URL and continue with visible controls/account fields instead."
            )
        return None, (
            "open_url was blocked: SuccessFactors URLs must be exact observed hrefs/current URLs because they contain opaque session requestParams."
        )

    # For all sites, unknown/unobserved URL opens are blocked.
    return None, "open_url was blocked because the URL was not observed on the page or in navigation history."

def _build_prompt(*, target_title: str, target_company: str, snapshot: dict[str, Any], history: list[dict[str, Any]]) -> str:
    compact = compact_snapshot_for_prompt(snapshot)
    memory = get_failure_memory_for_url(snapshot.get("url"))
    answer_hints = load_answer_bank_hints(limit=80)

    return f"""
You are an autonomous browser agent applying to a job for the user.

MISSION
- Navigate from the current employer/ATS page toward the correct application for the target job.
- Fill safe application/account fields using only the provided profile, answer-bank hints, generated account credentials, or clearly visible page options.
- Stop at final review/submit for external ATS applications. Do not click final external Submit/Finish/Send Application.
- Do not bypass CAPTCHA, human verification, or email verification codes.
- Stop for missing required documents that are not configured.

TARGET JOB
Company: {target_company or 'unknown'}
Title: {target_title or 'unknown'}

USER-AUTHORIZED POLICIES
{json.dumps(POLICY, indent=2, ensure_ascii=False)}

PROFILE FACTS
{json.dumps(profile_summary(), indent=2, ensure_ascii=False)}

CONFIGURED DOCUMENTS
{json.dumps(documents_summary(), indent=2, ensure_ascii=False)}

ANSWER-BANK HINTS
These are prior user-provided/local answers. They may include GPA. Use them as facts when relevant, but do not blindly reuse stale generic dropdown answers.
{json.dumps(answer_hints, indent=2, ensure_ascii=False)[:20000]}

SITE MEMORY FOR THIS HOST
{json.dumps(memory, indent=2, ensure_ascii=False)}

RECENT ACTION HISTORY
{json.dumps(_compact_history(history), indent=2, ensure_ascii=False)}

CURRENT PAGE SNAPSHOT
{json.dumps(compact, indent=2, ensure_ascii=False)[:45000]}

ALLOWED ACTIONS
Return exactly one JSON object. No markdown.

Schema:
{{
  "action": "click|fill|select|check|upload_file|open_url|go_back|wait|create_site_account|save_memory|stop",
  "target_ref": "visible control ref when available",
  "target_text": "visible text/label when helpful",
  "value": "value for fill/select/open_url/wait/save_memory",
  "option": "select option text when action=select",
  "document_key": "resume|transcript|cover_letter|portfolio|writing_sample|project when action=upload_file",
  "url": "absolute URL when action=open_url",
  "reason": "brief reasoning",
  "confidence": 0.0,
  "stop_reason": "final_review|human_verification|email_verification|missing_required_document|unknown_personal_fact|done|stuck|error when action=stop"
}}

RULES
- Prefer target_ref over vague target_text when clicking/filling visible controls.
- If a split Apply menu is open, inspect controls/hrefs and use open_url ONLY with the exact href shown in CURRENT PAGE SNAPSHOT. Never invent, shorten, or reconstruct a SuccessFactors/career URL.
- If you see a sign-in/create-account gate and account creation is needed, use action=create_site_account.
- For email/name/phone/location/school/degree/major/graduation/work authorization/sponsorship/availability/onsite/source/how-heard, fill/select from PROFILE FACTS or ANSWER-BANK HINTS.
- The user says GPA is already stored; use an answer-bank GPA hint when asked for GPA. If GPA is not in answer hints and no page option can be safely chosen, stop unknown_personal_fact.
- For standard account terms/data privacy required to create an account, checking the box is allowed by user policy.
- For final external submit/review buttons, stop with final_review. Native Handshake submit is handled outside this agent.
- Never invent a missing document. If required cover letter/project/portfolio/writing sample is requested and not configured, stop missing_required_document.
- open_url is only allowed for exact observed href/current/history URLs. For SuccessFactors, preserve the full requestParams URL; never remove parameters or create a simplified career_job_req_id URL.
- Once on a SuccessFactors/career page, prefer visible controls, create_site_account, fill/select/check, or wait. Do not open a reconstructed URL for the same job.
- Never navigate to www.successfactors.com or www.sap.com marketing pages; they are not application flows.
- If no safe progress action exists, stop with stuck and explain exactly what blocked progress.
""".strip()


def _ask_model(prompt: str) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return {
            "action": "stop",
            "stop_reason": "error",
            "reason": "OPENAI_API_KEY is not configured, so the web apply agent cannot reason over the page.",
            "confidence": 1.0,
        }

    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    response = client.responses.create(
        model=_model_name(),
        input=prompt,
    )
    return _extract_json(response.output_text)


def _action_maybe_final_submit(action: dict[str, Any]) -> bool:
    if str(action.get("action") or "").lower() != "click":
        return False
    text = " ".join(str(action.get(k) or "") for k in ["target_text", "text", "label", "value"])
    return is_final_submit_text(text)



def _page_is_closed(page) -> bool:
    try:
        return bool(page.is_closed())
    except Exception:
        return False


def _live_page(page):
    """Return the newest still-open page in the same context when ATS navigation closes/replaces the old page."""
    try:
        if not page.is_closed():
            return page
    except Exception:
        pass
    try:
        pages = [p for p in page.context.pages if not p.is_closed()]
        if pages:
            return pages[-1]
    except Exception:
        pass
    return page


def _safe_url(page, fallback: str = "") -> str:
    try:
        return getattr(page, "url", "") or fallback
    except Exception:
        return fallback


def _host(url: str) -> str:
    try:
        return urlparse(str(url or "")).netloc.lower()
    except Exception:
        return ""


def _path(url: str) -> str:
    try:
        return urlparse(str(url or "")).path.lower()
    except Exception:
        return ""


def _is_successfactors_or_sap_marketing(url: str) -> bool:
    host = _host(url)
    return host in {"successfactors.com", "www.successfactors.com", "sap.com", "www.sap.com"}


def _looks_like_sf_error_or_dead_session(snapshot: dict[str, Any]) -> bool:
    """Detect dead SuccessFactors/SAP shells where the only visible path is a marketing link.

    After SuccessFactors sign-in, SAP sometimes closes/replaces the tab and leaves an
    about:blank page or a career?_s.crb=... error shell. The useful recovery is not
    to click the visible SuccessFactors/SAP marketing link; it is to relaunch the
    employer apply flow from the last observed job page, now that credentials exist.
    """
    url = str(snapshot.get("url") or "")
    host = _host(url)
    body = _normalize_for_guard(snapshot.get("body_text") or "")
    title = _normalize_for_guard(snapshot.get("title") or "")
    controls = snapshot.get("controls") or []

    if url.strip().lower() in {"", "about:blank"}:
        return True

    if _is_successfactors_or_sap_marketing(url):
        return True

    if "successfactors" not in host:
        return False

    # A bare career?_s.crb=... URL is usually not the job application. It often
    # appears after the sign-in tab closes and can show an error page with only a
    # SuccessFactors/SAP link.
    path = _path(url)
    has_job_context = "career_job_req_id" in url or "career_ns=job" in url or "requestparams=" in url.lower()
    has_useful_controls = False
    for c in controls:
        if not isinstance(c, dict):
            continue
        hay = _normalize_for_guard(" ".join(str(c.get(k) or "") for k in ["text", "label", "role", "href"]))
        if any(term in hay for term in [
            "create an account", "sign in", "email", "password", "continue", "next",
            "resume", "first name", "last name", "phone", "candidate", "apply"
        ]):
            if "successfactors.com" not in hay and "sap.com" not in hay:
                has_useful_controls = True
                break

    error_markers = [
        "error", "not available", "unable to", "something went wrong", "session",
        "invalid", "expired", "try again", "successfactors"
    ]
    looks_error_text = any(m in body or m in title for m in error_markers)

    if path.rstrip("/") == "/career" and "_s.crb=" in url.lower() and not has_job_context:
        return True
    if looks_error_text and not has_useful_controls:
        return True
    return False


def _normalize_for_guard(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _is_restart_candidate_url(url: str) -> bool:
    raw = str(url or "").strip()
    if not raw.lower().startswith(("http://", "https://")):
        return False
    if raw.lower() == "about:blank":
        return False
    host = _host(raw)
    path = _path(raw)
    if "successfactors" in host or "sap.com" in host:
        return False
    if "talentcommunity/apply" in raw.lower():
        return False
    if path.rstrip("/") in {"", "/"}:
        return False
    return True


def _best_restart_url(history: list[dict[str, Any]], initial_url: str) -> str:
    urls: list[str] = []
    for item in reversed(history):
        if not isinstance(item, dict):
            continue
        for key in ["after_url", "before_url", "url"]:
            value = str(item.get(key) or "").strip()
            if value:
                urls.append(value)
    urls.append(initial_url)

    # Prefer concrete employer job-detail URLs before broad search pages.
    for url in urls:
        if _is_restart_candidate_url(url) and "/job" in _path(url):
            return url
    for url in urls:
        if _is_restart_candidate_url(url):
            return url
    return initial_url


def run_web_apply_agent(
    page,
    *,
    target_title: str,
    target_company: str = "",
    max_steps: int = 24,
) -> WebApplyResult:
    if not web_apply_agent_enabled():
        return WebApplyResult(False, "disabled", "WEB_APPLY_AGENT_ENABLED=false", getattr(page, "url", ""), 0)

    print("\n===== WEB APPLY AGENT =====")
    print(f"  Target: {target_company + ' — ' if target_company else ''}{target_title}")

    history: list[dict[str, Any]] = []
    page = _live_page(page)
    initial_url = _safe_url(page)
    repeated_state_count = 0
    last_signature = ""
    account_gate_no_progress_count = 0
    session_restart_count = 0

    for step in range(1, max_steps + 1):
        page = _live_page(page)
        try:
            snapshot = observe_page(page)
        except Exception as exc:
            # SuccessFactors/SAP sometimes closes/replaces the target page after login.
            # Switch to the newest live page if one exists instead of crashing the whole run.
            replacement = _live_page(page)
            if replacement is not page:
                page = replacement
                try:
                    snapshot = observe_page(page)
                except Exception as exc2:
                    return WebApplyResult(False, "page_closed", f"Browser page was closed/replaced and the live page could not be observed: {exc2}", _safe_url(page), step)
            else:
                return WebApplyResult(False, "page_closed", f"Browser page was closed or unavailable during observation: {exc}", _safe_url(page), step)
        url = str(snapshot.get("url") or _safe_url(page))
        state = str(snapshot.get("state") or "unknown")
        print(f"  Step {step}/{max_steps}: {state}")
        print(f"    URL: {url}")

        signature = f"{state}|{url}|{len(snapshot.get('controls') or [])}"
        if signature == last_signature:
            repeated_state_count += 1
        else:
            repeated_state_count = 0
        last_signature = signature

        terminal = _terminal_result(snapshot)
        if terminal is not None:
            terminal.steps = step
            append_event({
                "kind": "web_apply_terminal",
                "method": terminal.method,
                "reason": terminal.reason,
                "url": terminal.url,
                "target_company": target_company,
                "target_title": target_title,
            })
            print(f"  ✓ Agent terminal: {terminal.method} — {terminal.reason}")
            return terminal

        # Deterministic session recovery runs before the model. Do not let the
        # model click SuccessFactors/SAP marketing links from a dead session page.
        if _looks_like_sf_error_or_dead_session(snapshot):
            restart_url = _best_restart_url(history, initial_url)
            if session_restart_count >= 2 or not restart_url:
                reason = (
                    "SuccessFactors appears to have closed/replaced the application session after sign-in. "
                    "Credentials were saved/submitted, but the remaining page is a dead/error session shell; manual review is needed."
                )
                record_failure_memory(url, reason, pattern="successfactors_dead_session")
                return WebApplyResult(True, "session_recovery_needs_review", reason, url, step)

            session_restart_count += 1
            action = {
                "action": "open_url",
                "url": restart_url,
                "target_text": "restart employer apply flow from observed job page",
                "reason": "Current page is about:blank or a dead SuccessFactors/SAP error shell. Reopen the last observed employer job page and continue with saved credentials.",
                "confidence": 1.0,
            }
            print("  → Deterministic action: restart_apply_flow")
            print(f"    URL: {restart_url}")
            before_url = _safe_url(page)
            try:
                exec_result = execute_agent_action(
                    page,
                    action,
                    company=target_company,
                    job_title=target_title,
                    allow_final_submit=False,
                )
            except Exception as exc:
                replacement = _live_page(page)
                if replacement is not page:
                    page = replacement
                    exec_result = ActionResult(True, f"Browser target was replaced during session restart; switched to live page: {_safe_url(page)}", changed_url=True)
                else:
                    return WebApplyResult(False, "page_closed", f"Session restart failed because the page/context closed: {exc}", before_url, step)
            page = _live_page(page)
            after_url = _safe_url(page)
            history_item = {
                "step": step,
                "action": "restart_apply_flow",
                "target": restart_url,
                "ok": exec_result.ok,
                "message": exec_result.message,
                "before_url": before_url,
                "after_url": after_url,
                "reason": action["reason"],
                "confidence": 1.0,
            }
            history.append(history_item)
            append_event({"kind": "web_apply_action", **history_item, "target_company": target_company, "target_title": target_title})
            if exec_result.ok:
                print(f"    ✓ {exec_result.message}")
                continue
            print(f"    ⚠ {exec_result.message}")
            if session_restart_count >= 2:
                return WebApplyResult(True, "session_recovery_needs_review", exec_result.message, after_url or before_url, step)
            continue

        if repeated_state_count >= 5:
            lesson = "Agent saw the same page state repeatedly and stopped to avoid looping."
            record_failure_memory(url, lesson, pattern="repeated_state_loop", action_sequence=[str(h.get("action")) for h in history[-6:]])
            return WebApplyResult(False, "stuck", lesson, url, step)

        # Deterministic state handlers run before the model.
        # Account/login gates are not a reasoning problem: the user explicitly
        # authorized account creation and local credential storage, and allowing
        # the model to invent a SuccessFactors URL caused session loss. Stay on
        # the current page and use visible account controls.
        if state == "account_gate":
            action = {
                "action": "create_site_account",
                "target_text": "Create/sign in external account",
                "reason": "Current page is an external account gate; create/sign in using saved local site credentials and stay on this session URL.",
                "confidence": 1.0,
            }
            print("  → Deterministic action: create_site_account")
            print("    Reason: account_gate is handled before AI to preserve the current SuccessFactors session URL")
            before_url = _safe_url(page)
            exec_result = execute_agent_action(
                page,
                action,
                company=target_company,
                job_title=target_title,
                allow_final_submit=False,
            )
            after_url = _safe_url(page)
            history_item = {
                "step": step,
                "action": "create_site_account",
                "target": action["target_text"],
                "ok": exec_result.ok,
                "message": exec_result.message,
                "before_url": before_url,
                "after_url": after_url,
                "reason": action["reason"],
                "confidence": 1.0,
            }
            history.append(history_item)
            append_event({"kind": "web_apply_action", **history_item, "target_company": target_company, "target_title": target_title})
            if exec_result.ok:
                print(f"    ✓ {exec_result.message}")
                # If the account helper made progress, keep observing. If it reports
                # that it filled nothing and clicked nothing, stop instead of looping
                # the deterministic account handler forever on the same SuccessFactors
                # shell. This usually means email verification, duplicate-account
                # login, or a non-observed/blocked SAP control needs review.
                if "fields=0" in exec_result.message and "terms_checked=0" in exec_result.message and "No visible account fields" in exec_result.message:
                    result = WebApplyResult(True, "account_gate_needs_review", exec_result.message, after_url or before_url, step)
                    print(f"  ✓ Agent terminal: {result.method} — {result.reason}")
                    return result
                continue
            print(f"    ⚠ {exec_result.message}")
            account_gate_no_progress_count += 1
            if "No visible account fields" in exec_result.message or "create/continue controls" in exec_result.message:
                result = WebApplyResult(True, "account_gate_needs_review", exec_result.message, after_url or before_url, step)
                print(f"  ✓ Agent terminal: {result.method} — {result.reason}")
                return result
            if account_gate_no_progress_count >= 2:
                result = WebApplyResult(False, "account_gate_failed", exec_result.message, after_url or before_url, step)
                print(f"  ⚠ Agent terminal: {result.method} — {result.reason}")
                return result
            continue

        if state == "final_review_or_submit":
            result = WebApplyResult(True, "final_review", "Reached final external submit/review step. Stopping as requested.", url, step)
            print(f"  ✓ Agent terminal: {result.method} — {result.reason}")
            return result

        prompt = _build_prompt(
            target_title=target_title,
            target_company=target_company,
            snapshot=snapshot,
            history=history,
        )

        try:
            action = _ask_model(prompt)
        except Exception as exc:
            return WebApplyResult(False, "agent_error", f"OpenAI agent call failed: {exc}", url, step)

        if not isinstance(action, dict):
            return WebApplyResult(False, "agent_error", "Agent returned non-dict action.", url, step)

        kind = str(action.get("action") or "").lower().strip()
        reason = str(action.get("reason") or "").strip()
        confidence = action.get("confidence", "")

        print(f"  → Agent action: {kind}")
        if action.get("target_text") or action.get("target_ref") or action.get("url"):
            print(f"    Target: {action.get('target_text') or action.get('target_ref') or action.get('url')}")
        if reason:
            print(f"    Reason: {reason}")

        if kind == "stop":
            stop_reason = str(action.get("stop_reason") or "stopped")
            result = WebApplyResult(True, stop_reason, reason or f"Agent stopped: {stop_reason}", url, step)
            append_event({
                "kind": "web_apply_stop",
                "stop_reason": stop_reason,
                "reason": result.reason,
                "url": url,
                "target_company": target_company,
                "target_title": target_title,
            })
            print(f"  ✓ Agent stopped: {stop_reason} — {result.reason}")
            return result

        if kind == "save_memory":
            record_failure_memory(url, str(action.get("value") or reason), pattern=str(action.get("target_text") or "agent_memory"))
            history.append({"step": step, "action": "save_memory", "ok": True, "reason": reason})
            continue

        if _action_maybe_final_submit(action):
            result = WebApplyResult(True, "final_review", "Agent reached final external submit/review step and stopped as requested.", url, step)
            print(f"  ✓ Agent terminal: {result.method} — {result.reason}")
            return result

        if kind == "open_url":
            safe_url, guard_message = _resolve_safe_open_url(action, snapshot, history, initial_url)
            if not safe_url:
                print(f"    ⚠ {guard_message}")
                history_item = {
                    "step": step,
                    "action": kind,
                    "target": action.get("target_text") or action.get("target_ref") or action.get("url"),
                    "ok": False,
                    "message": guard_message,
                    "before_url": url,
                    "after_url": getattr(page, "url", ""),
                    "reason": reason,
                    "confidence": confidence,
                }
                history.append(history_item)
                append_event({"kind": "web_apply_action_blocked", **history_item, "target_company": target_company, "target_title": target_title})
                recent_open_blocks = [h for h in history[-5:] if h.get("action") == "open_url" and not h.get("ok")]
                if len(recent_open_blocks) >= 3:
                    record_failure_memory(url, "Agent repeatedly tried to open unobserved/reconstructed URLs; it should stay on the current page and use visible controls.", pattern="blocked_reconstructed_urls")
                    return WebApplyResult(False, "stuck", "Agent repeatedly tried to open unsafe reconstructed URLs.", url, step)
                continue
            if guard_message:
                print(f"    ✓ {guard_message}")
            action = dict(action)
            action["url"] = safe_url
            action["value"] = safe_url

        before_url = _safe_url(page)
        try:
            exec_result = execute_agent_action(
            page,
            action,
            company=target_company,
            job_title=target_title,
            allow_final_submit=False,
            )
        except Exception as exc:
            replacement = _live_page(page)
            if replacement is not page:
                page = replacement
                exec_result = ActionResult(True, f"Browser target was replaced after action; switched to live page: {_safe_url(page)}", changed_url=True)
            else:
                return WebApplyResult(False, "page_closed", f"Browser action crashed because the page/context closed: {exc}", before_url, step)
        page = _live_page(page)
        after_url = _safe_url(page)

        history_item = {
            "step": step,
            "action": kind,
            "target": action.get("target_text") or action.get("target_ref") or action.get("url"),
            "ok": exec_result.ok,
            "message": exec_result.message,
            "before_url": before_url,
            "after_url": after_url,
            "reason": reason,
            "confidence": confidence,
        }
        history.append(history_item)
        append_event({"kind": "web_apply_action", **history_item, "target_company": target_company, "target_title": target_title})

        if exec_result.ok:
            print(f"    ✓ {exec_result.message}")
        else:
            print(f"    ⚠ {exec_result.message}")
            # Let the model see the failure once; if failures accumulate, stop.
            recent_failures = [h for h in history[-4:] if not h.get("ok")]
            if len(recent_failures) >= 3:
                record_failure_memory(after_url or before_url, "Several consecutive browser actions failed.", pattern="action_failures")
                return WebApplyResult(False, "action_failures", "Several consecutive agent browser actions failed.", after_url or before_url, step)

        # Re-check final review after action; this catches pages that show submit after fills.
        page = _live_page(page)
        try:
            post_snapshot = observe_page(page)
        except Exception as exc:
            return WebApplyResult(False, "page_closed", f"Browser page was closed after action: {exc}", after_url or before_url, step)
        controls_text = " ".join(str(c.get("text") or c.get("label") or "") for c in (post_snapshot.get("controls") or []) if isinstance(c, dict))
        if post_snapshot.get("state") == "final_review_or_submit" or re.search(r"submit application|review and submit|final step", controls_text, re.I):
            result = WebApplyResult(True, "final_review", "Reached final external submit/review step. Stopping as requested.", str(post_snapshot.get("url") or after_url), step)
            print(f"  ✓ Agent terminal: {result.method} — {result.reason}")
            return result

    final_url = _safe_url(page)
    record_failure_memory(final_url, "Agent reached max steps before reaching a terminal application state.", pattern="max_steps", action_sequence=[str(h.get("action")) for h in history[-10:]])
    return WebApplyResult(False, "max_steps", "Web apply agent reached max steps before a terminal state.", final_url, max_steps)
