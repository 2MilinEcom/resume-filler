from __future__ import annotations

import json
import os
import re
import secrets
import string
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Optional
from urllib.parse import urlparse

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


JOBISH_HREF_MARKERS = [
    "/job/",
    "/jobs/",
    "/career/",
    "/careers/",
    "jobid=",
    "job_id=",
    "jobreq",
    "requisition",
]

BAD_HREF_MARKERS = [
    "facebook.com",
    "twitter.com",
    "x.com",
    "linkedin.com/company",
    "youtube.com",
    "instagram.com",
    "mailto:",
    "privacy",
    "terms",
    "site-map",
    "sitemap",
    "feedback",
    "cookie",
    "language",
]

BAD_LINK_TEXT = {
    "home",
    "about",
    "about qorvo careers",
    "jobs by career area",
    "language",
    "sign in",
    "site map",
    "feedback",
    "terms of use",
    "privacy policy",
    "learn more",
    "learn more about internships & recent college graduate positions at qorvo",
    "show more options",
}


@dataclass
class ExternalResolveResult:
    ok: bool
    method: str
    reason: str
    url: Optional[str] = None
    score: float = 0.0


def _truthy(value: str | None, default: str = "true") -> bool:
    return str(value if value is not None else default).strip().lower() in {
        "1",
        "true",
        "yes",
        "y",
        "on",
    }


def external_site_agent_enabled() -> bool:
    return _truthy(os.getenv("EXTERNAL_SITE_AGENT_ENABLED", "true"))


def _normalize(text: Any) -> str:
    text = str(text or "").lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _tokens(text: Any) -> list[str]:
    stop = {
        "job",
        "jobs",
        "career",
        "careers",
        "opening",
        "position",
        "role",
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "for",
        "to",
        "in",
        "at",
        "with",
        "inc",
        "llc",
        "corp",
        "co",
        "company",
        "utm",
        "source",
        "handshake",
        "2026",
        "2027",
        "2028",
        "8199958",
    }

    result = []
    for token in _normalize(text).split():
        if len(token) <= 1:
            continue
        if token in stop:
            continue
        result.append(token)
    return result


def _stem(token: str) -> str:
    token = token.lower().strip()
    variants = {
        "engineering": "engineer",
        "engineer": "engineer",
        "software": "software",
        "firmware": "firmware",
        "internship": "intern",
        "intern": "intern",
        "swe": "software",
        "developer": "software",
        "development": "software",
    }
    return variants.get(token, token)


def _token_set(text: Any) -> set[str]:
    return {_stem(t) for t in _tokens(text)}


def _path_text(url: str) -> str:
    try:
        parsed = urlparse(url)
        return re.sub(r"[-_/]+", " ", parsed.path)
    except Exception:
        return ""


def _query_from_target(title: str, original_url: str = "") -> str:
    combined = f"{title} {_path_text(original_url)}"
    toks = _tokens(combined)
    preferred = []
    for token in toks:
        s = _stem(token)
        if s in {"software", "firmware", "engineer", "intern", "research", "data", "machine", "learning", "product", "application", "applications"}:
            preferred.append(token)
    if preferred:
        return " ".join(dict.fromkeys(preferred) or toks[:5])
    return " ".join(toks[:5]) or title


def _is_bad_candidate(text: str, href: str) -> bool:
    href_l = (href or "").lower()
    text_l = _normalize(text)
    if not href_l:
        return True
    if any(marker in href_l for marker in BAD_HREF_MARKERS):
        return True
    if text_l in BAD_LINK_TEXT:
        return True
    if href_l.startswith("javascript:") or href_l.startswith("#"):
        return True
    return False


def _score_link(
    link: dict[str, Any],
    *,
    target_title: str,
    target_company: str = "",
    original_url: str = "",
) -> float:
    text = str(link.get("text") or "")
    href = str(link.get("href") or "")
    row = str(link.get("row_text") or "")
    context = f"{text} {row} {href}"

    if _is_bad_candidate(text, href):
        return -100.0

    target_tokens = _token_set(f"{target_title} {_path_text(original_url)}")
    context_tokens = _token_set(context)

    if not target_tokens or not context_tokens:
        return 0.0

    intersection = target_tokens & context_tokens
    coverage = len(intersection) / max(1, len(target_tokens))
    jaccard = len(intersection) / max(1, len(target_tokens | context_tokens))

    score = coverage * 70 + jaccard * 30

    # Role keywords matter more than IDs and generic text.
    important = {"software", "firmware", "engineer", "intern", "research", "data", "machine", "learning"}
    score += 8 * len((target_tokens & important) & context_tokens)

    href_l = href.lower()
    text_l = _normalize(text)
    row_l = _normalize(row)

    if any(marker in href_l for marker in JOBISH_HREF_MARKERS):
        score += 20

    if "/go/" in href_l:
        score -= 18

    if text_l:
        ratio = SequenceMatcher(None, _normalize(target_title), text_l).ratio()
        score += ratio * 25

    # Location / page-path clues from URLs like Richardson-Software-Engineer-Intern-TX-75080.
    path_tokens = set(_tokens(_path_text(original_url)))
    clue_tokens = {t for t in path_tokens if t not in {"job", "jobs"}}
    if clue_tokens:
        score += 5 * len(clue_tokens & context_tokens)

    # If the row includes location that also appears in the original URL, reward it.
    for clue in ["richardson", "austin", "san jose", "california", "texas", "tx", "ca", "nc", "ma", "fl"]:
        clue_norm = _normalize(clue)
        if clue_norm in _normalize(original_url) and clue_norm in row_l:
            score += 12

    if target_company and _normalize(target_company) in _normalize(context):
        score += 5

    return score


def collect_external_site_snapshot(page) -> dict[str, Any]:
    js = r"""
    () => {
      const norm = s => (s || '').replace(/\s+/g, ' ').trim();
      function visible(el) {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
      }
      const links = Array.from(document.querySelectorAll('a[href]')).map((a, i) => {
        let rowText = '';
        const row = a.closest('tr, li, article, section, div');
        if (row) rowText = norm(row.innerText || row.textContent || '');
        return {
          index: i + 1,
          text: norm(a.innerText || a.textContent || a.getAttribute('aria-label') || ''),
          href: a.href,
          title: a.getAttribute('title') || '',
          row_text: rowText.slice(0, 1000),
          visible: visible(a)
        };
      }).filter(x => x.href);

      const inputs = Array.from(document.querySelectorAll('input, textarea')).filter(visible).map((el, i) => ({
        index: i + 1,
        tag: el.tagName.toLowerCase(),
        type: (el.getAttribute('type') || '').toLowerCase(),
        value: el.value || '',
        placeholder: el.getAttribute('placeholder') || '',
        aria_label: el.getAttribute('aria-label') || '',
        name: el.getAttribute('name') || '',
        id: el.getAttribute('id') || ''
      }));

      const buttons = Array.from(document.querySelectorAll('button, input[type="submit"], input[type="button"]')).filter(visible).map((b, i) => ({
        index: i + 1,
        text: norm(b.innerText || b.textContent || b.value || b.getAttribute('aria-label') || ''),
        type: b.getAttribute('type') || '',
        disabled: !!b.disabled
      })).filter(b => b.text);

      return {
        url: window.location.href,
        title: document.title,
        body_text: norm(document.body ? document.body.innerText : '').slice(0, 25000),
        links,
        inputs,
        buttons,
      };
    }
    """
    try:
        snapshot = page.evaluate(js)
        if isinstance(snapshot, dict):
            return snapshot
    except Exception as exc:
        return {
            "url": getattr(page, "url", ""),
            "title": "",
            "body_text": "",
            "links": [],
            "inputs": [],
            "buttons": [],
            "snapshot_error": repr(exc),
        }

    return {
        "url": getattr(page, "url", ""),
        "title": "",
        "body_text": "",
        "links": [],
        "inputs": [],
        "buttons": [],
        "snapshot_error": "snapshot returned non-dict",
    }


def _best_link_from_snapshot(
    snapshot: dict[str, Any],
    *,
    target_title: str,
    target_company: str = "",
    original_url: str = "",
) -> tuple[Optional[dict[str, Any]], float]:
    links = snapshot.get("links") or []
    best: tuple[Optional[dict[str, Any]], float] = (None, -100.0)

    for link in links:
        if not isinstance(link, dict):
            continue
        score = _score_link(
            link,
            target_title=target_title,
            target_company=target_company,
            original_url=original_url or str(snapshot.get("url") or ""),
        )
        if score > best[1]:
            best = (link, score)

    return best


def _openai_choose_link(
    snapshot: dict[str, Any],
    *,
    target_title: str,
    target_company: str = "",
    original_url: str = "",
) -> Optional[str]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None

    links = []
    for link in (snapshot.get("links") or [])[:120]:
        if not isinstance(link, dict):
            continue
        href = str(link.get("href") or "")
        text = str(link.get("text") or "")
        row = str(link.get("row_text") or "")[:350]
        if _is_bad_candidate(text, href):
            continue
        links.append({"text": text, "href": href, "row_text": row})

    if not links:
        return None

    prompt = f"""
You are resolving an external employer careers page to the exact job posting the applicant intended to apply to.
Return JSON only with this shape:
{{"chosen_href": "https://... or null", "confidence": 0.0, "reason": "brief"}}

Target job title from Handshake: {target_title}
Target company: {target_company or 'unknown'}
Original captured URL: {original_url or snapshot.get('url')}
Current page title: {snapshot.get('title')}

Rules:
- Choose the most likely actual job posting link, not category pages, home pages, alerts, sign-in, social media, privacy, or terms.
- Prefer links whose title/row/location match the target job.
- If this is a listing page/table and the target job appears in the table, choose that row's job link.
- If no likely job posting exists, use null.

Candidate links:
{json.dumps(links, ensure_ascii=False)[:45000]}
""".strip()

    try:
        from openai import OpenAI
        client = OpenAI()
        model = os.getenv("EXTERNAL_SITE_AGENT_MODEL", "gpt-5-mini").strip() or "gpt-5-mini"
        response = client.responses.create(model=model, input=prompt)
        text = response.output_text.strip()
        match = re.search(r"\{.*\}", text, flags=re.S)
        parsed = json.loads(match.group(0) if match else text)
        href = parsed.get("chosen_href")
        confidence = float(parsed.get("confidence") or 0)
        if href and confidence >= 0.60:
            print(f"  ✓ External page agent chose job link: {href}")
            print(f"    Reason: {parsed.get('reason', '')}")
            return str(href)
    except Exception as exc:
        print(f"  ⚠ External page OpenAI resolver failed safely: {exc}")

    return None


def _dismiss_cookie_banner(page) -> None:
    # Cookie banners often cover the Qorvo table. Prefer privacy-preserving choices
    # when available, but accept if that is the only way to unblock navigation.
    choices = [
        "Reject All",
        "Reject all",
        "Decline",
        "Only necessary",
        "Accept All",
        "Accept all",
        "Accept",
        "I Accept",
    ]
    for text in choices:
        try:
            btn = page.get_by_role("button", name=re.compile(rf"^{re.escape(text)}$", re.I))
            if btn.count() and btn.first.is_visible():
                btn.first.click(timeout=1500)
                page.wait_for_timeout(500)
                return
        except Exception:
            continue


def _try_search_box(page, query: str) -> bool:
    if not query:
        return False

    try:
        # Common SuccessFactors/Qorvo search field.
        candidates = [
            page.locator("input[placeholder*='Search']").first,
            page.locator("input[aria-label*='Search']").first,
            page.locator("input[name*='search']").first,
            page.locator("input[name='q']").first,
            page.locator("input[type='search']").first,
            page.locator("input[type='text']").first,
        ]
        field = None
        for candidate in candidates:
            try:
                if candidate.count() and candidate.is_visible() and candidate.is_enabled():
                    field = candidate
                    break
            except Exception:
                continue

        if field is None:
            return False

        print(f"  Searching external career page for: {query}")
        field.fill(query, timeout=4000)
        page.wait_for_timeout(250)

        button_names = ["Search Jobs", "Search jobs", "Search", "Go"]
        for name in button_names:
            try:
                btn = page.get_by_role("button", name=re.compile(rf"^{re.escape(name)}$", re.I))
                if btn.count() and btn.first.is_visible() and btn.first.is_enabled():
                    btn.first.click(timeout=5000)
                    page.wait_for_load_state("domcontentloaded", timeout=12000)
                    page.wait_for_timeout(1000)
                    return True
            except Exception:
                continue

        try:
            field.press("Enter")
            page.wait_for_load_state("domcontentloaded", timeout=12000)
            page.wait_for_timeout(1000)
            return True
        except Exception:
            return False

    except Exception:
        return False


def _click_apply_if_present(page) -> bool:
    names = [
        "Apply Now",
        "Apply now",
        "Apply",
        "Apply for this job",
        "Apply for Job",
        "Apply to this job",
    ]
    for name in names:
        try:
            control = page.get_by_role("link", name=re.compile(rf"^{re.escape(name)}$", re.I))
            if control.count() and control.first.is_visible():
                print(f"  Clicking external job action: {name}")
                control.first.click(timeout=8000)
                page.wait_for_load_state("domcontentloaded", timeout=15000)
                page.wait_for_timeout(1000)
                return True
        except Exception:
            pass

        try:
            control = page.get_by_role("button", name=re.compile(rf"^{re.escape(name)}$", re.I))
            if control.count() and control.first.is_visible() and control.first.is_enabled():
                print(f"  Clicking external job action: {name}")
                control.first.click(timeout=8000)
                page.wait_for_load_state("domcontentloaded", timeout=15000)
                page.wait_for_timeout(1000)
                return True
        except Exception:
            pass

    return False


def resolve_external_job_page(
    page,
    *,
    target_title: str,
    target_company: str = "",
    original_url: str = "",
) -> ExternalResolveResult:
    """
    Resolve employer landing/category pages to the most likely actual job posting.

    Example: Qorvo /go/Internships-&-Recent-College-Grads page contains a table of
    123 internships. This function scores the table links against the original
    Handshake job title/URL and navigates to the matching job row.
    """
    if not external_site_agent_enabled():
        return ExternalResolveResult(False, "disabled", "External site resolver disabled.")

    print("\n===== EXTERNAL SITE RESOLVER =====")
    print(f"  Target: {target_company + ' — ' if target_company else ''}{target_title}")

    _dismiss_cookie_banner(page)

    for attempt in range(1, 4):
        try:
            page.wait_for_timeout(700)
        except Exception:
            pass

        snapshot = collect_external_site_snapshot(page)
        current_url = str(snapshot.get("url") or getattr(page, "url", ""))

        # Already on a plausible job detail page.
        body_norm = _normalize(snapshot.get("body_text"))
        title_norm = _normalize(target_title)
        if (
            any(marker in current_url.lower() for marker in ["/job/", "/jobs/"])
            and ("apply" in body_norm or "job description" in body_norm or "responsibilities" in body_norm)
        ):
            print("  ✓ Already on a likely external job detail page")
            _click_apply_if_present(page)
            return ExternalResolveResult(True, "already_job_page", "Already on likely job detail page.", current_url, 100.0)

        best, score = _best_link_from_snapshot(
            snapshot,
            target_title=target_title,
            target_company=target_company,
            original_url=original_url or current_url,
        )

        if best and score >= 58:
            href = str(best.get("href") or "")
            text = str(best.get("text") or "").strip()
            print(f"  ✓ Found likely job link on external page: {text or href}")
            print(f"    Score: {score:.1f}")
            print(f"    URL:   {href}")
            try:
                page.goto(href, wait_until="domcontentloaded", timeout=45000)
                try:
                    page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
                page.wait_for_timeout(1000)
                _dismiss_cookie_banner(page)
                _click_apply_if_present(page)
                return ExternalResolveResult(True, "deterministic_link", f"Matched external job link: {text}", href, score)
            except Exception as exc:
                return ExternalResolveResult(False, "navigation_failed", f"Could not open matched external job link: {exc}", href, score)

        # Use search box after first pass if the page looks like a search/listing page.
        if attempt == 1:
            query = _query_from_target(target_title, original_url or current_url)
            if _try_search_box(page, query):
                continue

        href = _openai_choose_link(
            snapshot,
            target_title=target_title,
            target_company=target_company,
            original_url=original_url or current_url,
        )
        if href:
            try:
                page.goto(href, wait_until="domcontentloaded", timeout=45000)
                try:
                    page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
                page.wait_for_timeout(1000)
                _dismiss_cookie_banner(page)
                _click_apply_if_present(page)
                return ExternalResolveResult(True, "openai_link", "OpenAI selected a job link from the external page.", href, 75.0)
            except Exception as exc:
                return ExternalResolveResult(False, "openai_navigation_failed", f"Could not open OpenAI-selected link: {exc}", href, 75.0)

        break

    return ExternalResolveResult(False, "no_match", "No likely job link found on external employer page.")


# ---------------------------------------------------------------------
# AI-FIRST EXTERNAL APPLY NAVIGATION
# ---------------------------------------------------------------------
# After the resolver reaches an employer job detail page, keep navigating the
# employer's own Apply / Apply Now / Apply Manually flow until we reach a real
# application form, a supported platform, an account/login gate, or a safe stop.

APPLY_ACTION_POSITIVE = re.compile(
    r"\b(apply|apply now|apply manually|apply with|start application|begin application|continue application|continue|next|create profile|new candidate|sign in|login)\b",
    re.I,
)

APPLY_ACTION_NEGATIVE = re.compile(
    r"(create alert|job alert|search jobs|search|language|view profile|home|about|privacy|terms|cookie|share|facebook|linkedin|twitter|youtube|saved|save job)",
    re.I,
)


def _classify_external_apply_state(snapshot: dict[str, Any]) -> str:
    body = _normalize(snapshot.get("body_text") or "")
    url = str(snapshot.get("url") or "").lower()

    if "greenhouse.io" in url:
        return "greenhouse"

    if any(marker in body for marker in ["captcha", "verify you are human", "human verification"]):
        return "human_verification"

    # Account gates must be detected before generic form detection because
    # SuccessFactors create-account pages contain many ordinary inputs.
    account_markers = [
        "create an account",
        "career opportunities create an account",
        "already have an account",
        "already a registered user",
        "choose password",
        "retype password",
        "retype email address",
        "new candidate",
        "returning candidate",
        "sign in to apply",
        "login to apply",
        "log in to apply",
    ]
    if any(marker in body for marker in account_markers):
        return "account_gate"

    # Real application forms generally expose several of these fields at once.
    form_markers = [
        "first name",
        "last name",
        "email address",
        "phone",
        "resume",
        "upload resume",
        "cover letter",
        "linkedin",
        "work authorization",
        "application form",
        "my information",
        "candidate information",
    ]
    marker_count = sum(1 for marker in form_markers if marker in body)

    inputs = snapshot.get("inputs") or []
    visible_input_count = len(inputs) if isinstance(inputs, list) else 0

    if marker_count >= 3 or visible_input_count >= 5:
        return "application_form"

    return "job_or_listing_page"


def _visible_apply_candidates(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    for button in snapshot.get("buttons") or []:
        if not isinstance(button, dict):
            continue
        text = str(button.get("text") or "").strip()
        if not text:
            continue
        if button.get("disabled"):
            continue
        if APPLY_ACTION_NEGATIVE.search(text):
            continue
        if APPLY_ACTION_POSITIVE.search(text):
            candidates.append({
                "kind": "button",
                "text": text,
                "href": "",
            })

    for link in snapshot.get("links") or []:
        if not isinstance(link, dict):
            continue
        if link.get("visible") is False:
            continue
        text = str(link.get("text") or link.get("title") or "").strip()
        href = str(link.get("href") or "").strip()
        row = str(link.get("row_text") or "")[:400]
        combined = f"{text} {row}"
        if not text or not href:
            continue
        if APPLY_ACTION_NEGATIVE.search(combined) or APPLY_ACTION_NEGATIVE.search(href):
            continue
        if APPLY_ACTION_POSITIVE.search(combined) or "apply" in href.lower():
            candidates.append({
                "kind": "link",
                "text": text,
                "href": href,
            })

    # Prefer more specific application actions before generic Apply Now.
    def priority(item: dict[str, Any]) -> tuple[int, int]:
        text_l = _normalize(item.get("text") or "")
        priorities = [
            ("apply manually", 0),
            ("apply with resume", 1),
            ("apply with cv", 1),
            ("start application", 2),
            ("begin application", 2),
            ("continue application", 3),
            ("new candidate", 4),
            ("create profile", 4),
            ("apply now", 5),
            ("apply", 6),
            ("continue", 7),
            ("next", 8),
            ("sign in", 9),
            ("login", 9),
        ]
        for phrase, value in priorities:
            if phrase in text_l:
                return (value, len(text_l))
        return (50, len(text_l))

    deduped: list[dict[str, Any]] = []
    seen = set()
    for item in sorted(candidates, key=priority):
        key = (item.get("kind"), _normalize(item.get("text")), item.get("href"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    return deduped[:20]


def _openai_choose_external_apply_action(
    snapshot: dict[str, Any],
    *,
    target_title: str,
    target_company: str = "",
) -> Optional[dict[str, Any]]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None

    candidates = _visible_apply_candidates(snapshot)
    if not candidates:
        return None

    prompt = f"""
You are navigating an employer career site after the correct job posting has been found.
Choose the safest next visible action to START or CONTINUE the application.
Return JSON only:
{{"action_index": 0, "confidence": 0.0, "reason": "brief"}}

Target job: {target_company + ' — ' if target_company else ''}{target_title}
Current URL: {snapshot.get('url')}
Page title: {snapshot.get('title')}
Detected page state: {_classify_external_apply_state(snapshot)}

Rules:
- Prefer actions like Apply Manually, Apply with Resume, Start Application, Apply Now, Continue Application.
- Do not choose Create Alert, Search Jobs, View Profile, Language, social links, privacy/terms, or job-category navigation.
- It is okay to click a login/create-profile gate if that is the next required step to apply.
- Do not submit a completed application; only navigate to the form/login/application flow.
- If none are safe, use action_index null.

Candidate actions, zero-indexed:
{json.dumps(candidates, ensure_ascii=False)[:20000]}
""".strip()

    try:
        from openai import OpenAI
        client = OpenAI()
        model = os.getenv("EXTERNAL_SITE_AGENT_MODEL", "gpt-5-mini").strip() or "gpt-5-mini"
        response = client.responses.create(model=model, input=prompt)
        text = response.output_text.strip()
        match = re.search(r"\{.*\}", text, flags=re.S)
        parsed = json.loads(match.group(0) if match else text)
        idx = parsed.get("action_index")
        confidence = float(parsed.get("confidence") or 0)
        if idx is None or confidence < 0.55:
            return None
        idx = int(idx)
        if idx < 0 or idx >= len(candidates):
            return None
        chosen = dict(candidates[idx])
        chosen["reason"] = parsed.get("reason", "")
        chosen["confidence"] = confidence
        return chosen
    except Exception as exc:
        print(f"  ⚠ External apply-action AI failed safely: {exc}")
        return None


def _finish_external_click_wait(page, before_pages) -> None:
    """Wait after an external navigation click and fold popups back into the active tab."""
    try:
        page.wait_for_timeout(1200)
        new_pages = list(set(page.context.pages) - before_pages)
        if new_pages:
            popup = new_pages[-1]
            try:
                popup.wait_for_load_state("domcontentloaded", timeout=12_000)
            except Exception:
                pass
            try:
                target_url = popup.url
                if target_url and target_url != "about:blank":
                    page.goto(target_url, wait_until="domcontentloaded", timeout=45_000)
            finally:
                try:
                    popup.close()
                except Exception:
                    pass
    except Exception:
        pass

    try:
        page.wait_for_load_state("domcontentloaded", timeout=12_000)
    except Exception:
        pass
    try:
        page.wait_for_load_state("networkidle", timeout=8_000)
    except Exception:
        pass
    try:
        page.wait_for_timeout(1000)
    except Exception:
        pass


def _click_visible_apply_menu_item(page, parent_rect: dict[str, Any] | None = None) -> bool:
    """
    Some career sites, especially SuccessFactors skins, use a split button:
    clicking "Apply now" only opens a small menu, then the actual navigation is
    a menu item also named "Apply Now". This clicks the real revealed menu item.
    """
    js = r"""
    ({ parentRect }) => {
      function norm(s) {
        return (s || '').replace(/\s+/g, ' ').trim();
      }
      function visible(el) {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
      }
      function isApplyText(text, href) {
        const t = (text || '').toLowerCase();
        const h = (href || '').toLowerCase();
        if (/create alert|search jobs|view profile|language|privacy|terms|home|facebook|linkedin company/.test(t + ' ' + h)) return false;
        return /apply|start application|continue application|new candidate|create profile/.test(t + ' ' + h);
      }
      const parent = parentRect || null;
      const els = Array.from(document.querySelectorAll(
        'a[href], button, [role="menuitem"], [role="option"], input[type="submit"], input[type="button"]'
      )).filter(visible).filter(el => !el.disabled && el.getAttribute('aria-disabled') !== 'true');

      const candidates = [];
      for (const el of els) {
        const text = norm(el.innerText || el.textContent || el.value || el.getAttribute('aria-label') || '');
        const href = el.href || el.getAttribute('href') || '';
        if (!isApplyText(text, href)) continue;
        const rect = el.getBoundingClientRect();

        let score = 0;
        const low = text.toLowerCase();
        const lowHref = String(href || '').toLowerCase();

        // Prefer the menu item opened below the split button.
        if (parent) {
          const belowParent = rect.top >= parent.top - 8;
          const closeToParent = rect.top <= parent.bottom + 260;
          const horizontalOverlap = !(rect.right < parent.left - 60 || rect.left > parent.right + 60);
          const sameBox = Math.abs(rect.top - parent.top) < 6 && Math.abs(rect.left - parent.left) < 6;
          if (belowParent && closeToParent && horizontalOverlap && !sameBox) score += 100;
        }

        const role = (el.getAttribute('role') || '').toLowerCase();
        const cls = (el.className || '').toString().toLowerCase();
        if (role.includes('menuitem') || cls.includes('dropdown') || cls.includes('menu')) score += 50;
        if (low === 'apply now' || low === 'apply now »' || low === 'apply') score += 40;
        if (low.includes('apply manually') || low.includes('new candidate') || low.includes('create profile')) score += 45;
        if (low.includes('linkedin')) score -= 25;
        if (lowHref.includes('apply') || lowHref.includes('talentcommunity')) score += 20;
        if (score > 0) candidates.push({ el, score, text, href, top: rect.top });
      }

      candidates.sort((a, b) => b.score - a.score || a.top - b.top);
      if (!candidates.length) return { ok: false, reason: 'no revealed apply menu item' };
      candidates[0].el.scrollIntoView({ block: 'center' });
      candidates[0].el.click();
      return { ok: true, text: candidates[0].text, href: candidates[0].href };
    }
    """
    try:
        result = page.evaluate(js, {"parentRect": parent_rect or None})
        if isinstance(result, dict) and result.get("ok"):
            label = result.get("text") or result.get("href") or "revealed apply menu item"
            print(f"  ✓ Clicked revealed apply menu item: {label}")
            return True
    except Exception:
        pass
    return False


def _click_action_item(page, item: dict[str, Any]) -> bool:
    kind = str(item.get("kind") or "")
    text = str(item.get("text") or "").strip()
    href = str(item.get("href") or "").strip()

    if not text and not href:
        return False

    # Prefer a real DOM click over direct page.goto for employer apply links.
    # Sites such as Cargill/SuccessFactors can route direct href navigation to a
    # generic jobs homepage, while a browser click carries the correct page state.
    js = r"""
    ({ text, href }) => {
      function norm(s) {
        return (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
      }
      function visible(el) {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
      }
      const wantedText = norm(text);
      const wantedHref = href || '';
      const els = Array.from(document.querySelectorAll('a[href], button, input[type="submit"], input[type="button"], [role="menuitem"]'))
        .filter(visible)
        .filter(el => !el.disabled && el.getAttribute('aria-disabled') !== 'true');

      let matches = [];
      for (const el of els) {
        const elText = norm(el.innerText || el.textContent || el.value || el.getAttribute('aria-label') || '');
        const elHref = el.href || el.getAttribute('href') || '';
        let score = 0;
        if (wantedHref && elHref === wantedHref) score += 100;
        if (wantedHref && elHref && elHref.split('#')[0] === wantedHref.split('#')[0]) score += 90;
        if (wantedText && elText === wantedText) score += 80;
        if (wantedText && elText.includes(wantedText)) score += 50;
        if (/apply|start application|continue application|new candidate|create profile/i.test(elText + ' ' + elHref)) score += 10;
        if (/create alert|search jobs|view profile|language|privacy|terms|home/i.test(elText + ' ' + elHref)) score -= 100;
        if (score > 0) matches.push({ el, score, top: el.getBoundingClientRect().top });
      }
      matches.sort((a, b) => b.score - a.score || a.top - b.top);
      if (!matches.length) return { ok: false, reason: 'no visible matching element' };
      const rect = matches[0].el.getBoundingClientRect();
      matches[0].el.scrollIntoView({ block: 'center' });
      matches[0].el.click();
      return {
        ok: true,
        rect: { top: rect.top, bottom: rect.bottom, left: rect.left, right: rect.right, width: rect.width, height: rect.height }
      };
    }
    """

    try:
        before_pages = set(page.context.pages)
    except Exception:
        before_pages = set()

    try:
        label = text or href
        before_url = getattr(page, "url", "")
        print(f"  Clicking external apply action: {label}")
        result = page.evaluate(js, {"text": text, "href": href})
        if not (isinstance(result, dict) and result.get("ok")):
            raise RuntimeError(result)

        # Give split-button menus/dropdowns a chance to appear. If the URL did
        # not change, click the revealed menu item before declaring progress.
        try:
            page.wait_for_timeout(650)
        except Exception:
            pass

        after_first_click_url = getattr(page, "url", "")
        if after_first_click_url == before_url:
            parent_rect = result.get("rect") if isinstance(result, dict) else None
            if _click_visible_apply_menu_item(page, parent_rect=parent_rect):
                try:
                    page.wait_for_timeout(1000)
                except Exception:
                    pass

        _finish_external_click_wait(page, before_pages)
        return True
    except Exception:
        pass

    # Fallback: direct navigation only after DOM click fails. This is less safe
    # for some career sites, but still useful when links are hidden behind markup.
    if kind == "link" and href and href.lower().startswith(("http://", "https://")):
        try:
            print(f"  Navigating external apply link as fallback: {text or href}")
            page.goto(href, wait_until="domcontentloaded", timeout=45_000)
            try:
                page.wait_for_load_state("networkidle", timeout=12_000)
            except Exception:
                pass
            page.wait_for_timeout(1000)
            return True
        except Exception:
            pass

    return False


def _deterministic_external_apply_action(snapshot: dict[str, Any]) -> Optional[dict[str, Any]]:
    candidates = _visible_apply_candidates(snapshot)
    if not candidates:
        return None
    return candidates[0]


def _external_action_key(action: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(action.get("kind") or ""),
        _normalize(action.get("text") or ""),
        str(action.get("href") or ""),
    )



# ---------------------------------------------------------------------
# ACCOUNT GATE HANDLER
# ---------------------------------------------------------------------
# Some employer sites (notably SuccessFactors) require a lightweight account
# before the application form appears. The user explicitly asked for generated
# account credentials to be saved locally so they can log in later.

def _external_account_creation_enabled() -> bool:
    return _truthy(os.getenv("EXTERNAL_ACCOUNT_CREATION_ENABLED", "false"), "false")


def _external_account_accept_terms_enabled() -> bool:
    return _truthy(os.getenv("EXTERNAL_ACCOUNT_ACCEPT_TERMS", "false"), "false")


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _account_store_path() -> Path:
    return _project_root() / "data" / "site_accounts.json"


def _load_account_store() -> dict[str, Any]:
    path = _account_store_path()
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return {}


def _save_account_store(store: dict[str, Any]) -> None:
    path = _account_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, indent=2, sort_keys=True))
    try:
        path.chmod(0o600)
    except Exception:
        pass


def _account_key(page, company: str = "") -> str:
    try:
        host = urlparse(page.url).netloc.lower()
    except Exception:
        host = "external-site"
    company_key = _normalize(company or "unknown-company").replace(" ", "-") or "unknown-company"
    if "successfactors" in host:
        return f"successfactors:{company_key}"
    return f"{host}:{company_key}"


def _generate_password(length: int = 18) -> str:
    # Avoid spaces/unicode/quotes that break older ATS forms; include all classes.
    alphabet = string.ascii_letters + string.digits + "!@#$%_-+?"
    while True:
        password = "".join(secrets.choice(alphabet) for _ in range(length))
        if (
            any(c.islower() for c in password)
            and any(c.isupper() for c in password)
            and any(c.isdigit() for c in password)
            and any(c in "!@#$%_-+?" for c in password)
        ):
            return password


def _profile_value(name: str, default: str = "") -> str:
    try:
        from src.profile import PROFILE
    except Exception:
        try:
            from profile import PROFILE
        except Exception:
            PROFILE = {}
    return str(PROFILE.get(name, default) or default).strip()


def _account_record_for(page, company: str, title: str) -> dict[str, Any]:
    store = _load_account_store()
    key = _account_key(page, company)
    existing = store.get(key)
    if isinstance(existing, dict) and existing.get("email") and existing.get("password"):
        return dict(existing)

    record = {
        "company": company,
        "job_title": title,
        "site_key": key,
        "host": urlparse(page.url).netloc.lower(),
        "email": _profile_value("email"),
        "password": _generate_password(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_url": page.url,
    }
    store[key] = record
    _save_account_store(store)
    print(f"  ✓ Generated and saved site credentials: {_account_store_path()}")
    return record


def _fill_by_label_text(page, labels: list[str], value: str) -> bool:
    if not value:
        return False
    # Try accessible labels first.
    for label in labels:
        try:
            loc = page.get_by_label(re.compile(label, re.I))
            if loc.count():
                field = loc.first
                if field.is_visible() and field.is_enabled():
                    field.fill(value, timeout=5_000)
                    return True
        except Exception:
            pass

    # Fallback for old SuccessFactors table markup.
    js = r"""
    ({ labels, value }) => {
      function norm(s) { return (s || '').replace(/\s+/g, ' ').trim().toLowerCase(); }
      function visible(el) {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
      }
      const wanted = labels.map(norm);
      const fields = Array.from(document.querySelectorAll('input, textarea')).filter(visible);
      for (const field of fields) {
        const id = field.id;
        let labelText = '';
        if (id) {
          const lab = document.querySelector(`label[for="${CSS.escape(id)}"]`);
          if (lab) labelText += ' ' + norm(lab.innerText || lab.textContent || '');
        }
        const aria = field.getAttribute('aria-label') || '';
        const name = field.getAttribute('name') || '';
        const placeholder = field.getAttribute('placeholder') || '';
        labelText += ' ' + norm(aria + ' ' + name + ' ' + placeholder);
        let parent = field.parentElement;
        for (let depth = 0; parent && depth < 4; depth++, parent = parent.parentElement) {
          labelText += ' ' + norm(parent.innerText || parent.textContent || '');
        }
        if (wanted.some(w => labelText.includes(w))) {
          field.focus();
          field.value = value;
          field.dispatchEvent(new Event('input', { bubbles: true }));
          field.dispatchEvent(new Event('change', { bubbles: true }));
          return true;
        }
      }
      return false;
    }
    """
    try:
        return bool(page.evaluate(js, {"labels": labels, "value": value}))
    except Exception:
        return False


def _select_country_us(page) -> bool:
    choices = ["United States", "United States of America", "USA", "US"]
    try:
        selects = page.locator("select")
        for i in range(selects.count()):
            sel = selects.nth(i)
            try:
                if not sel.is_visible() or not sel.is_enabled():
                    continue
                for choice in choices:
                    try:
                        sel.select_option(label=choice, timeout=2_000)
                        return True
                    except Exception:
                        pass
                    try:
                        sel.select_option(value=choice, timeout=2_000)
                        return True
                    except Exception:
                        pass
            except Exception:
                continue
    except Exception:
        pass
    return False


def _click_account_terms_checkbox(page) -> bool:
    if not _external_account_accept_terms_enabled():
        print("  ⚠ Terms/privacy checkbox present; set EXTERNAL_ACCOUNT_ACCEPT_TERMS=true to auto-accept standard account terms.")
        return False

    js = r"""
    () => {
      function norm(s) { return (s || '').replace(/\s+/g, ' ').trim().toLowerCase(); }
      function visible(el) {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
      }
      const boxes = Array.from(document.querySelectorAll('input[type="checkbox"]')).filter(visible);
      for (const box of boxes) {
        if (box.checked) continue;
        let text = '';
        const id = box.id;
        if (id) {
          const lab = document.querySelector(`label[for="${CSS.escape(id)}"]`);
          if (lab) text += ' ' + norm(lab.innerText || lab.textContent || '');
        }
        let parent = box.parentElement;
        for (let depth = 0; parent && depth < 5; depth++, parent = parent.parentElement) {
          text += ' ' + norm(parent.innerText || parent.textContent || '');
        }
        if (/terms of use|data privacy|privacy statement|read and accept|accept/i.test(text)) {
          box.scrollIntoView({ block: 'center' });
          box.click();
          return true;
        }
      }
      return false;
    }
    """
    try:
        return bool(page.evaluate(js))
    except Exception:
        return False


def _click_by_text(page, patterns: list[str]) -> bool:
    for pattern in patterns:
        rx = re.compile(pattern, re.I)
        for getter in (page.get_by_role, page.get_by_text):
            try:
                if getter is page.get_by_role:
                    for role in ["link", "button"]:
                        loc = page.get_by_role(role, name=rx)
                        if loc.count() and loc.first.is_visible() and loc.first.is_enabled():
                            loc.first.click(timeout=6_000)
                            page.wait_for_timeout(1000)
                            return True
                else:
                    loc = page.get_by_text(rx)
                    if loc.count() and loc.first.is_visible():
                        loc.first.click(timeout=6_000)
                        page.wait_for_timeout(1000)
                        return True
            except Exception:
                pass
    return False


def _click_submit_create_or_signin(page, names: list[str]) -> bool:
    for name in names:
        try:
            button = page.get_by_role("button", name=re.compile(name, re.I))
            if button.count() and button.first.is_visible() and button.first.is_enabled():
                button.first.click(timeout=8_000)
                page.wait_for_timeout(2500)
                return True
        except Exception:
            pass
        try:
            submit = page.locator('input[type="submit"], input[type="button"], button')
            for i in range(submit.count()):
                b = submit.nth(i)
                try:
                    text = (b.get_attribute("value") or b.inner_text() or "").strip()
                    if re.search(name, text, re.I) and b.is_visible() and b.is_enabled():
                        b.click(timeout=8_000)
                        page.wait_for_timeout(2500)
                        return True
                except Exception:
                    continue
        except Exception:
            pass
    return False


def _handle_external_account_gate(page, *, target_title: str, target_company: str = "") -> ExternalResolveResult:
    current_url = getattr(page, "url", "")
    if not _external_account_creation_enabled():
        return ExternalResolveResult(True, "account_gate", "Reached external account/login gate. Account creation disabled.", current_url, 80.0)

    print("\n===== EXTERNAL ACCOUNT GATE =====")
    print(f"  Site: {urlparse(current_url).netloc}")

    try:
        body = _normalize(page.locator("body").inner_text(timeout=3_000))
    except Exception:
        body = ""

    record = _account_record_for(page, target_company, target_title)
    email = record.get("email") or _profile_value("email")
    password = record.get("password")

    # If currently on a sign-in page and credentials already exist, try sign-in.
    if "password" in body and "create an account" in body and "choose password" not in body and "retype password" not in body:
        _fill_by_label_text(page, ["email address", "email"], email)
        _fill_by_label_text(page, ["password"], password)
        if _click_submit_create_or_signin(page, ["sign in", "login", "log in"]):
            print("  ✓ Submitted saved external-site credentials")
            return ExternalResolveResult(True, "account_signed_in", "Signed in with saved local credentials.", getattr(page, "url", current_url), 85.0)

        # Otherwise move to create account.
        if _click_by_text(page, ["create an account", "create account", "new candidate", "create profile"]):
            try:
                page.wait_for_load_state("domcontentloaded", timeout=10_000)
            except Exception:
                pass
            page.wait_for_timeout(1000)

    # Fill create-account page.
    filled = 0
    if _fill_by_label_text(page, ["email address", "email"], email):
        filled += 1
    if _fill_by_label_text(page, ["retype email address", "confirm email", "verify email"], email):
        filled += 1
    if _fill_by_label_text(page, ["choose password", "new password", "password"], password):
        filled += 1
    if _fill_by_label_text(page, ["retype password", "confirm password"], password):
        filled += 1
    if _fill_by_label_text(page, ["first name", "given name"], _profile_value("first_name", "Sample")):
        filled += 1
    if _fill_by_label_text(page, ["last name", "family name", "surname"], _profile_value("last_name", "Applicant")):
        filled += 1
    if _select_country_us(page):
        filled += 1

    terms_ok = _click_account_terms_checkbox(page)
    if terms_ok:
        filled += 1

    print(f"  ✓ Filled external account fields: {filled}")

    if not terms_ok:
        return ExternalResolveResult(True, "account_gate_terms_needed", "Account page filled, but terms/privacy checkbox needs explicit enablement or manual confirmation.", getattr(page, "url", current_url), 75.0)

    if _click_submit_create_or_signin(page, ["create account", "create", "continue", "next"]):
        print("  ✓ Submitted external account creation form")
        try:
            page.wait_for_load_state("domcontentloaded", timeout=15_000)
        except Exception:
            pass
        page.wait_for_timeout(2000)
        return ExternalResolveResult(True, "account_created", "Created/logged into external account with locally saved credentials.", getattr(page, "url", current_url), 90.0)

    return ExternalResolveResult(True, "account_filled", "External account form filled; create/continue button was not clicked.", getattr(page, "url", current_url), 80.0)


def continue_external_apply_navigation(
    page,
    *,
    target_title: str,
    target_company: str = "",
    max_steps: int = 8,
) -> ExternalResolveResult:
    """
    Continue from an employer job details page into the actual application flow.

    This is intentionally navigation-only. It does not submit external ATS forms,
    bypass verification, or invent credentials. It clicks the next safe Apply /
    Apply Manually / Start / Continue action until the tab reaches an application
    form, a login gate, Greenhouse, or a safe stop.
    """
    if not external_site_agent_enabled():
        return ExternalResolveResult(False, "disabled", "External apply navigation disabled.")

    print("\n===== EXTERNAL APPLY NAVIGATOR =====")
    print(f"  Target: {target_company + ' — ' if target_company else ''}{target_title}")

    bad_action_keys: set[tuple[str, str, str]] = set()

    for step in range(1, max_steps + 1):
        _dismiss_cookie_banner(page)
        snapshot = collect_external_site_snapshot(page)
        state = _classify_external_apply_state(snapshot)
        current_url = str(snapshot.get("url") or getattr(page, "url", ""))

        print(f"  Step {step}/{max_steps}: {state}")

        if state == "greenhouse":
            return ExternalResolveResult(True, "greenhouse_reached", "Reached Greenhouse application flow.", current_url, 100.0)

        if state == "application_form":
            return ExternalResolveResult(True, "external_application_form", "Reached an external application form.", current_url, 90.0)

        if state == "account_gate":
            # Account gates are now actionable. The handler can sign in with
            # saved credentials or create a new account when explicitly enabled.
            account_result = _handle_external_account_gate(
                page,
                target_title=target_title,
                target_company=target_company,
            )
            if account_result.method in {"account_created", "account_signed_in"}:
                # Keep navigating after a successful account action.
                continue
            return account_result

        if state == "human_verification":
            return ExternalResolveResult(True, "human_verification", "Reached human verification; manual action required.", current_url, 80.0)

        action = _deterministic_external_apply_action(snapshot)
        chosen_by = "deterministic"

        # Let AI override/choose when several actions are available or when the
        # first deterministic action is generic.
        ai_action = _openai_choose_external_apply_action(
            snapshot,
            target_title=target_title,
            target_company=target_company,
        )
        if ai_action is not None:
            action = ai_action
            chosen_by = "ai"

        if action and _external_action_key(action) in bad_action_keys:
            alternates = [a for a in _visible_apply_candidates(snapshot) if _external_action_key(a) not in bad_action_keys]
            if alternates:
                action = alternates[0]
                chosen_by = "alternate"
            else:
                action = None

        if not action:
            return ExternalResolveResult(False, "no_apply_action", "No safe Apply/Start/Continue action was found on the external page.", current_url, 0.0)

        reason = action.get("reason") or ""
        print(f"  ✓ Next external action ({chosen_by}): {action.get('text') or action.get('href')}")
        if reason:
            print(f"    Reason: {reason}")

        before_url = getattr(page, "url", "")
        clicked = _click_action_item(page, action)
        if not clicked:
            return ExternalResolveResult(False, "action_click_failed", f"Could not click external action: {action.get('text')}", current_url, 0.0)

        _dismiss_cookie_banner(page)
        after_url = getattr(page, "url", "")

        # Some external ATS links incorrectly dump direct navigation at a generic
        # jobs homepage. Detect that loss of job context, go back once, and let
        # the next loop try a different visible action/state rather than stopping
        # on a useless home/search page.
        try:
            after_snapshot = collect_external_site_snapshot(page)
            after_body = _normalize(after_snapshot.get("body_text") or "")
            after_title = _normalize(after_snapshot.get("title") or "")
            target_tokens = _token_set(target_title)
            after_tokens = _token_set((after_snapshot.get("body_text") or "")[:5000] + " " + after_url)
            coverage = len(target_tokens & after_tokens) / max(1, len(target_tokens))
            path = urlparse(after_url).path.strip("/").lower()
            looks_generic_home = (
                coverage < 0.25
                and (
                    path in {"", "en", "en-us", "jobs", "careers", "search-jobs"}
                    or after_title in {"jobs at cargill", "careers", "jobs"}
                    or ("search jobs" in after_body and "create alert" in after_body)
                )
            )
            if looks_generic_home and before_url and before_url != after_url:
                print("  ⚠ Apply action landed on a generic jobs page; returning to the job page and retrying.")
                bad_action_keys.add(_external_action_key(action))
                try:
                    page.goto(before_url, wait_until="domcontentloaded", timeout=45_000)
                    try:
                        page.wait_for_load_state("networkidle", timeout=10_000)
                    except Exception:
                        pass
                    page.wait_for_timeout(1000)
                except Exception:
                    pass
        except Exception:
            pass

        # If the URL did not change and we are still looking at the same kind
        # of job/listing page, this click probably only reopened the same split
        # button menu. Mark it bad so the next loop must choose a different item
        # or stop instead of clicking the parent button forever.
        if after_url == before_url:
            try:
                stagnant_snapshot = collect_external_site_snapshot(page)
                stagnant_state = _classify_external_apply_state(stagnant_snapshot)
                if stagnant_state == state and state == "job_or_listing_page":
                    print("  ⚠ Apply click did not advance the page; avoiding this same action next.")
                    bad_action_keys.add(_external_action_key(action))
                page.wait_for_timeout(1000)
            except Exception:
                pass

    return ExternalResolveResult(False, "max_steps", "External apply navigation reached the step limit before finding a form/login/supported flow.", getattr(page, "url", ""), 0.0)
