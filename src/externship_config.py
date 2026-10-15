from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"


def load_env_file(path: Path = ENV_PATH) -> None:
    """Tiny .env loader that avoids python-dotenv stdin/find_dotenv issues."""
    if not path.exists():
        return
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except Exception:
        return


def get_env(name: str, default: str = "") -> str:
    load_env_file()
    return os.getenv(name, default).strip()


def get_bool_env(name: str, default: bool = False) -> bool:
    raw = get_env(name, "true" if default else "false").lower()
    return raw in {"1", "true", "yes", "y", "on"}


def get_int_env(name: str, default: int) -> int:
    try:
        return int(get_env(name, str(default)))
    except Exception:
        return default


def get_float_env(name: str, default: float) -> float:
    try:
        return float(get_env(name, str(default)))
    except Exception:
        return default


DEFAULT_CENTER_ADDRESS = get_env("EXTERNSHIP_CENTER", "Berkeley, CA 94704")
DEFAULT_RADIUS_MILES = get_float_env("EXTERNSHIP_DEFAULT_RADIUS_MILES", 50.0)
DEFAULT_MAX_LEADS = get_int_env("EXTERNSHIP_MAX_LEADS_PER_RUN", 25)
DEFAULT_TOP = get_int_env("EXTERNSHIP_TOP_LEADS", DEFAULT_MAX_LEADS)

# Email/follow-up defaults.
GMAIL_CREDENTIALS_PATH = Path(get_env("GMAIL_CREDENTIALS_PATH", str(ROOT / "credentials.json"))).expanduser()
GMAIL_TOKEN_PATH = Path(get_env("GMAIL_TOKEN_PATH", str(ROOT / "data" / "gmail_token.json"))).expanduser()
OUTREACH_APPROVAL_REQUIRED = get_bool_env("OUTREACH_APPROVAL_REQUIRED", True)
FOLLOWUP_1_DAYS = get_int_env("EXTERNSHIP_FOLLOWUP_1_DAYS", 4)
FOLLOWUP_2_DAYS = get_int_env("EXTERNSHIP_FOLLOWUP_2_DAYS", 7)
OUTREACH_DAILY_SEND_LIMIT = get_int_env("EXTERNSHIP_DAILY_SEND_LIMIT", 25)

# Lead filtering. Default is strict because Sample needs real clinics, not paid schools/training academies.
EXCLUDE_ACADEMY_LEADS = get_bool_env("EXTERNSHIP_EXCLUDE_ACADEMY_LEADS", True)
ACADEMY_EXCLUDE_TERMS = [
    term.strip().lower()
    for term in get_env(
        "EXTERNSHIP_ACADEMY_EXCLUDE_TERMS",
        "academy,school,college,university,career services,career center,training institute,training school,"
        "certificate program,certification program,admissions,tuition,campus,student placement office,"
        "medical academy,healthcare academy,externship placement school,education center,learning center",
    ).split(",")
    if term.strip()
]

# Use several Bay Area anchors because Places Nearby Search caps circle radius.
DEFAULT_DISCOVERY_CENTERS = [
    ("Berkeley", "Berkeley, CA 94704"),
    ("Oakland", "Oakland, CA"),
    ("San Francisco", "San Francisco, CA"),
    ("Walnut Creek", "Walnut Creek, CA"),
    ("San Leandro", "San Leandro, CA"),
    ("Hayward", "Hayward, CA"),
]

DEFAULT_SEARCH_QUERIES = [
    "medical clinic accepting externs",
    "medical assistant externship clinic",
    "primary care clinic",
    "family medicine clinic",
    "community health center",
    "urgent care clinic",
    "pediatrics clinic",
    "dermatology clinic",
    "OB GYN clinic",
    "orthopedic clinic",
    "occupational medicine clinic",
    "women's health clinic",
]

# Email copy controls.
# candidate = first-person Sample voice. Use helper only if you intentionally want coordinator wording.
EXTERNSHIP_EMAIL_SENDER_MODE = get_env("EXTERNSHIP_EMAIL_SENDER_MODE", "candidate")
EXTERNSHIP_HELPER_NAME = get_env("EXTERNSHIP_HELPER_NAME", "Sample Applicant")
EXTERNSHIP_HELPER_LINE = get_env("EXTERNSHIP_HELPER_LINE", "Coordinating outreach for Sample Applicant")

# Website-tailored email controls.
EXTERNSHIP_TAILOR_FROM_WEBSITE = get_bool_env("EXTERNSHIP_TAILOR_FROM_WEBSITE", True)
EXTERNSHIP_TAILOR_MAX_PAGES = get_int_env("EXTERNSHIP_TAILOR_MAX_PAGES", 6)


# Apollo contact enrichment controls. Defaults are conservative: email-only, no phone, no
# personal email, no waterfall/webhook flow. People search itself is 0 credits; bulk
# match/enrichment can consume credits when Apollo returns data.
APOLLO_API_KEY = get_env("APOLLO_API_KEY", "")
APOLLO_BASE_URL = get_env("APOLLO_BASE_URL", "https://api.apollo.io")
APOLLO_MAX_CREDITS_PER_RUN = get_int_env("APOLLO_MAX_CREDITS_PER_RUN", 25)
APOLLO_MAX_CONTACTS_PER_CLINIC = get_int_env("APOLLO_MAX_CONTACTS_PER_CLINIC", 1)
APOLLO_SEARCH_PER_CLINIC = get_int_env("APOLLO_SEARCH_PER_CLINIC", 5)
APOLLO_ENRICH_EMAILS = get_bool_env("APOLLO_ENRICH_EMAILS", True)
APOLLO_ENRICH_PHONES = get_bool_env("APOLLO_ENRICH_PHONES", False)
APOLLO_USE_WATERFALL = get_bool_env("APOLLO_USE_WATERFALL", False)
APOLLO_PERSONAL_EMAILS = get_bool_env("APOLLO_PERSONAL_EMAILS", False)
APOLLO_REQUEST_TIMEOUT = get_int_env("APOLLO_REQUEST_TIMEOUT", 30)
APOLLO_TARGET_TITLES = [
    x.strip()
    for x in get_env(
        "APOLLO_TARGET_TITLES",
        "Clinic Manager,Practice Manager,Office Manager,Medical Office Manager,Operations Manager,"
        "Practice Administrator,Clinic Administrator,Site Manager,Health Center Manager,Center Manager,"
        "Medical Director,Clinical Director,Human Resources,HR Manager,Talent Acquisition,"
        "Externship Coordinator,Student Coordinator,Training Coordinator,Program Coordinator",
    ).split(",")
    if x.strip()
]
APOLLO_CONTACT_EMAIL_STATUS = [
    x.strip()
    for x in get_env("APOLLO_CONTACT_EMAIL_STATUS", "verified,likely to engage,unverified").split(",")
    if x.strip()
]

# Hiring-intent controls. This separates "any email" from a likely person tied to
# hiring, recruiting, clinic operations, or a current medical-assistant opening.
EXTERNSHIP_HIRING_SCAN_MAX_PAGES = get_int_env("EXTERNSHIP_HIRING_SCAN_MAX_PAGES", 10)
APOLLO_REQUIRE_HIRING_CONTACT = get_bool_env("APOLLO_REQUIRE_HIRING_CONTACT", True)
APOLLO_REQUIRE_HIRING_SIGNAL = get_bool_env("APOLLO_REQUIRE_HIRING_SIGNAL", False)
APOLLO_HIRING_TARGET_TITLES = [
    x.strip()
    for x in get_env(
        "APOLLO_HIRING_TARGET_TITLES",
        "Talent Acquisition Partner,Recruiter,Healthcare Recruiter,Clinical Recruiter,Human Resources Manager,HR Manager,People Operations,"
        "Hiring Manager,Clinic Manager,Practice Manager,Medical Office Manager,Office Manager,Site Manager,Health Center Manager,Center Manager,"
        "Practice Administrator,Clinic Administrator,Clinical Operations Manager,Operations Manager,Director of Operations,"
        "Externship Coordinator,Student Placement Coordinator,Training Coordinator,Clinical Training Coordinator,Medical Director,Clinical Director",
    ).split(",")
    if x.strip()
]
