from __future__ import annotations

import json
import os
import re
from typing import Optional

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

try:
    from src.email_helper import normalize_reply_to_option
except Exception:
    normalize_reply_to_option = None

try:
    from src.profile import PROFILE
except Exception:
    PROFILE = {}

try:
    from src.answer_bank import find_saved_answer, save_answer
except Exception:
    find_saved_answer = None
    save_answer = None


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _enabled() -> bool:
    return _truthy(os.getenv("CHOICE_ANSWER_AGENT_ENABLED", "true"))


def _normalize(text: str) -> str:
    text = str(text or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_json(text: str) -> dict:
    text = str(text or "").strip()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        return {}

    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}




def _question_too_generic_for_answer_bank(question: str, options: list[str]) -> bool:
    if not options:
        return False
    lower = " ".join(str(question or "").lower().split())
    generic = {
        "required dropdown question",
        "required radio question",
        "required screening question",
        "select one",
        "select",
        "required",
    }
    return lower in generic or not lower or len(lower) < 8


def _option_match(answer: str, options: list[str]) -> Optional[str]:
    if not answer:
        return None

    if normalize_reply_to_option is not None:
        try:
            matched = normalize_reply_to_option(answer, options)
            if matched:
                return matched
        except Exception:
            pass

    answer_norm = _normalize(answer)

    for option in options:
        if _normalize(option) == answer_norm:
            return option

    for option in options:
        option_norm = _normalize(option)
        if answer_norm and (
            answer_norm in option_norm
            or option_norm in answer_norm
        ):
            return option

    return None


def _saved_answer(company: str, title: str, question: str, options: list[str]) -> Optional[str]:
    if find_saved_answer is None:
        return None

    if _question_too_generic_for_answer_bank(question, options):
        return None

    try:
        answer = find_saved_answer(
            company=company,
            title=title,
            question=question,
            options=options,
        )
    except Exception:
        return None

    return _option_match(str(answer or ""), options)


def _save_answer(
    company: str,
    title: str,
    question: str,
    options: list[str],
    answer: str,
    raw_reply: str,
) -> None:
    if save_answer is None:
        return

    if _question_too_generic_for_answer_bank(question, options):
        return

    try:
        save_answer(
            company=company,
            title=title,
            question=question,
            answer=answer,
            options=options,
            raw_reply=raw_reply,
            source="ai_choice_agent",
        )
    except Exception:
        pass


def _profile_for_prompt() -> dict:
    keys = [
        "first_name",
        "last_name",
        "email",
        "phone",
        "school",
        "degree",
        "major",
        "graduation_month",
        "graduation_year",
        "expected_graduation",
        "authorized_us",
        "sponsorship",
        "requires_sponsorship",
        "onsite_willing",
        "available_january_may",
        "full_time_internship_available",
        "can_take_time_off_school_for_internship",
        "how_heard",
        "linkedin",
        "gender",
        "hispanic_latino",
        "veteran_status",
    ]

    result = {}

    for key in keys:
        value = PROFILE.get(key)
        if value is not None:
            result[key] = str(value)

    return result


def _build_prompt(
    *,
    company: str,
    title: str,
    question: str,
    options: list[str],
    context: str,
) -> str:
    profile_json = json.dumps(_profile_for_prompt(), ensure_ascii=False, indent=2)
    options_json = json.dumps(options, ensure_ascii=False, indent=2)

    return f"""
You are an AI choice resolver inside a job-application autofill bot.

Your task:
Choose the best option from the provided options for the applicant, or return null if the answer is not safe to infer.

Return JSON only:
{{
  "answer": "exact option text from the options list, or null",
  "confidence": 0.0,
  "safe_to_use": true,
  "reason": "brief explanation"
}}

Applicant profile:
{profile_json}

Standing applicant rules and preferences:
- The applicant is Sample Applicant, a UC Berkeley EECS student.
- The applicant plans to graduate in December 2028.
- The applicant can take time off school for internships and is trying to secure an internship.
- For internship availability questions asking about 12-week, full-time, 40-hours/week, summer, spring, fall, or selectable terms, the answer is generally Yes when Yes is an available option.
- For office, onsite, hybrid, relocation, or city-specific internship work questions, the applicant is generally willing/able when needed for the internship. Choose Yes when the options support it.
- For work authorization in the United States, the applicant is authorized. Choose Yes when supported by options.
- For visa sponsorship, the applicant does not require sponsorship. Choose No when supported by options.
- For "How did you hear about this job/opportunity?" use the actual context: the bot found the role through Handshake / university career recruiting. If Handshake is not an option, choose the closest option such as a college/university career website or career fair. Do not choose Referral unless referral is explicitly known.
- Candidate privacy policy / privacy notice acknowledgement is a standard application acknowledgement. Choose an acknowledgement/confirm option when offered.
- Do not infer race, disability, sexual orientation, transgender identity, salary expectations, legal attestations beyond standard privacy acknowledgement, criminal/background information, or anything not supported by the profile/rules/options.
- Do not invent documents, essays, referrals, personal connections, employment history, or credentials.
- If the question is too ambiguous or the available options do not include a safe answer, return answer=null and safe_to_use=false.

Application context:
Company: {company}
Job title: {title}
Resolver context: {context}

Question:
{question}

Options:
{options_json}

Important:
- The answer must exactly match one of the options.
- Prefer a reasonable safe inference over emailing the user for routine logistical questions.
- Return null only when truly unsafe or unknowable.
""".strip()


def infer_choice_answer(
    *,
    company: str,
    title: str,
    question: str,
    options: list[str],
    context: str = "",
) -> Optional[str]:
    options = [str(option).strip() for option in (options or []) if str(option).strip()]

    if not options:
        return None

    saved = _saved_answer(company, title, question, options)
    if saved:
        print(f"  ✓ Reusing saved choice answer: {saved}")
        return saved

    if not _enabled():
        print("  ⚠ Choice-answer AI resolver disabled.")
        return None

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        print("  ⚠ OPENAI_API_KEY missing; choice-answer AI resolver skipped.")
        return None

    model = os.getenv("CHOICE_ANSWER_AGENT_MODEL", "gpt-5-mini").strip() or "gpt-5-mini"
    prompt = _build_prompt(
        company=company,
        title=title,
        question=question,
        options=options,
        context=context,
    )

    try:
        from openai import OpenAI

        client = OpenAI()
        response = client.responses.create(
            model=model,
            input=prompt,
        )

        parsed = _extract_json(response.output_text)
    except Exception as exc:
        print(f"  ⚠ Choice-answer AI resolver failed safely: {exc}")
        return None

    raw_answer = parsed.get("answer")
    confidence = parsed.get("confidence", 0)
    safe_to_use = bool(parsed.get("safe_to_use"))
    reason = str(parsed.get("reason") or "").strip()

    try:
        confidence_float = float(confidence)
    except Exception:
        confidence_float = 0.0

    if not raw_answer or not safe_to_use or confidence_float < 0.70:
        if reason:
            print(f"  ⚠ AI did not safely choose a choice answer: {reason}")
        else:
            print("  ⚠ AI did not safely choose a choice answer.")
        return None

    matched = _option_match(str(raw_answer), options)

    if not matched:
        print(f"  ⚠ AI returned answer not found in options: {raw_answer}")
        return None

    print(f"  ✓ AI choice answer: {matched}")
    if reason:
        print(f"    Reason: {reason}")

    _save_answer(
        company=company,
        title=title,
        question=question,
        options=options,
        answer=matched,
        raw_reply=json.dumps(parsed, ensure_ascii=False),
    )

    return matched
