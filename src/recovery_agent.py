from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

try:
    from src.profile import PROFILE
except Exception:
    try:
        from profile import PROFILE  # type: ignore
    except Exception:
        PROFILE = {}


SAFE_FILE_KEYS = {"resume", "transcript", "cover_letter", "generated_questionnaire"}
MAX_AGENT_ACTIONS = 8


def _truthy(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def recovery_agent_enabled() -> bool:
    return _truthy(os.getenv("RECOVERY_AGENT_ENABLED", "true"), True)


def _norm(text: Any) -> str:
    text = str(text or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _clean(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _document_path(file_key: str) -> Optional[Path]:
    if file_key not in SAFE_FILE_KEYS:
        return None

    if file_key == "generated_questionnaire":
        try:
            from src.questionnaire_document_agent import latest_generated_questionnaire

            return latest_generated_questionnaire()
        except Exception:
            return None

    value = PROFILE.get(file_key)
    if value:
        path = Path(value).expanduser().resolve()
        if path.exists():
            return path
        print(f"  ⚠ PROFILE[{file_key!r}] points to a missing file: {path}")

    # Fallbacks: look for likely files in documents/.
    try:
        root = Path(__file__).resolve().parent.parent
        docs = root / "documents"
        patterns = []
        if file_key == "resume":
            patterns = ["*Resume*.pdf", "*resume*.pdf"]
        elif file_key == "transcript":
            patterns = ["*Transcript*.pdf", "*transcript*.pdf"]
        elif file_key == "cover_letter":
            patterns = ["*Cover*Letter*.pdf", "*cover*letter*.pdf", "*COVER*LETTER*.pdf", "*Letter*.pdf"]

        for pattern in patterns:
            for candidate in docs.glob(pattern):
                if candidate.exists():
                    print(f"  Using {file_key} fallback file: {candidate.name}")
                    return candidate.resolve()
    except Exception:
        pass

    return None


def _available_documents() -> Dict[str, Dict[str, Any]]:
    docs: Dict[str, Dict[str, Any]] = {}
    for key in sorted(SAFE_FILE_KEYS):
        path = _document_path(key)
        docs[key] = {
            "configured": bool(PROFILE.get(key)),
            "exists": bool(path and path.exists()),
            "filename": path.name if path else None,
        }
    return docs


def _extract_json_object(text: str) -> Dict[str, Any]:
    text = str(text or "").strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

    return {"actions": [], "manual_review": ["Could not parse recovery-agent JSON."]}


def collect_recovery_snapshot(page, context: str = "") -> Dict[str, Any]:
    js = r"""
    () => {
      function norm(s) {
        return (s || "").replace(/\s+/g, " ").trim();
      }

      function visible(el) {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== "none" &&
               style.visibility !== "hidden" &&
               rect.width > 0 &&
               rect.height > 0;
      }

      function shortText(el, limit) {
        return norm(el.innerText || el.textContent || "").slice(0, limit || 600);
      }

      function labelForInput(input) {
        const parts = [];
        const id = input.getAttribute("id");
        if (id) {
          for (const lab of Array.from(document.querySelectorAll("label"))) {
            if (lab.getAttribute("for") === id) {
              parts.push(lab.innerText || lab.textContent || "");
            }
          }
        }
        const wrap = input.closest("label");
        if (wrap) parts.push(wrap.innerText || wrap.textContent || "");
        const section = input.closest("section, fieldset, div");
        if (section) parts.push(shortText(section, 800));
        return norm(parts.filter(Boolean).join(" | "));
      }

      const buttons = Array.from(document.querySelectorAll("button, [role='button'], input[type='submit']"))
        .filter(visible)
        .map((el, index) => ({
          index: index + 1,
          text: norm(el.innerText || el.textContent || el.value || ""),
          disabled: !!el.disabled || el.getAttribute("aria-disabled") === "true",
        }))
        .filter(x => x.text)
        .slice(0, 80);

      const fileInputs = Array.from(document.querySelectorAll("input[type='file']"))
        .map((el, index) => ({
          index: index + 1,
          label: labelForInput(el),
          name: el.getAttribute("name") || "",
          id: el.getAttribute("id") || "",
          visible: visible(el),
        }))
        .slice(0, 40);

      const errors = Array.from(document.querySelectorAll("[role='alert'], .error, .field-error, [class*='error'], [data-testid*='error']"))
        .filter(visible)
        .map(el => shortText(el, 500))
        .filter(Boolean)
        .slice(0, 40);

      const sectionTexts = [];
      const keywords = ["attach your resume", "attach your transcript", "attach your cover letter", "cover letter", "cover-letter", "other required documents", "transcript", "resume", "required", "valid response", "upload new", "search your"];
      for (const el of Array.from(document.querySelectorAll("section, fieldset, div, dialog, [role='dialog']"))) {
        if (!visible(el)) continue;
        const text = shortText(el, 1000);
        const lower = text.toLowerCase();
        if (!text) continue;
        if (keywords.some(k => lower.includes(k))) {
          if (!sectionTexts.includes(text)) sectionTexts.push(text);
        }
        if (sectionTexts.length >= 35) break;
      }

      return {
        url: window.location.href,
        title: document.title,
        body_text: norm(document.body ? document.body.innerText : "").slice(0, 22000),
        buttons,
        file_inputs: fileInputs,
        errors,
        relevant_sections: sectionTexts,
      };
    }
    """

    try:
        snapshot = page.evaluate(js)
        if not isinstance(snapshot, dict):
            snapshot = {}
    except Exception as exc:
        snapshot = {"snapshot_error": repr(exc)}

    snapshot["context"] = context
    snapshot["available_documents"] = _available_documents()
    return snapshot


def _local_recovery_actions(snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
    body_norm = _norm(snapshot.get("body_text", ""))
    actions: List[Dict[str, Any]] = []

    transcript_path = _document_path("transcript")
    resume_path = _document_path("resume")
    cover_letter_path = _document_path("cover_letter")

    if (
        cover_letter_path
        and ("cover letter" in body_norm or "cover-letter" in body_norm or "letter of interest" in body_norm or "motivation letter" in body_norm)
        and cover_letter_path.name.lower() not in str(snapshot.get("body_text", "")).lower()
    ):
        actions.append(
            {
                "type": "upload_document",
                "file_key": "cover_letter",
                "section_label": "Attach your cover letter",
                "confidence": 0.99,
                "reason": "Local recovery: page asks for a cover letter and PROFILE has one configured.",
            }
        )

    if (
        transcript_path
        and ("attach your transcript" in body_norm or "search your transcripts" in body_norm or "upload transcript" in body_norm)
        and transcript_path.name.lower() not in str(snapshot.get("body_text", "")).lower()
    ):
        actions.append(
            {
                "type": "upload_document",
                "file_key": "transcript",
                "section_label": "Attach your transcript",
                "confidence": 0.99,
                "reason": "Local recovery: page asks for a transcript and PROFILE has one configured.",
            }
        )

    if (
        resume_path
        and ("attach your resume" in body_norm or "search your resumes" in body_norm or "upload resume" in body_norm)
        and resume_path.name.lower() not in str(snapshot.get("body_text", "")).lower()
    ):
        actions.append(
            {
                "type": "upload_document",
                "file_key": "resume",
                "section_label": "Attach your resume",
                "confidence": 0.98,
                "reason": "Local recovery: page asks for a resume and PROFILE has one configured.",
            }
        )

    if "other required documents" in body_norm or "short answer responses" in body_norm or "questionnaire" in body_norm:
        if _truthy(os.getenv("AI_GENERATE_OTHER_DOCUMENTS"), False) or _truthy(os.getenv("AI_FILL_QUESTIONNAIRES"), False):
            actions.append(
                {
                    "type": "generate_questionnaire_document",
                    "file_key": "generated_questionnaire",
                    "section_label": "Attach other required documents",
                    "company": snapshot.get("company") or "",
                    "title": snapshot.get("job_title") or "",
                    "confidence": 0.86,
                    "reason": "Page asks for a questionnaire / other required document, and AI questionnaire generation is enabled. Generate a review-only PDF and attach it, then stop before submit.",
                }
            )
        actions.append(
            {
                "type": "manual_review",
                "confidence": 0.95,
                "reason": "Page asks for other required documents / questionnaire responses. Review any generated attachment and the application before submitting.",
            }
        )

    return actions


def _build_recovery_prompt(snapshot: Dict[str, Any]) -> str:
    safe_profile = {
        "name": f"{PROFILE.get('first_name', '')} {PROFILE.get('last_name', '')}".strip(),
        "email": PROFILE.get("email"),
        "phone": PROFILE.get("phone"),
        "school": PROFILE.get("school"),
        "degree": PROFILE.get("degree"),
        "major": PROFILE.get("major"),
        "expected_graduation": PROFILE.get("expected_graduation"),
        "authorized_us": PROFILE.get("authorized_us"),
        "sponsorship": PROFILE.get("sponsorship") or PROFILE.get("requires_sponsorship"),
        "outside_business_activity": PROFILE.get("outside_business_activity"),
        "outside_business_explanation": PROFILE.get("outside_business_explanation"),
        "available_documents": snapshot.get("available_documents"),
    }

    snapshot_json = json.dumps(snapshot, ensure_ascii=False)[:90000]
    profile_json = json.dumps(safe_profile, ensure_ascii=False, indent=2)

    return f"""
You are a recovery planner for a job-application autofill bot.
The bot hit a problem such as a disabled submit button, missing required field, validation error, or required document section.

Return JSON only with this shape:
{{
  "summary": "brief diagnosis",
  "actions": [
    {{
      "type": "upload_document | fill_text | generate_questionnaire_document | manual_review",
      "file_key": "resume | transcript | cover_letter | null",
      "section_label": "visible page section label or null",
      "label_contains": "visible field label text or null",
      "value": "text value for fill_text or null",
      "confidence": 0.0,
      "reason": "brief reason"
    }}
  ],
  "manual_review": ["anything unsafe/unknown"]
}}

Allowed actions:
- upload_document only for file_key resume, transcript, cover_letter, or generated_questionnaire when the page clearly asks for that document and it exists in available_documents.
- generate_questionnaire_document only when the page asks for a questionnaire, short-answer response document, or other required document AND AI_GENERATE_OTHER_DOCUMENTS or AI_FILL_QUESTIONNAIRES is enabled. This must be review-only and must not submit the application.
- fill_text only when the value is explicitly known in the profile, e.g. a conditional N/A explanation for outside business activity.
- manual_review for anything else.

Safety rules:
- Do not invent portfolios or unsupported credentials.
- Do not generate new cover letters; only upload the configured cover_letter PDF when the page clearly asks for a cover letter.
- If questionnaire generation is enabled, you may generate a questionnaire/short-answer document using only the applicant profile, applicant brief, and visible job text; the bot must still stop before final submit.
- Do not submit the application.
- Do not bypass CAPTCHA or human verification.
- Do not provide legal consent, attestation, certification, or signature actions.
- Do not fill disability, race, sexual orientation, transgender identity, or other sensitive demographic fields.
- If the page asks for "other required documents" or short-answer responses and no matching file is configured, manual_review.

Known safe profile/document data:
{profile_json}

DOM snapshot:
{snapshot_json}
""".strip()


def _openai_recovery_actions(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    if not recovery_agent_enabled():
        return {"summary": "Recovery agent disabled.", "actions": [], "manual_review": []}

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return {"summary": "OPENAI_API_KEY missing; local recovery only.", "actions": [], "manual_review": []}

    model = os.getenv("RECOVERY_AGENT_MODEL", os.getenv("APPLICATION_AGENT_MODEL", "gpt-5-mini")).strip() or "gpt-5-mini"

    try:
        from openai import OpenAI

        client = OpenAI()
        response = client.responses.create(
            model=model,
            input=_build_recovery_prompt(snapshot),
        )
        result = _extract_json_object(response.output_text)
        if not isinstance(result.get("actions"), list):
            result["actions"] = []
        if not isinstance(result.get("manual_review"), list):
            result["manual_review"] = []
        return result
    except Exception as exc:
        return {
            "summary": f"Recovery-agent API failed; local recovery only. Error: {exc}",
            "actions": [],
            "manual_review": [],
        }


def _dedupe_actions(actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    seen = set()
    for action in actions:
        if not isinstance(action, dict):
            continue
        key = (
            str(action.get("type") or ""),
            str(action.get("file_key") or ""),
            _norm(action.get("section_label") or ""),
            _norm(action.get("label_contains") or ""),
            _norm(action.get("value") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(action)
    return deduped[:MAX_AGENT_ACTIONS]


def _tag_matching_file_inputs(page, file_key: str, section_label: str = "") -> int:
    terms = []
    if file_key == "transcript":
        terms = ["transcript", "academic record", "unofficial transcript", "official transcript"]
    elif file_key == "resume":
        terms = ["resume", "cv", "curriculum vitae"]
    elif file_key == "cover_letter":
        terms = ["cover letter", "cover-letter", "letter of interest", "motivation letter"]
    elif file_key == "generated_questionnaire":
        terms = [
            "other required documents",
            "attach other required documents",
            "questionnaire",
            "short answer",
            "other document",
            "search your other documents",
        ]

    if section_label:
        terms.append(section_label)

    js = r"""
    ({ terms, tag }) => {
      function norm(s) {
        return (s || "").replace(/\s+/g, " ").trim().toLowerCase();
      }
      function textNear(input) {
        const parts = [];
        const id = input.getAttribute("id");
        if (id) {
          for (const lab of Array.from(document.querySelectorAll("label"))) {
            if (lab.getAttribute("for") === id) parts.push(lab.innerText || lab.textContent || "");
          }
        }
        const wrap = input.closest("label");
        if (wrap) parts.push(wrap.innerText || wrap.textContent || "");
        const section = input.closest("section, fieldset, div");
        if (section) parts.push(section.innerText || section.textContent || "");
        return norm(parts.join(" "));
      }
      const wanted = terms.map(norm).filter(Boolean);
      let count = 0;
      for (const input of Array.from(document.querySelectorAll('input[type="file"]'))) {
        const text = textNear(input);
        if (wanted.some(t => text.includes(t))) {
          input.setAttribute(tag, "true");
          count += 1;
        }
      }
      return count;
    }
    """
    try:
        return int(page.evaluate(js, {"terms": terms, "tag": f"data-recovery-upload-{file_key}"}) or 0)
    except Exception:
        return 0


def _click_upload_new_near_section(page, section_label: str, file_key: str) -> bool:
    labels = [section_label]
    if file_key == "transcript":
        labels.extend(["Attach your transcript", "Search your transcripts", "transcript"])
    elif file_key == "resume":
        labels.extend(["Attach your resume", "Search your resumes", "resume"])
    elif file_key == "cover_letter":
        labels.extend(["Attach your cover letter", "Cover letter", "cover-letter", "letter of interest", "motivation letter"])
    elif file_key == "generated_questionnaire":
        labels.extend([
            "Attach other required documents",
            "Other required documents",
            "Questionnaire",
            "Short answer",
            "Other Document",
            "Search your other documents",
        ])

    js = r"""
    ({ labels }) => {
      function norm(s) {
        return (s || "").replace(/\s+/g, " ").trim().toLowerCase();
      }
      function visible(el) {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
      }

      const wanted = labels.map(norm).filter(Boolean);
      const all = Array.from(document.querySelectorAll("body *")).filter(visible);
      let labelEl = null;

      for (const exact of [true, false]) {
        for (const el of all) {
          const text = norm(el.innerText || el.textContent || "");
          if (!text || text.length > 600) continue;
          if (wanted.some(w => exact ? text === w : text.includes(w))) {
            labelEl = el;
            break;
          }
        }
        if (labelEl) break;
      }

      const buttons = all
        .filter(el => {
          const text = norm(el.innerText || el.textContent || el.value || "");
          return text === "upload new" || text === "upload" || text.includes("upload new");
        })
        .map(el => ({ el, rect: el.getBoundingClientRect() }));

      if (!buttons.length) {
        return { ok: false, reason: "no upload buttons found" };
      }

      let chosen = null;
      if (labelEl) {
        const lr = labelEl.getBoundingClientRect();
        const nearby = buttons
          .filter(item => item.rect.top >= lr.top - 20 && item.rect.top <= lr.top + 420)
          .sort((a, b) => {
            if (Math.abs(a.rect.top - b.rect.top) > 10) return a.rect.top - b.rect.top;
            return a.rect.left - b.rect.left;
          });
        if (nearby.length) chosen = nearby[0].el;
      }

      // Fallback: resume usually appears first, transcript usually appears after resume.
      if (!chosen) {
        chosen = buttons[buttons.length - 1].el;
      }

      chosen.scrollIntoView({ block: "center" });
      chosen.click();
      return { ok: true };
    }
    """
    try:
        result = page.evaluate(js, {"labels": labels})
        return bool(isinstance(result, dict) and result.get("ok"))
    except Exception as exc:
        print(f"  ⚠ Could not click Upload new near {section_label!r}: {exc}")
        return False


def _document_attached(page, file_key: str, path: Path) -> bool:
    try:
        body = page.locator("body").inner_text(timeout=3000).lower()
    except Exception:
        return False

    names = [path.name.lower()]
    if file_key == "resume":
        names.extend(["guzmansample_resume.pdf", "resume.pdf"])
    elif file_key == "transcript":
        names.extend(["transcriptunofficial.pdf", "guzmansample_transcript.pdf", "transcript.pdf"])
    elif file_key == "cover_letter":
        names.extend(["cover letter.pdf", "cover_letter.pdf", "guzmansample_cover_letter.pdf", "coverletter.pdf"])
    elif file_key == "generated_questionnaire":
        # Do not use generic words like "questionnaire" here; those often appear
        # in the employer instructions before any file has been attached.
        try:
            names.append(path.stem.lower())
        except Exception:
            pass

    return any(name in body for name in names)


def _confirm_possible_upload_dialog(page, file_key: str, path: Path) -> None:
    for label in ["Upload", "Attach", "Save", "Add document", "Done", "Confirm"]:
        try:
            button = page.get_by_role("button", name=label).last
            if button.count() > 0 and button.is_visible():
                button.click(timeout=2500)
                page.wait_for_timeout(2000)
                if _document_attached(page, file_key, path):
                    return
        except Exception:
            continue


def _execute_upload_document(page, action: Dict[str, Any]) -> bool:
    file_key = str(action.get("file_key") or "").strip().lower()
    if file_key not in SAFE_FILE_KEYS:
        print(f"  ⚠ Refusing unsafe upload file_key: {file_key!r}")
        return False

    path = _document_path(file_key)
    if not path:
        print(f"  ⚠ No configured file found for {file_key}.")
        return False

    if _document_attached(page, file_key, path):
        print(f"  ✓ {file_key.capitalize()} already attached: {path.name}")
        return True

    section_label = _clean(action.get("section_label") or "")
    if not section_label:
        if file_key == "transcript":
            section_label = "Attach your transcript"
        elif file_key == "cover_letter":
            section_label = "Attach your cover letter"
        elif file_key == "generated_questionnaire":
            section_label = "Attach other required documents"
        else:
            section_label = "Attach your resume"

    print(f"  Recovery action: upload {file_key} → {path.name}")
    print(f"    Section: {section_label}")

    # Method 1: direct input[type=file] with nearby label.
    try:
        tagged = _tag_matching_file_inputs(page, file_key, section_label)
        if tagged:
            locator = page.locator(f'input[type="file"][data-recovery-upload-{file_key}="true"]').last
            locator.set_input_files(str(path))
            page.wait_for_timeout(3000)
            _confirm_possible_upload_dialog(page, file_key, path)
            if _document_attached(page, file_key, path):
                print(f"  ✓ Uploaded {file_key}: {path.name}")
                return True
            print(f"  ⚠ Set file input for {file_key}, but filename was not confirmed.")
            return True
    except Exception as exc:
        print(f"  ⚠ Direct file-input upload failed for {file_key}: {exc}")

    # Method 2: click Upload new and handle native file chooser.
    try:
        with page.expect_file_chooser(timeout=8000) as chooser_info:
            clicked = _click_upload_new_near_section(page, section_label, file_key)
            if not clicked:
                raise RuntimeError("Upload button was not clicked")
        chooser = chooser_info.value
        chooser.set_files(str(path))
        page.wait_for_timeout(4000)
        _confirm_possible_upload_dialog(page, file_key, path)
        if _document_attached(page, file_key, path):
            print(f"  ✓ Uploaded {file_key}: {path.name}")
            return True
        print(f"  ⚠ File chooser accepted {file_key}, but filename was not confirmed.")
        return True
    except Exception as exc:
        print(f"  ⚠ File chooser upload failed for {file_key}: {exc}")

    # Method 3: click upload then set newest file input.
    try:
        _click_upload_new_near_section(page, section_label, file_key)
        page.wait_for_timeout(1500)
        inputs = page.locator('input[type="file"]')
        count = inputs.count()
        for i in reversed(range(count)):
            try:
                inputs.nth(i).set_input_files(str(path), timeout=5000)
                page.wait_for_timeout(4000)
                _confirm_possible_upload_dialog(page, file_key, path)
                if _document_attached(page, file_key, path):
                    print(f"  ✓ Uploaded {file_key} via fallback input: {path.name}")
                    return True
            except Exception:
                continue
    except Exception as exc:
        print(f"  ⚠ Fallback upload failed for {file_key}: {exc}")

    print(f"  ✗ Could not upload {file_key} automatically.")
    return False


def _execute_fill_text(page, action: Dict[str, Any]) -> bool:
    label_contains = _clean(action.get("label_contains") or "")
    value = _clean(action.get("value") or "")
    if not label_contains or not value:
        return False

    # Only allow safe profile/N/A text. Do not let the model invent essays.
    allowed_values = {
        _clean(PROFILE.get("outside_business_explanation")),
        "N/A - I do not currently own, operate, or provide services to any other business or organization.",
    }
    if value not in allowed_values:
        print(f"  ⚠ Refusing unsafe fill_text value: {value[:80]!r}")
        return False

    js = r"""
    ({ labelContains, value }) => {
      function norm(s) { return (s || "").replace(/\s+/g, " ").trim().toLowerCase(); }
      function visible(el) {
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
      }
      function labelFor(el) {
        const parts = [];
        const id = el.getAttribute("id");
        if (id) {
          for (const lab of Array.from(document.querySelectorAll("label"))) {
            if (lab.getAttribute("for") === id) parts.push(lab.innerText || lab.textContent || "");
          }
        }
        const wrap = el.closest("label");
        if (wrap) parts.push(wrap.innerText || wrap.textContent || "");
        const section = el.closest("section, fieldset, div");
        if (section) parts.push(section.innerText || section.textContent || "");
        return norm(parts.join(" "));
      }
      function setValue(el, val) {
        const setter = Object.getOwnPropertyDescriptor(el.constructor.prototype, "value")?.set;
        if (setter) setter.call(el, val); else el.value = val;
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
        el.dispatchEvent(new Event("blur", { bubbles: true }));
      }
      const wanted = norm(labelContains);
      for (const el of Array.from(document.querySelectorAll("textarea, input[type='text']"))) {
        if (!visible(el)) continue;
        if (norm(el.value || "")) continue;
        if (labelFor(el).includes(wanted)) {
          setValue(el, value);
          return true;
        }
      }
      return false;
    }
    """
    try:
        ok = bool(page.evaluate(js, {"labelContains": label_contains, "value": value}))
        if ok:
            print(f"  ✓ Filled safe text recovery: {label_contains} → {value}")
        return ok
    except Exception as exc:
        print(f"  ⚠ Could not execute fill_text recovery: {exc}")
        return False




def _execute_generate_questionnaire_document(page, action: Dict[str, Any]) -> bool:
    if not (_truthy(os.getenv("AI_GENERATE_OTHER_DOCUMENTS"), False) or _truthy(os.getenv("AI_FILL_QUESTIONNAIRES"), False)):
        print("  ⚠ Questionnaire generation action ignored because AI_GENERATE_OTHER_DOCUMENTS/AI_FILL_QUESTIONNAIRES is disabled.")
        return False

    company = _clean(action.get("company") or "")
    title = _clean(action.get("title") or "")
    section_label = _clean(action.get("section_label") or "Attach other required documents")

    try:
        from src.questionnaire_document_agent import generate_questionnaire_document

        path = generate_questionnaire_document(page=page, company=company, title=title)
    except Exception as exc:
        print(f"  ⚠ Could not generate questionnaire document: {exc}")
        return False

    if not path:
        print("  ⚠ No questionnaire document was generated.")
        return False

    # Reuse the normal upload machinery, now pointed at the latest generated questionnaire.
    return _execute_upload_document(
        page,
        {
            "type": "upload_document",
            "file_key": "generated_questionnaire",
            "section_label": section_label,
            "reason": "Attach the generated review-only questionnaire document.",
        },
    )

def _execute_action(page, action: Dict[str, Any]) -> bool:
    action_type = str(action.get("type") or "").strip().lower()
    reason = _clean(action.get("reason") or "")
    confidence = action.get("confidence", "")

    if reason:
        print(f"  Plan: {action_type} (confidence={confidence}) — {reason}")

    if action_type == "upload_document":
        return _execute_upload_document(page, action)
    if action_type == "fill_text":
        return _execute_fill_text(page, action)
    if action_type == "generate_questionnaire_document":
        return _execute_generate_questionnaire_document(page, action)
    if action_type == "manual_review":
        print(f"  Manual review needed: {reason or action}")
        return False

    print(f"  ⚠ Unknown recovery action ignored: {action_type!r}")
    return False


def run_recovery_agent(
    page,
    *,
    context: str = "",
    company: str = "",
    title: str = "",
    max_rounds: int = 2,
) -> Dict[str, Any]:
    print("\n===== RECOVERY AGENT =====")
    print(f"Context: {context or 'unknown'}")

    total_applied = 0
    manual_notes: List[str] = []
    last_summary = ""

    for round_index in range(1, max_rounds + 1):
        snapshot = collect_recovery_snapshot(page, context=context)
        snapshot["company"] = company
        snapshot["job_title"] = title

        local_actions = _local_recovery_actions(snapshot)
        ai_result = _openai_recovery_actions(snapshot)
        ai_actions = ai_result.get("actions") if isinstance(ai_result, dict) else []
        if not isinstance(ai_actions, list):
            ai_actions = []

        last_summary = str(ai_result.get("summary") or "") if isinstance(ai_result, dict) else ""
        if last_summary:
            print(f"AI diagnosis: {last_summary}")

        manual = ai_result.get("manual_review") if isinstance(ai_result, dict) else []
        if isinstance(manual, list):
            manual_notes.extend(str(item) for item in manual if item)

        actions = _dedupe_actions(local_actions + ai_actions)
        if not actions:
            print("No safe recovery actions found.")
            break

        applied_this_round = 0
        for action in actions:
            if _execute_action(page, action):
                applied_this_round += 1
                total_applied += 1
                try:
                    page.wait_for_timeout(1000)
                except Exception:
                    pass

        if applied_this_round == 0:
            print("No recovery action succeeded this round.")
            break

    if manual_notes:
        print("\nRecovery manual-review notes:")
        for note in manual_notes[:12]:
            print(f" - {note}")

    print(f"Recovery summary: applied={total_applied}")
    return {
        "applied": total_applied,
        "summary": last_summary,
        "manual_review": manual_notes,
    }
