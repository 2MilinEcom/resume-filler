from __future__ import annotations

import os
import re
from typing import Any

try:
    from src.profile import PROFILE
except Exception:
    PROFILE = {}


def truthy(value: str | None, default: str = "false") -> bool:
    raw = value if value is not None else default
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


POLICY = {
    "can_create_external_accounts": truthy(os.getenv("EXTERNAL_ACCOUNT_CREATION_ENABLED", "true"), "true"),
    "can_save_generated_passwords": True,
    "can_accept_standard_account_terms": truthy(os.getenv("EXTERNAL_ACCOUNT_ACCEPT_TERMS", "true"), "true"),
    "can_submit_native_handshake": True,
    "external_final_submit_mode": os.getenv("EXTERNAL_FINAL_SUBMIT_MODE", "stop_at_final_review"),
    "missing_documents_mode": "stop",
    "unknown_personal_fact_mode": "ask_or_stop",
}

FINAL_SUBMIT_RE = re.compile(r"^(submit|submit application|send application|apply|finish application|complete application)$", re.I)
DANGEROUS_TEXT_RE = re.compile(
    r"captcha|verify you are human|human verification|signature|certify|i certify|under penalty|background check|ssn|social security|driver'?s license|passport",
    re.I,
)
MISSING_DOC_RE = re.compile(r"cover letter|portfolio|writing sample|project|school or work project|other document", re.I)
STANDARD_TERMS_RE = re.compile(r"terms of use|privacy statement|privacy policy|data privacy|data processing|read and accept", re.I)


def profile_summary() -> dict[str, Any]:
    keys = [
        "first_name", "preferred_first_name", "last_name", "email", "phone",
        "city", "state", "state_full", "country", "country_full", "zip_code",
        "school", "degree", "major", "graduation_month", "graduation_year", "expected_graduation",
        "authorized_us", "sponsorship", "requires_sponsorship", "onsite_willing", "relocation_willing",
        "available_january_may", "full_time_internship_available", "twelve_week_internship_available",
        "forty_hour_internship_available", "can_take_semester_off_for_internship", "can_take_time_off_for_internship",
        "previously_worked_for_company", "outside_business_activity", "talent_community", "how_heard",
        "gender", "hispanic_latino", "veteran_status", "linkedin",
    ]
    result: dict[str, Any] = {}
    for key in keys:
        if key in PROFILE:
            value = PROFILE.get(key)
            if value is not None and str(value).strip():
                result[key] = str(value)
    return result


def documents_summary() -> dict[str, str]:
    docs: dict[str, str] = {}
    for key in ["resume", "transcript", "cover_letter", "portfolio", "writing_sample", "project"]:
        value = PROFILE.get(key)
        if value:
            docs[key] = str(value)
    return docs


def is_final_submit_text(text: str | None) -> bool:
    return bool(FINAL_SUBMIT_RE.search(str(text or "").strip()))


def page_has_human_verification(text: str | None) -> bool:
    return bool(DANGEROUS_TEXT_RE.search(str(text or "")))


def missing_document_mentions(text: str | None) -> list[str]:
    body = str(text or "")
    hits = []
    for match in MISSING_DOC_RE.finditer(body):
        term = match.group(0)
        if term.lower() not in {h.lower() for h in hits}:
            hits.append(term)
    return hits


def is_standard_terms_text(text: str | None) -> bool:
    return bool(STANDARD_TERMS_RE.search(str(text or "")))
