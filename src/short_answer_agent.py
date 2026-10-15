from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, Optional

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


ROOT = Path(__file__).resolve().parent.parent


SHORT_ANSWER_KEYWORDS = [
    "why are you interested",
    "why do you want",
    "why this",
    "what products",
    "what features",
    "what are you interested in building",
    "tell us about",
    "describe",
    "briefly explain",
    "short answer",
    "essay",
    "cover letter",
    "statement",
    "motivation",
    "what excites you",
    "why cloudflare",
    "why our company",
    "why this role",
    "why this internship",
]

BLOCKED_SHORT_ANSWER_TERMS = [
    "desired salary",
    "salary expectation",
    "compensation",
    "disability",
    "sexual orientation",
    "transgender",
    "race",
    "ethnicity",
    "hispanic",
    "latino",
    "veteran",
    "protected veteran",
    "signature",
    "certify",
    "certification",
    "attest",
    "captcha",
    "human verification",
    "authorization to contact",
]


def _truthy(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def short_answer_agent_enabled() -> bool:
    return _truthy(os.getenv("SHORT_ANSWER_AGENT_ENABLED", "true"), True)


def _norm(text: Any) -> str:
    text = str(text or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _clean(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


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

    return {"answer": text, "confidence": 0.0, "reason": "Model did not return JSON."}


def _load_optional_text_file(path: Path, max_chars: int = 12000) -> str:
    try:
        if path.exists() and path.is_file():
            return path.read_text(errors="replace")[:max_chars]
    except Exception:
        pass
    return ""


def load_applicant_brief() -> str:
    candidates = [
        ROOT / "documents" / "applicant_brief.md",
        ROOT / "documents" / "ApplicantBrief.md",
        ROOT / "applicant_brief.md",
        ROOT / "data" / "applicant_brief.md",
    ]

    for candidate in candidates:
        text = _load_optional_text_file(candidate)
        if text.strip():
            return text.strip()

    return ""


def profile_for_prompt() -> Dict[str, Any]:
    keep = [
        "first_name",
        "preferred_first_name",
        "last_name",
        "email",
        "phone",
        "city",
        "state",
        "state_full",
        "country",
        "zip_code",
        "school",
        "degree",
        "major",
        "graduation_month",
        "graduation_year",
        "expected_graduation",
        "authorized_us",
        "sponsorship",
        "onsite_willing",
        "available_january_may",
        "previously_worked_for_company",
        "outside_business_activity",
        "archetype",
        "how_heard",
        "linkedin",
    ]

    result: Dict[str, Any] = {}
    for key in keep:
        value = PROFILE.get(key)
        if value is not None:
            result[key] = str(value)
    return result


def _page_text(page, max_chars: int = 14000) -> str:
    try:
        text = page.locator("body").inner_text(timeout=3000)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars]
    except Exception:
        return ""


def _infer_limits(question: str) -> Dict[str, Optional[int]]:
    q = str(question or "")
    limits: Dict[str, Optional[int]] = {"max_words": None, "max_chars": None}

    word_matches = re.findall(r"(?:under|within|max(?:imum)?|up to|no more than)?\s*(\d{2,4})\s*words?", q, flags=re.I)
    if word_matches:
        try:
            limits["max_words"] = min(int(word_matches[-1]), 600)
        except Exception:
            pass

    char_matches = re.findall(r"(?:under|within|max(?:imum)?|up to|no more than)?\s*(\d{2,5})\s*characters?", q, flags=re.I)
    if char_matches:
        try:
            limits["max_chars"] = min(int(char_matches[-1]), 4000)
        except Exception:
            pass

    return limits


def should_draft_short_answer(question: str) -> bool:
    q = _norm(question)

    if not q:
        return False

    if any(_norm(term) in q for term in BLOCKED_SHORT_ANSWER_TERMS):
        return False

    if len(q) < 35:
        return False

    return any(_norm(keyword) in q for keyword in SHORT_ANSWER_KEYWORDS)


def _trim_answer(answer: str, question: str) -> str:
    answer = str(answer or "").strip()
    answer = re.sub(r"^```(?:text|markdown)?", "", answer, flags=re.I).strip()
    answer = re.sub(r"```$", "", answer).strip()
    answer = re.sub(r"\n{3,}", "\n\n", answer)

    limits = _infer_limits(question)
    max_chars = limits.get("max_chars")
    max_words = limits.get("max_words")

    if max_chars and len(answer) > max_chars:
        answer = answer[: max_chars - 1].rsplit(" ", 1)[0].rstrip(".,;:") + "."

    if max_words:
        words = answer.split()
        if len(words) > max_words:
            answer = " ".join(words[:max_words]).rstrip(".,;:") + "."

    # Keep generated answers reasonable even when no limit is specified.
    if not max_words and len(answer.split()) > 230:
        answer = " ".join(answer.split()[:230]).rstrip(".,;:") + "."

    return answer.strip()


def build_short_answer_prompt(
    *,
    company: str,
    title: str,
    question: str,
    page_text: str,
    applicant_brief: str,
) -> str:
    profile_json = json.dumps(profile_for_prompt(), indent=2, ensure_ascii=False)
    limits = _infer_limits(question)
    max_words = limits.get("max_words") or 180
    max_chars = limits.get("max_chars")

    limit_instruction = f"Aim for {max_words} words or fewer."
    if max_chars:
        limit_instruction += f" Stay under {max_chars} characters."

    return f"""
You are drafting a polished short-answer response for a job application.

Return JSON only:
{{
  "answer": "finished answer to paste into the form",
  "confidence": 0.0,
  "needs_user_review": true,
  "reason": "brief explanation"
}}

Applicant profile:
{profile_json}

Optional applicant brief from documents/applicant_brief.md:
{applicant_brief or "(No applicant brief was found.)"}

Application context:
Company: {company}
Role: {title}
Question: {question}

Visible page/job text excerpt:
{page_text[:14000]}

Rules:
- Write the finished answer, not notes or bullets unless the question asks for bullets.
- Use first person singular.
- Be specific to the company/role using only company/product/role details visible in the page text or generally named in the question.
- Use known applicant facts: UC Berkeley EECS, expected graduation June 2027, GPA 3.67, U.S. work-authorized/no sponsorship, and strong product/growth/technical execution experience.
- For marketing, growth, brand, social media, content, product marketing, or e-commerce roles, emphasize: founded/scaled e-commerce businesses from $800 to $2M+ revenue and 30K+ orders; managed $800K+ paid advertising spend; built acquisition/retention systems; conversion optimization; grew Lirvana Labs YouTube presence to about 100K monthly views; executed a $20K+ campaign; and combines marketing with technical/product experience.
- For software/AI roles, emphasize the BlackRock/AWS/Facebook/Apple technical and product background where relevant. The applicant can take time off school for internships and is available for full-time internships when asked. Do not include email signatures, markdown bolding, or résumé-header text in the answer.
- Do not invent projects, internships, research, publications, leadership roles, security experience, or quantified results that are not in the profile or applicant brief.
- It is okay to express interest, motivation, and what the applicant would like to build.
- Avoid overclaiming. Prefer "I am interested in" or "I would be excited to" when experience is not explicitly known.
- Do not mention that an AI wrote this.
- {limit_instruction}
""".strip()


def generate_short_answer(
    *,
    page,
    company: str,
    title: str,
    question: str,
    source: str = "application",
) -> Dict[str, Any]:
    if not short_answer_agent_enabled():
        return {"ok": False, "status": "disabled", "answer": None, "reason": "Short-answer agent disabled."}

    if not should_draft_short_answer(question):
        return {"ok": False, "status": "not_short_answer", "answer": None, "reason": "Question does not look like a draftable short-answer prompt."}

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return {"ok": False, "status": "missing_api_key", "answer": None, "reason": "OPENAI_API_KEY is missing."}

    model = (
        os.getenv("SHORT_ANSWER_AGENT_MODEL", "").strip()
        or os.getenv("APPLICATION_AGENT_MODEL", "").strip()
        or "gpt-5-mini"
    )

    try:
        from openai import OpenAI

        page_excerpt = _page_text(page)
        applicant_brief = load_applicant_brief()
        prompt = build_short_answer_prompt(
            company=company,
            title=title,
            question=question,
            page_text=page_excerpt,
            applicant_brief=applicant_brief,
        )

        client = OpenAI()
        response = client.responses.create(
            model=model,
            input=prompt,
        )

        parsed = _extract_json_object(response.output_text)
        answer = _trim_answer(str(parsed.get("answer") or ""), question)

        if not answer:
            return {"ok": False, "status": "empty_answer", "answer": None, "reason": "Model returned an empty answer."}

        return {
            "ok": True,
            "status": "drafted",
            "answer": answer,
            "confidence": parsed.get("confidence", 0.0),
            "needs_user_review": bool(parsed.get("needs_user_review", True)),
            "reason": parsed.get("reason") or "OpenAI drafted a short answer.",
            "source": source,
        }

    except Exception as exc:
        return {"ok": False, "status": "error", "answer": None, "reason": repr(exc)}


def _review_mode() -> str:
    mode = os.getenv("SHORT_ANSWER_REVIEW_MODE", "approve").strip().lower()
    if mode in {"off", "none", "false", "0"}:
        return "off"
    if mode in {"notify", "notification", "email_only"}:
        return "notify"
    return "approve"


def _review_timeout_seconds() -> int:
    try:
        return max(0, int(os.getenv("SHORT_ANSWER_REVIEW_TIMEOUT_SECONDS", "60").strip()))
    except Exception:
        return 60


def _send_review_email(
    *,
    company: str,
    title: str,
    question: str,
    answer: str,
    wait_for_reply: bool,
) -> Optional[str]:
    try:
        from src.email_helper import EmailConfig, clean_reply_text, get_email_config, wait_for_reply as wait_for_email_reply, _send_email
    except Exception:
        return None

    config = get_email_config()
    if config is None:
        return None

    question_id = "SA" + uuid.uuid4().hex[:6].upper()
    subject = f"Resume Filler Draft [RF-{question_id}]"
    mode_line = (
        "Reply OK to use it, reply UPDATE: <new answer> to replace it, or reply STOP to leave this application for manual review. "
        f"If you do not reply within {_review_timeout_seconds()} seconds, the bot will use the draft."
        if wait_for_reply
        else "This draft was filled automatically. Reply with corrections if you want me to reuse them for future applications."
    )

    body = (
        "Resume Filler drafted a short-answer response.\n\n"
        f"Company: {company}\n"
        f"Job: {title}\n\n"
        "Question:\n"
        f"{question}\n\n"
        "Draft answer:\n"
        f"{answer}\n\n"
        f"{mode_line}\n\n"
        f"Draft ID: RF-{question_id}"
    )

    try:
        _send_email(config, subject, body)
        print(f"  ✉ Emailed completed short-answer draft to {config.notify_email}")
    except Exception as exc:
        print(f"  ⚠ Could not email short-answer draft: {exc}")
        return None

    if not wait_for_reply:
        return None

    timeout = _review_timeout_seconds()
    if timeout <= 0:
        return None

    try:
        review_config = replace(config, timeout_seconds=timeout, poll_seconds=min(config.poll_seconds, 5))
    except Exception:
        review_config = config
        review_config.timeout_seconds = timeout
        review_config.poll_seconds = min(config.poll_seconds, 5)

    print(f"  Waiting {timeout} seconds for optional short-answer edits...")
    reply = wait_for_email_reply(question_id, review_config)
    if not reply:
        print("  No short-answer edits received; using generated draft.")
        return None

    return clean_reply_text(reply)


def _first_nonempty_line(text: str) -> str:
    for line in str(text or "").splitlines():
        line = line.strip().strip("*_ ")
        if line:
            return line
    return ""


def _strip_likely_signature(text: str) -> str:
    lines = str(text or "").splitlines()
    kept = []
    signature_markers = [
        "sample guzman",
        "eecs freshman",
        "he / him",
        "he/him",
        "university of california",
        "linkedin.com/in/guzmansample",
    ]

    for line in lines:
        cleaned = line.strip().strip("*_ ")
        norm = _norm(cleaned)
        if any(marker in norm for marker in signature_markers):
            break
        kept.append(line)

    return "\n".join(kept).strip()


def _apply_review_reply(reply: Optional[str], draft: str) -> Dict[str, Any]:
    if not reply:
        return {"status": "use", "answer": draft, "reason": "No review reply; using generated draft."}

    cleaned = _strip_likely_signature(str(reply or "").strip())
    first_line = _first_nonempty_line(cleaned or reply)
    first_norm = _norm(first_line)
    full_norm = _norm(cleaned)

    approval_markers = {
        "ok", "okay", "yes", "y", "approved", "approve", "use", "use it",
        "send", "submit", "continue", "looks good", "good", "great", "fine",
        "lgtm", "go", "go ahead",
    }

    if first_norm in approval_markers or full_norm in approval_markers:
        return {"status": "use", "answer": draft, "reason": "User approved generated draft."}

    stop_markers = {"stop", "manual", "manual review", "skip", "leave blank"}
    if first_norm in stop_markers or full_norm in stop_markers:
        return {"status": "stop", "answer": None, "reason": "User requested manual review/stop."}

    # Prefer explicit edit commands. This prevents replies like "OK" plus a mail
    # signature from replacing a good draft with a signature block.
    explicit = re.match(r"^(update|replace|edit|use this|answer)\s*:\s*(.*)$", cleaned, flags=re.I | re.S)
    if explicit:
        replacement = explicit.group(2).strip()
        if replacement:
            return {"status": "use", "answer": replacement, "reason": "Using user's explicit review edit as replacement answer."}

    # Backward compatibility: if the user replies with a substantial paragraph
    # and did not use an approval/stop command, treat it as a replacement.
    if len(cleaned.split()) >= 12:
        return {"status": "use", "answer": cleaned, "reason": "Using user's review edit as replacement answer."}

    return {"status": "use", "answer": draft, "reason": "Review reply was not an explicit edit; using generated draft."}

def draft_short_answer_for_field(
    *,
    page,
    company: str,
    title: str,
    question: str,
    source: str = "application",
) -> Dict[str, Any]:
    """
    Generate a finished short-answer response and optionally email it for edits.

    Return shape:
      {"status": "use", "answer": "..."}       fill this answer
      {"status": "stop", "answer": None}        leave for manual review
      {"status": "unavailable", "answer": None} fallback to old email question flow
    """

    generated = generate_short_answer(
        page=page,
        company=company,
        title=title,
        question=question,
        source=source,
    )

    if not generated.get("ok"):
        return {
            "status": "unavailable",
            "answer": None,
            "reason": generated.get("reason") or generated.get("status") or "Short-answer agent unavailable.",
        }

    draft = str(generated.get("answer") or "").strip()
    if not draft:
        return {"status": "unavailable", "answer": None, "reason": "Generated draft was blank."}

    print("  ✓ OpenAI drafted a completed short-answer response")
    print(f"    {draft[:240]}{'...' if len(draft) > 240 else ''}")

    mode = _review_mode()
    if mode == "off":
        return {"status": "use", "answer": draft, "reason": "Review email disabled."}

    reply = _send_review_email(
        company=company,
        title=title,
        question=question,
        answer=draft,
        wait_for_reply=(mode == "approve"),
    )

    reviewed = _apply_review_reply(reply, draft)
    if reviewed.get("answer"):
        reviewed["answer"] = _trim_answer(str(reviewed["answer"]), question)

    return reviewed
