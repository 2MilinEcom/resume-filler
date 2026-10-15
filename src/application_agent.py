from __future__ import annotations

import json
import os
import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass


from src.profile import PROFILE

# Always derive facts from the current user-controlled profile, never a second
# stale hardcoded identity/graduation record.
KNOWN_PROFILE = {
    "first_name": PROFILE.get("first_name", ""),
    "last_name": PROFILE.get("last_name", ""),
    "preferred_first_name": PROFILE.get("preferred_first_name", ""),
    "email": PROFILE.get("email", ""),
    "phone": PROFILE.get("phone", ""),
    "location": ", ".join(str(PROFILE.get(k, "")) for k in ("city", "state_full", "country") if PROFILE.get(k)),
    "city": PROFILE.get("city", ""),
    "state": PROFILE.get("state_full", PROFILE.get("state", "")),
    "country": PROFILE.get("country", ""),
    "country_full": PROFILE.get("country_full", ""),
    "zip_code": PROFILE.get("zip_code", ""),
    "school": PROFILE.get("school", ""),
    "school_greenhouse": PROFILE.get("school", ""),
    "degree": PROFILE.get("degree", ""),
    "major": PROFILE.get("major", ""),
    "expected_graduation": PROFILE.get("expected_graduation", ""),
    "graduation_month": PROFILE.get("graduation_month", ""),
    "graduation_year": PROFILE.get("graduation_year", ""),
    "linkedin": PROFILE.get("linkedin", ""),
    "authorized_us": PROFILE.get("authorized_us", ""),
    "requires_sponsorship": PROFILE.get("requires_sponsorship", ""),
    "onsite_willing": "No",  # Remote-only applications: never claim willingness to attend onsite.
    "san_jose_office_willing": "No",
    "available_january_may": PROFILE.get("available_january_may", ""),
    "previously_worked_for_company": PROFILE.get("previously_worked_for_company", ""),
    "outside_business_activity": PROFILE.get("outside_business_activity", ""),
    "talent_community": PROFILE.get("talent_community", ""),
}



SAFE_AUTOFILL_CATEGORIES = {
    "name",
    "email",
    "phone",
    "location",
    "school",
    "degree",
    "major",
    "graduation",
    "work_authorization",
    "sponsorship",
    "linkedin",
    "zip_code",
    "onsite",
    "onsite_willingness",
    "availability",
    "previous_employment",
    "outside_business",
    "talent_community",
}


NEVER_AUTOFILL_CATEGORIES = {
    "salary",
    "demographic",
    "veteran",
    "consent",
    "attestation",
    "signature",
    "certification",
    "file_upload",
    "captcha",
    "disability",
    "race",
    "sexual_orientation",
    "transgender",
}


NEVER_AUTOFILL_LABEL_TERMS = [
    "submit application",
    "submit",
    "desired salary",
    "salary",
    "compensation",
    "disability",
    "chronic condition",
    "sexual orientation",
    "transgender",
    "racial",
    "race",
    "ethnic background",
    "ethnicity",
    "veteran status",
    "protected veteran",
    "certify",
    "certification",
    "signature",
    "terms",
    "privacy policy",
    "data processing",
    "store and process my data",
    "i agree to allow",
    "by checking this box",
    "captcha",
    "human verification",
]


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def agent_enabled() -> bool:
    return _truthy(os.getenv("APPLICATION_AGENT_ENABLED", "true"))


def agent_apply_enabled() -> bool:
    return _truthy(os.getenv("APPLICATION_AGENT_APPLY_SUGGESTIONS", "true"))


def _normalize(value: Any) -> str:
    text = str(value or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _pretty(value: Any) -> str:
    return str(value or "").strip()


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _extract_json_object(text: str) -> Dict[str, Any]:
    text = text.strip()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return {
            "page_type": "unknown",
            "summary": text[:1000],
            "fields": [],
            "risks": [],
        }

    try:
        parsed = json.loads(match.group(0))
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    return {
        "page_type": "unknown",
        "summary": text[:1000],
        "fields": [],
        "risks": [],
    }


def collect_application_snapshot(page) -> Dict[str, Any]:
    js = r"""
    () => {
      const norm = (s) => (s || "").replace(/\s+/g, " ").trim();

      function isVisible(el) {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        if (!style || style.display === "none" || style.visibility === "hidden") return false;
        if (el.type && String(el.type).toLowerCase() === "hidden") return false;
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 && rect.height === 0) return false;
        return true;
      }

      function labelFor(el) {
        const parts = [];

        const aria = el.getAttribute("aria-label");
        if (aria) parts.push(aria);

        const placeholder = el.getAttribute("placeholder");
        if (placeholder) parts.push(placeholder);

        const name = el.getAttribute("name");
        const id = el.getAttribute("id");

        if (id) {
          for (const lab of Array.from(document.querySelectorAll("label"))) {
            if (lab.getAttribute("for") === id) {
              parts.push(lab.innerText || lab.textContent || "");
            }
          }
        }

        const wrappingLabel = el.closest("label");
        if (wrappingLabel) {
          parts.push(wrappingLabel.innerText || wrappingLabel.textContent || "");
        }

        const ariaLabelledBy = el.getAttribute("aria-labelledby");
        if (ariaLabelledBy) {
          for (const refId of ariaLabelledBy.split(/\s+/)) {
            const ref = document.getElementById(refId);
            if (ref) parts.push(ref.innerText || ref.textContent || "");
          }
        }

        const containerSelectors = [
          "[data-testid]",
          "fieldset",
          ".field",
          ".form-field",
          ".application-question",
          ".question",
          ".select__container",
          ".field-error-wrapper",
          "div"
        ];

        for (const selector of containerSelectors) {
          const container = el.closest(selector);
          if (container) {
            const text = norm(container.innerText || container.textContent || "");
            if (text && text.length < 850) {
              parts.push(text);
              break;
            }
          }
        }

        if (name) parts.push(name);
        if (id) parts.push(id);

        for (const p of parts) {
          const cleaned = norm(p);
          if (cleaned) return cleaned.slice(0, 450);
        }

        return norm(el.tagName || "field");
      }

      function optionLabelFor(el) {
        const parts = [];
        const id = el.getAttribute("id");

        if (id) {
          for (const lab of Array.from(document.querySelectorAll("label"))) {
            if (lab.getAttribute("for") === id) {
              parts.push(lab.innerText || lab.textContent || "");
            }
          }
        }

        const wrap = el.closest("label");
        if (wrap) parts.push(wrap.innerText || wrap.textContent || "");

        const parent = el.parentElement;
        if (parent) parts.push(parent.innerText || parent.textContent || "");

        for (const p of parts) {
          const cleaned = norm(p);
          if (cleaned) return cleaned.slice(0, 250);
        }

        return norm(el.value || "");
      }

      const controls = [];
      const seenRadioGroups = new Set();
      const seenCheckboxGroups = new Set();

      function pushControl(elements, data) {
        const index = controls.length + 1;
        const els = Array.isArray(elements) ? elements : [elements];

        for (const el of els) {
          try {
            el.setAttribute("data-agent-control-index", String(index));
          } catch (e) {}
        }

        controls.push({
          index,
          ...data,
        });
      }

      for (const el of Array.from(document.querySelectorAll("input, textarea, select"))) {
        if (!isVisible(el)) continue;

        const tag = el.tagName.toLowerCase();
        const type = (el.getAttribute("type") || tag).toLowerCase();
        const name = el.getAttribute("name") || "";
        const id = el.getAttribute("id") || "";
        const role = el.getAttribute("role") || "";

        if (type === "submit" || type === "button" || type === "file" || type === "hidden") {
          continue;
        }

        if (type === "radio" && name) {
          const groupKey = `radio:${name}`;
          if (seenRadioGroups.has(groupKey)) continue;
          seenRadioGroups.add(groupKey);

          const group = Array.from(document.querySelectorAll('input[type="radio"]'))
            .filter(x => (x.getAttribute("name") || "") === name)
            .filter(x => isVisible(x));

          pushControl(group, {
            tag,
            type,
            role,
            name,
            id,
            required: group.some(x => x.required || x.getAttribute("aria-required") === "true"),
            label: labelFor(el),
            value: group.find(x => x.checked)?.value || "",
            options: group.map(x => optionLabelFor(x)).filter(Boolean),
          });
          continue;
        }

        if (type === "checkbox" && name) {
          const groupKey = `checkbox:${name}`;
          if (seenCheckboxGroups.has(groupKey)) continue;
          seenCheckboxGroups.add(groupKey);

          const group = Array.from(document.querySelectorAll('input[type="checkbox"]'))
            .filter(x => (x.getAttribute("name") || "") === name)
            .filter(x => isVisible(x));

          pushControl(group, {
            tag,
            type,
            role,
            name,
            id,
            required: group.some(x => x.required || x.getAttribute("aria-required") === "true"),
            label: labelFor(el),
            value: group.filter(x => x.checked).map(x => x.value).join(", "),
            options: group.map(x => optionLabelFor(x)).filter(Boolean),
          });
          continue;
        }

        let options = [];
        if (tag === "select") {
          options = Array.from(el.options || [])
            .map(o => norm(o.textContent || o.value))
            .filter(Boolean);
        }

        pushControl(el, {
          tag,
          type,
          role,
          name,
          id,
          required: !!el.required || el.getAttribute("aria-required") === "true",
          label: labelFor(el),
          placeholder: el.getAttribute("placeholder") || "",
          value: el.value || "",
          options,
        });
      }

      const buttons = Array.from(document.querySelectorAll("button, input[type='submit']"))
        .filter(isVisible)
        .map((b, i) => ({
          index: i + 1,
          text: norm(b.innerText || b.textContent || b.value || ""),
          type: b.getAttribute("type") || "",
          disabled: !!b.disabled,
        }))
        .filter(b => b.text);

      return {
        url: window.location.href,
        title: document.title,
        body_text: norm(document.body ? document.body.innerText : "").slice(0, 16000),
        controls,
        buttons,
      };
    }
    """

    try:
        snapshot = page.evaluate(js)
        if not isinstance(snapshot, dict):
            return {
                "url": getattr(page, "url", ""),
                "title": "",
                "body_text": "",
                "controls": [],
                "buttons": [],
                "snapshot_error": "page.evaluate returned non-dict snapshot",
            }
        return snapshot
    except Exception as exc:
        return {
            "url": getattr(page, "url", ""),
            "title": "",
            "body_text": "",
            "controls": [],
            "buttons": [],
            "snapshot_error": repr(exc),
        }


def build_agent_prompt(snapshot: Dict[str, Any]) -> str:
    profile_json = json.dumps(KNOWN_PROFILE, ensure_ascii=False, indent=2)
    snapshot_json = json.dumps(snapshot, ensure_ascii=False)[:75000]

    return f"""
You are analyzing a job application page for autofill assistance.

Return JSON only with this exact shape:
{{
  "page_type": "greenhouse_application | ats_application | unknown",
  "summary": "one sentence",
  "fields": [
    {{
      "label": "field/question label",
      "type": "text | dropdown | radio | checkbox | textarea | unknown",
      "required": true,
      "category": "name | email | phone | location | zip_code | school | degree | major | graduation | work_authorization | sponsorship | linkedin | onsite_willingness | previous_employment | outside_business | talent_community | salary | demographic | veteran | consent | file_upload | captcha | unknown",
      "recommended_answer": "answer or null",
      "confidence": 0.0,
      "action": "autofill | ask_user | skip | manual_review",
      "reason": "brief reason"
    }}
  ],
  "risks": ["anything that should not be auto-submitted or should stay manual"]
}}

Known applicant profile:
{profile_json}

Rules:
- Never recommend submitting the application.
- You may recommend autofill for factual profile fields when the answer is explicitly known above.
- First name, last name, preferred first name, email, phone, LinkedIn, school, degree, major, city, state, country, ZIP code, and location may be autofill when clearly matched.
- Onsite or office attendance is incompatible with remote-only applications. Never answer Yes to mandatory onsite attendance.
- Previous employment with the company may be autofill as "No" when the question asks whether the applicant has previously worked for that company, including Veeam.
- Outside business, freelance, consulting, board, or contractual activity may be autofill as "No" when the question asks whether the applicant currently owns, operates, or provides services to another business or organization.
- Talent community opt-in may be autofill as "Yes" when the question asks whether the applicant agrees to join Veeam's talent community for future opportunities.
- Work authorization may be recommended as autofill only when the question asks whether the applicant is legally authorized or eligible to work in the United States / country where the role is posted. Use "Yes".
- Sponsorship may be recommended as autofill only when the question asks whether the applicant now or in the future requires visa sponsorship or work authorization sponsorship. Use "No".
- Expected graduation must come from the KNOWN_PROFILE fields above; do not substitute a different date.
- Use graduation_month, graduation_year, and expected_graduation consistently from KNOWN_PROFILE.
- Demographic fields may be suggested only when explicitly known, but use manual_review unless the field is clearly optional and low-risk.
- Veteran status is known as not a veteran, but still use manual_review for voluntary self-ID forms unless the existing autofill already selected it.
- Disability, sexual orientation, transgender identity, race, consent, attestation, signature, certification, salary, transcript upload, other file uploads, and CAPTCHA fields should be manual_review.
- Data processing consent is NOT the same as talent community opt-in. Data processing consent must stay manual_review.
- If a dropdown has ambiguous options like "Select..." and no clear profile match, use ask_user or manual_review.
- Do not hallucinate options. Use the DOM snapshot only.
- The final submit button should always be listed as a risk if visible.

DOM snapshot:
{snapshot_json}
""".strip()


def analyze_application_page(page) -> Dict[str, Any]:
    snapshot = collect_application_snapshot(page)
    controls = snapshot.get("controls") or []

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("APPLICATION_AGENT_MODEL", "gpt-5-mini").strip() or "gpt-5-mini"

    if not api_key:
        result = {
            "page_type": "greenhouse_application",
            "summary": "OpenAI API key missing; showing local DOM snapshot only.",
            "fields": controls,
            "risks": ["OpenAI API key missing; no model analysis was run."],
        }
        result["_snapshot_controls"] = controls
        return result

    try:
        from openai import OpenAI

        client = OpenAI()
        prompt = build_agent_prompt(snapshot)

        response = client.responses.create(
            model=model,
            input=prompt,
        )

        result = _extract_json_object(response.output_text)

        if not isinstance(result.get("fields"), list):
            result["fields"] = []

        if not result.get("fields") and controls:
            result["fields"] = controls
            result["summary"] = (
                str(result.get("summary") or "")
                + " Model returned no fields, so local DOM controls are shown."
            ).strip()

        result["_snapshot_controls"] = controls
        return result

    except Exception as exc:
        result = {
            "page_type": "greenhouse_application",
            "summary": f"Agent API call failed; showing local DOM snapshot. Error: {exc}",
            "fields": controls,
            "risks": ["Agent API call failed; verify OPENAI_API_KEY and model name."],
        }
        result["_snapshot_controls"] = controls
        return result


def _option_match(answer: str, options: List[str]) -> str:
    if not options:
        return answer

    norm_answer = _normalize(answer)

    for opt in options:
        if _normalize(opt) == norm_answer:
            return opt

    for opt in options:
        norm_opt = _normalize(opt)
        if norm_answer and (norm_answer in norm_opt or norm_opt in norm_answer):
            return opt

    return answer


def _deterministic_profile_answer(label: str, category: str = "", options: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
    label_norm = _normalize(label)
    category_norm = _normalize(category)
    options = options or []

    if not label_norm:
        return None

    # Hard blocks first.
    if any(term in label_norm for term in [_normalize(t) for t in NEVER_AUTOFILL_LABEL_TERMS]):
        # Talent community has "agree", but is safe as a preference only when explicit.
        if "talent community" not in label_norm:
            return None

    if category_norm in NEVER_AUTOFILL_CATEGORIES:
        return None

    def pack(
        answer: str,
        category_value: str,
        confidence: float,
        reason: str,
    ) -> Dict[str, Any]:
        return {
            "answer": _option_match(answer, options),
            "category": category_value,
            "confidence": confidence,
            "reason": reason,
        }

    # Identity/contact.
    if "first name" in label_norm and "preferred" not in label_norm:
        return pack(KNOWN_PROFILE["first_name"], "name", 0.99, "Known profile first name.")
    if "last name" in label_norm:
        return pack(KNOWN_PROFILE["last_name"], "name", 0.99, "Known profile last name.")
    if "preferred first name" in label_norm or "preferred name" in label_norm:
        return pack(KNOWN_PROFILE["preferred_first_name"], "name", 0.97, "Known profile preferred first name.")
    if "email" in label_norm:
        return pack(KNOWN_PROFILE["email"], "email", 0.99, "Known profile email.")
    if "phone" in label_norm:
        return pack(KNOWN_PROFILE["phone"], "phone", 0.99, "Known profile phone number.")
    if "linkedin" in label_norm:
        return pack(KNOWN_PROFILE["linkedin"], "linkedin", 0.99, "Known profile LinkedIn URL.")

    # Education.
    if "school" in label_norm and "other" not in label_norm:
        return pack(KNOWN_PROFILE["school_greenhouse"], "school", 0.95, "Known UC Berkeley school name.")
    if "degree" in label_norm:
        return pack(KNOWN_PROFILE["degree"], "degree", 0.95, "Known degree.")
    if "major" in label_norm or "discipline" in label_norm or "field of study" in label_norm:
        return pack(KNOWN_PROFILE["major"], "major", 0.90, "Known major.")
    if "graduation month" in label_norm or "end date month" in label_norm:
        return pack(KNOWN_PROFILE["graduation_month"], "graduation", 0.95, "Known graduation month.")
    if "graduation year" in label_norm or "end date year" in label_norm:
        return pack(KNOWN_PROFILE["graduation_year"], "graduation", 0.95, "Known graduation year.")
    if "expected graduation" in label_norm or "graduation date" in label_norm:
        return pack(KNOWN_PROFILE["expected_graduation"], "graduation", 0.90, "Known expected graduation date.")

    # Location.
    if "zip" in label_norm or "postal code" in label_norm:
        return pack(KNOWN_PROFILE["zip_code"], "zip_code", 0.97, "Known ZIP code.")
    if "state" in label_norm and ("reside" in label_norm or "residence" in label_norm or "currently" in label_norm):
        return pack(KNOWN_PROFILE["state"], "location", 0.95, "Known state of residence.")
    if "country of residence" in label_norm:
        return pack(KNOWN_PROFILE["country_full"], "location", 0.95, "Known country of residence.")
    if label_norm == "country" or "country " in label_norm or " country" in label_norm:
        return pack(KNOWN_PROFILE["country_full"], "location", 0.90, "Known country.")
    if "location city" in label_norm or "city" in label_norm:
        return pack(KNOWN_PROFILE["location"], "location", 0.95, "Known location.")
    if "san jose" in label_norm and ("office" in label_norm or "work environment" in label_norm or "willing" in label_norm):
        return pack("No", "onsite_willingness", 0.99, "Only fully remote roles permitted.")
    if "office" in label_norm and "willing" in label_norm and "able" in label_norm:
        return pack("No", "onsite_willingness", 0.99, "Only fully remote roles permitted.")

    # Work authorization/sponsorship.
    if (
        "legally authorized" in label_norm
        or "authorized to work" in label_norm
        or "eligible to work" in label_norm
        or "eligibility to work" in label_norm
    ):
        return pack("Yes", "work_authorization", 0.95, "Known work authorization.")
    if "sponsorship" in label_norm or "h 1b" in label_norm or "visa status" in label_norm:
        return pack("No", "sponsorship", 0.95, "Known no sponsorship requirement.")

    # Company-specific factual yes/no.
    if "previously worked" in label_norm or "worked for veeam" in label_norm:
        return pack("No", "previous_employment", 0.95, "Known no previous employment with company.")
    if (
        "own operate" in label_norm
        or "provide services to any other business" in label_norm
        or "consultancy" in label_norm
        or "freelance" in label_norm
        or "board membership" in label_norm
        or "contractual engagement" in label_norm
        or "outside business" in label_norm
    ):
        return pack("No", "outside_business", 0.95, "Known no outside business activity.")
    if "talent community" in label_norm:
        return pack("Yes", "talent_community", 0.90, "Known preference to join talent community.")

    return None


def enrich_agent_result_with_profile_answers(result: Dict[str, Any]) -> Dict[str, Any]:
    fields = result.get("fields") or []

    for field in fields:
        if not isinstance(field, dict):
            continue

        label = _pretty(field.get("label") or field.get("name") or field.get("id"))
        category = _pretty(field.get("category", ""))
        options = field.get("options") if isinstance(field.get("options"), list) else []

        profile_answer = _deterministic_profile_answer(label, category, options)
        if not profile_answer:
            continue

        field["category"] = profile_answer["category"]
        field["action"] = "autofill"
        field["recommended_answer"] = profile_answer["answer"]
        field["confidence"] = max(_as_float(field.get("confidence"), 0.0), profile_answer["confidence"])

        old_reason = _pretty(field.get("reason"))
        new_reason = profile_answer["reason"]
        if old_reason:
            field["reason"] = f"{old_reason} Profile override: {new_reason}"
        else:
            field["reason"] = f"Profile override: {new_reason}"

    return result


def _label_similarity(a: str, b: str) -> float:
    a_norm = _normalize(a)
    b_norm = _normalize(b)

    if not a_norm or not b_norm:
        return 0.0

    if a_norm == b_norm:
        return 1.0

    if a_norm in b_norm or b_norm in a_norm:
        return 0.88

    return SequenceMatcher(None, a_norm, b_norm).ratio()


def _find_best_control_for_field(field: Dict[str, Any], controls: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    label = _pretty(field.get("label") or "")
    category = _normalize(field.get("category") or "")

    best: Tuple[float, Optional[Dict[str, Any]]] = (0.0, None)

    for control in controls:
        if not isinstance(control, dict):
            continue

        control_label = _pretty(control.get("label") or "")
        control_name = _pretty(control.get("name") or "")
        control_id = _pretty(control.get("id") or "")

        score = max(
            _label_similarity(label, control_label),
            _label_similarity(label, control_name),
            _label_similarity(label, control_id),
        )

        # Category-based nudges.
        c_label_norm = _normalize(control_label)
        if category == "work_authorization" and ("authorized" in c_label_norm or "eligible to work" in c_label_norm):
            score += 0.25
        if category == "sponsorship" and ("sponsorship" in c_label_norm or "visa" in c_label_norm):
            score += 0.25
        if category == "zip_code" and ("zip" in c_label_norm or "postal" in c_label_norm):
            score += 0.25
        if category == "onsite_willingness" and ("san jose" in c_label_norm or "office" in c_label_norm):
            score += 0.25
        if category == "previous_employment" and "previously worked" in c_label_norm:
            score += 0.25
        if category == "outside_business" and ("own operate" in c_label_norm or "other business" in c_label_norm):
            score += 0.25
        if category == "talent_community" and "talent community" in c_label_norm:
            score += 0.25

        if score > best[0]:
            best = (score, control)

    if best[0] >= 0.45:
        return best[1]

    return None


def _safe_to_apply(field: Dict[str, Any]) -> bool:
    label = _normalize(field.get("label") or "")
    category = _normalize(field.get("category") or "")
    action = _normalize(field.get("action") or "")
    answer = _pretty(field.get("recommended_answer"))

    if action != "autofill":
        return False

    if not answer:
        return False

    if category in NEVER_AUTOFILL_CATEGORIES:
        return False

    if category not in SAFE_AUTOFILL_CATEGORIES:
        return False

    if _as_float(field.get("confidence"), 0.0) < 0.80:
        return False

    for term in NEVER_AUTOFILL_LABEL_TERMS:
        term_norm = _normalize(term)
        if term_norm and term_norm in label:
            if "talent community" not in label:
                return False

    return True


def _apply_control_js(page, control_index: int, answer: str) -> Dict[str, Any]:
    js = r"""
    ({ index, answer }) => {
      const norm = (s) => (s || "").replace(/\s+/g, " ").trim().toLowerCase();

      function dispatch(el) {
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
        el.dispatchEvent(new Event("blur", { bubbles: true }));
      }

      function optionTextFor(el) {
        const parts = [];
        const id = el.getAttribute("id");

        if (id) {
          for (const lab of Array.from(document.querySelectorAll("label"))) {
            if (lab.getAttribute("for") === id) {
              parts.push(lab.innerText || lab.textContent || "");
            }
          }
        }

        const wrap = el.closest("label");
        if (wrap) parts.push(wrap.innerText || wrap.textContent || "");

        const parent = el.parentElement;
        if (parent) parts.push(parent.innerText || parent.textContent || "");

        parts.push(el.value || "");

        return parts.map(norm).filter(Boolean).join(" ");
      }

      const nodes = Array.from(document.querySelectorAll(`[data-agent-control-index="${index}"]`));
      if (!nodes.length) {
        return { ok: false, reason: "control not found" };
      }

      const first = nodes[0];
      const tag = first.tagName.toLowerCase();
      const type = (first.getAttribute("type") || tag).toLowerCase();
      const answerNorm = norm(answer);

      if (type === "radio" || type === "checkbox") {
        let best = null;

        for (const node of nodes) {
          const optText = optionTextFor(node);
          if (optText === answerNorm || optText.includes(answerNorm) || answerNorm.includes(optText)) {
            best = node;
            break;
          }
        }

        if (!best) {
          for (const node of nodes) {
            const optText = optionTextFor(node);
            if (answerNorm === "yes" && /\byes\b/.test(optText)) {
              best = node;
              break;
            }
            if (answerNorm === "no" && /\bno\b/.test(optText)) {
              best = node;
              break;
            }
          }
        }

        if (!best) {
          return { ok: false, reason: "matching radio/checkbox option not found" };
        }

        best.click();
        dispatch(best);
        return { ok: true, method: "radio_or_checkbox_click" };
      }

      if (tag === "select") {
        let selected = false;

        for (const option of Array.from(first.options || [])) {
          const text = norm(option.textContent || option.value || "");
          if (text === answerNorm || text.includes(answerNorm) || answerNorm.includes(text)) {
            first.value = option.value;
            selected = true;
            break;
          }
        }

        if (!selected) {
          return { ok: false, reason: "matching select option not found" };
        }

        dispatch(first);
        return { ok: true, method: "select_option" };
      }

      if (tag === "input" || tag === "textarea") {
        const setter = Object.getOwnPropertyDescriptor(first.constructor.prototype, "value")?.set;
        if (setter) {
          setter.call(first, answer);
        } else {
          first.value = answer;
        }
        dispatch(first);
        return { ok: true, method: "input_value_set" };
      }

      return { ok: false, reason: `unsupported tag/type ${tag}/${type}` };
    }
    """

    try:
        result = page.evaluate(js, {"index": control_index, "answer": answer})
        if isinstance(result, dict):
            return result
    except Exception as exc:
        return {"ok": False, "reason": repr(exc)}

    return {"ok": False, "reason": "unknown JS apply failure"}


def _apply_with_playwright_fallback(page, control: Dict[str, Any], answer: str) -> bool:
    index = control.get("index")
    if not index:
        return False

    selector = f'[data-agent-control-index="{index}"]'

    try:
        locator = page.locator(selector).first
        if locator.count() == 0:
            return False

        tag = _normalize(control.get("tag"))
        control_type = _normalize(control.get("type"))
        role = _normalize(control.get("role"))

        if tag == "select":
            try:
                locator.select_option(label=answer, timeout=1500)
                return True
            except Exception:
                pass

        if control_type in {"radio", "checkbox"}:
            # JS is usually better for radio/checkbox; fallback to label text.
            try:
                page.get_by_label(answer, exact=False).first.click(timeout=1500)
                return True
            except Exception:
                return False

        try:
            locator.fill(answer, timeout=1500)
            page.wait_for_timeout(250)
        except Exception:
            try:
                locator.click(timeout=1500)
                page.keyboard.press("Control+A")
                page.keyboard.type(answer)
                page.wait_for_timeout(250)
            except Exception:
                return False

        if role == "combobox" or "select" in _normalize(control.get("label")):
            try:
                page.get_by_text(answer, exact=True).last.click(timeout=1500)
                return True
            except Exception:
                try:
                    page.keyboard.press("Enter")
                    return True
                except Exception:
                    pass

        return True

    except Exception:
        return False


def apply_agent_suggestions(page, result: Dict[str, Any]) -> Dict[str, Any]:
    print("\n===== APPLYING AGENT AUTOFILL SUGGESTIONS =====")

    if not agent_apply_enabled():
        print("Agent autofill application disabled.")
        return {"applied": 0, "skipped": 0, "failed": 0}

    result = enrich_agent_result_with_profile_answers(result)

    fields = result.get("fields") or []
    controls = result.get("_snapshot_controls") or []

    applied = 0
    skipped = 0
    failed = 0

    for field in fields:
        if not isinstance(field, dict):
            skipped += 1
            continue

        label = _pretty(field.get("label") or field.get("name") or field.get("id") or "Unknown field")
        answer = _pretty(field.get("recommended_answer"))

        if not _safe_to_apply(field):
            skipped += 1
            continue

        control = _find_best_control_for_field(field, controls)

        if not control:
            print(f"  ⚠ No matching control found for: {label} → {answer}")
            failed += 1
            continue

        control_index = int(control.get("index"))
        js_result = _apply_control_js(page, control_index, answer)

        ok = bool(js_result.get("ok"))
        if not ok:
            ok = _apply_with_playwright_fallback(page, control, answer)

        if ok:
            print(f"  ✓ Applied: {label} → {answer}")
            applied += 1
        else:
            print(f"  ⚠ Could not apply: {label} → {answer} ({js_result.get('reason', 'unknown')})")
            failed += 1

        page.wait_for_timeout(150)

    print(f"\nAgent autofill summary: applied={applied}, skipped={skipped}, failed={failed}")
    return {"applied": applied, "skipped": skipped, "failed": failed}


def run_application_agent_analysis(page) -> Dict[str, Any] | None:
    print("\n===== APPLICATION AGENT ANALYSIS =====")

    if not agent_enabled():
        print("Application agent disabled.")
        return None

    result = analyze_application_page(page)
    result = enrich_agent_result_with_profile_answers(result)

    page_type = result.get("page_type", "unknown")
    summary = result.get("summary", "")
    fields = result.get("fields") or []
    risks = result.get("risks") or []

    print(f"Page type: {page_type}")
    if summary:
        print(f"Summary:   {summary}")

    print(f"Fields returned by agent: {len(fields)}")

    for i, field in enumerate(fields[:35], start=1):
        if isinstance(field, dict):
            label = field.get("label") or field.get("name") or field.get("id") or "Unknown field"
            field_type = field.get("type") or field.get("tag") or "unknown"
            required = field.get("required", "")
            category = field.get("category", "unknown")
            action = field.get("action", "unknown")
            answer = field.get("recommended_answer", field.get("value", None))
            confidence = field.get("confidence", "")
            reason = field.get("reason", "")

            print(f"\n{i}. {label}")
            print(f"   type:       {field_type}")
            if required != "":
                print(f"   required:   {required}")
            print(f"   category:   {category}")
            print(f"   action:     {action}")
            if answer not in (None, ""):
                print(f"   answer:     {answer}")
            if confidence != "":
                print(f"   confidence: {confidence}")
            if reason:
                print(f"   reason:     {reason}")
        else:
            print(f"\n{i}. {field}")

    if risks:
        print("\nRisks / manual review:")
        for risk in risks[:15]:
            print(f" - {risk}")

    apply_agent_suggestions(page, result)

    return result


# HOTFIX_MINIMAL_2026_10_01
# Overrides broken profile-answer logic without rewriting the full file.

def _category_allowed(category, allowed):
    raw = str(category or "").strip().lower()
    norm = _normalize(raw)
    return raw in {str(x).lower() for x in allowed} or norm in {_normalize(x) for x in allowed}


def _safe_to_apply(field):
    label = _normalize(field.get("label") or "")
    category = str(field.get("category") or "").strip().lower()
    action = str(field.get("action") or "").strip().lower()
    answer = _pretty(field.get("recommended_answer"))

    if action != "autofill" or not answer:
        return False

    if _category_allowed(category, NEVER_AUTOFILL_CATEGORIES):
        return False

    if not _category_allowed(category, SAFE_AUTOFILL_CATEGORIES):
        return False

    if _as_float(field.get("confidence"), 0.0) < 0.80:
        return False

    for term in NEVER_AUTOFILL_LABEL_TERMS:
        term_norm = _normalize(term)
        if term_norm and term_norm in label and "talent community" not in label:
            return False

    return True


def _deterministic_profile_answer(label, category="", options=None):
    label_norm = _normalize(label)
    options = options or []

    if not label_norm:
        return None

    def pack(answer, category_value, confidence, reason):
        return {
            "answer": _option_match(answer, options),
            "category": category_value,
            "confidence": confidence,
            "reason": reason,
        }

    # These MUST come before any country/location logic.
    if (
        "sponsorship" in label_norm
        or "h 1b" in label_norm
        or "visa status" in label_norm
        or "company sponsorship" in label_norm
        or ("visa" in label_norm and "work authorization" in label_norm)
    ):
        return pack("No", "sponsorship", 0.99, "HOTFIX: sponsorship is No.")

    if (
        "legally authorized" in label_norm
        or "authorized to work" in label_norm
        or "eligible to work" in label_norm
        or "eligibility to work" in label_norm
        or ("eligible" in label_norm and "work" in label_norm and "country" in label_norm)
    ):
        return pack("Yes", "work_authorization", 0.99, "HOTFIX: work authorization is Yes.")

    if "san jose" in label_norm and (
        "office" in label_norm
        or "work environment" in label_norm
        or "willing" in label_norm
        or "able" in label_norm
        or "accommodate" in label_norm
    ):
        return pack("Yes", "onsite_willingness", 0.99, "HOTFIX: San Jose onsite willingness is Yes.")

    if "zip" in label_norm or "postal code" in label_norm:
        return pack("94560", "zip_code", 0.99, "HOTFIX: ZIP code is 94560.")

    if (
        "available" in label_norm
        and ("internship" in label_norm or "full time" in label_norm or "40 hours" in label_norm or "12 week" in label_norm or "term" in label_norm)
    ):
        return pack("Yes", "availability", 0.99, "HOTFIX: available for full-time internships; can take time off school.")

    if ("austin" in label_norm and "office" in label_norm) or ("office" in label_norm and ("3 5" in label_norm or "days a week" in label_norm)):
        return pack("Yes", "onsite_willingness", 0.99, "HOTFIX: willing to work in-office for internships.")

    if "previously worked" in label_norm or "worked for veeam" in label_norm:
        return pack("No", "previous_employment", 0.99, "HOTFIX: previously worked is No.")

    if (
        "own operate" in label_norm
        or "provide services to any other business" in label_norm
        or "other business" in label_norm
        or "consultancy" in label_norm
        or "freelance" in label_norm
        or "board membership" in label_norm
        or "contractual engagement" in label_norm
        or "outside business" in label_norm
    ):
        return pack("No", "outside_business", 0.99, "HOTFIX: outside business activity is No.")

    if "talent community" in label_norm:
        return pack("Yes", "talent_community", 0.95, "HOTFIX: talent community is Yes.")

    return None


# HOTFIX_CONDITIONAL_OUTSIDE_BUSINESS_TEXTAREA_2026_10_01
# If the applicant answered No to outside business activity, fill the required
# conditional "If yes, describe..." textarea with a safe N/A statement.

_PREVIOUS_DETERMINISTIC_PROFILE_ANSWER_FOR_TEXTAREA = _deterministic_profile_answer


def _deterministic_profile_answer(label, category="", options=None):
    label_norm = _normalize(label)
    options = options or []

    def pack(answer, category_value, confidence, reason):
        return {
            "answer": _option_match(answer, options),
            "category": category_value,
            "confidence": confidence,
            "reason": reason,
        }

    if (
        "if yes" in label_norm
        and "describe" in label_norm
        and (
            "nature of the activity" in label_norm
            or "your role" in label_norm
            or "responsibilities or interests of veeam" in label_norm
            or "overlap with the responsibilities" in label_norm
        )
    ):
        return pack(
            "N/A - I do not currently own, operate, or provide services to any other business or organization.",
            "outside_business",
            0.99,
            "HOTFIX: outside business activity is No, so the conditional explanation field is not applicable.",
        )

    return _PREVIOUS_DETERMINISTIC_PROFILE_ANSWER_FOR_TEXTAREA(label, category, options)
