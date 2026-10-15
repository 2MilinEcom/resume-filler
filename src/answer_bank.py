from __future__ import annotations

import json
import os
import re
import time
import unicodedata
from pathlib import Path
from typing import Any, Optional

try:
    from src.profile import PROFILE
except Exception:
    PROFILE = {}


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
ANSWER_BANK_PATH = DATA_DIR / "answer_bank.jsonl"


# ============================================================
# NORMALIZATION
# ============================================================

def normalize_text(text: str | None) -> str:
    if not text:
        return ""

    value = unicodedata.normalize("NFKD", str(text))
    value = "".join(
        char for char in value
        if not unicodedata.combining(char)
    )
    value = value.casefold()
    value = value.replace("&", " and ")
    value = re.sub(r"['’`]", "", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def token_set(text: str | None) -> set[str]:
    return set(normalize_text(text).split())


def option_signature(options: list[str] | None) -> str:
    normalized = [normalize_text(option) for option in (options or [])]
    normalized = [option for option in normalized if option]
    return "|".join(normalized)


def current_timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


# ============================================================
# SETTINGS
# ============================================================

def answer_bank_enabled() -> bool:
    return os.getenv("ANSWER_BANK_ENABLED", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def answer_bank_auto_reuse_enabled() -> bool:
    return os.getenv("ANSWER_BANK_AUTO_REUSE", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


# ============================================================
# CATEGORIES
# ============================================================

CATEGORY_REUSE_SCOPE = {
    # Safe reusable profile facts.
    "major_field": "category",
    "degree_level": "category",
    "school": "category",
    "gpa": "category",
    "graduation": "category",
    "linkedin": "category",
    "phone": "category",
    "email": "category",
    "name": "category",
    "location": "category",
    "work_authorization": "category",
    "sponsorship": "category",
    "previous_employment": "category",
    "outside_business": "category",
    "leadership": "category",
    "internship_experience": "exact",
    "student_organizations": "category",
    "availability": "category",
    "onsite": "category",
    "source": "category",
    "high_school": "category",
    "standardized_test": "category",
    "pronouns": "category",
    "prior_application": "category",
    "current_offers": "category",
    "further_education": "category",
    "privacy_acknowledgement": "category",
    "code_of_conduct": "category",
    "programming_languages": "category",
    "university_email": "category",
    "immigration_context": "category",

    # Store these, but only reuse for the exact same question/options.
    "gender": "exact",
    "hispanic_latino": "exact",
    "race_ethnicity": "exact",
    "veteran": "exact",
    "disability": "exact",
    "lgbtq": "exact",
    "transgender": "exact",
    "demographic": "exact",
    "essay": "exact",
    "company_specific": "exact",
    "conflict_of_interest": "exact",
    "government_relationship": "exact",
    "unknown": "exact",
}


def question_category(question: str) -> str:
    q = normalize_text(question)

    if not q:
        return "unknown"

    # These eligibility categories take precedence over location ("United States")
    # and over each other (sponsorship prompts mention "work authorization").
    if any(term in q for term in (
        "sponsorship", "sponsor", "visa status", "employment based visa",
        "employment based petition", "file a petition",
    )):
        return "sponsorship"
    if any(term in q for term in (
        "authorized to work", "authorization to work", "eligible to work",
        "work authorization", "legally authorized",
    )):
        return "work_authorization"

    # Essays / open writing should not be globally reused.
    if any(
        phrase in q
        for phrase in [
            "why are you interested",
            "why do you want",
            "why this role",
            "why this company",
            "cover letter",
            "tell us about",
            "describe your",
            "what interests you",
            "motivation for applying",
        ]
    ):
        return "essay"

    if any(
        phrase in q
        for phrase in [
            "government official",
            "public official",
            "elected official",
            "politically exposed",
        ]
    ):
        return "government_relationship"

    if any(
        phrase in q
        for phrase in [
            "familial relationship",
            "personal relationship",
            "relative",
            "conflict of interest",
            "investment",
            "intellectual property",
            "outside business interest",
        ]
    ):
        return "conflict_of_interest"

    if any(phrase in q for phrase in ["transgender", "trans gender", "gender identity different", "gender identity differ"]):
        return "transgender"

    if any(phrase in q for phrase in ["lgbtq", "lgbt", "sexual orientation", "heterosexual", "straight"]):
        return "lgbtq"

    if any(phrase in q for phrase in ["disability", "disabled"]):
        return "disability"

    if any(phrase in q for phrase in ["veteran", "military", "armed forces"]):
        return "veteran"

    if any(phrase in q for phrase in ["hispanic", "latino", "latina", "latinx"]):
        return "hispanic_latino"

    if any(phrase in q for phrase in ["race", "ethnicity", "ethnic"]):
        return "race_ethnicity"

    if "gender" in q:
        return "gender"

    if any(
        phrase in q
        for phrase in [
            "major",
            "field of study",
            "area of study",
            "discipline",
            "academic program",
            "computer science",
            "computer engineering",
            "electrical engineering",
            "engineering and computer sciences",
            "eecs",
        ]
    ):
        return "major_field"

    if any(
        phrase in q
        for phrase in [
            "degree",
            "bachelor",
            "bachelors",
            "bachelor s",
            "master",
            "masters",
            "phd",
            "doctorate",
        ]
    ):
        return "degree_level"

    # Specific school-related fields must be classified before generic school/email.
    if "high school" in q or "secondary school" in q:
        return "high_school"

    if "university email" in q or "school email" in q or "student email" in q:
        return "university_email"

    if any(phrase in q for phrase in ["school", "university", "college", "institution"]):
        return "school"

    if "gpa" in q or "grade point" in q or "4 0 scale" in q:
        return "gpa"

    if any(phrase in q for phrase in ["graduation", "graduate", "grad date", "completion date", "end date"]):
        return "graduation"

    if "linkedin" in q:
        return "linkedin"

    if "phone" in q or "mobile" in q:
        return "phone"

    if "email" in q:
        return "email"

    if any(phrase in q for phrase in ["first name", "last name", "preferred name", "full name"]):
        return "name"

    if any(
        phrase in q
        for phrase in [
            "location",
            "city",
            "state",
            "country",
            "zip",
            "postal code",
            "mailing address",
            "primary address",
            "residence",
        ]
    ):
        return "location"

    # Sponsorship questions often contain "work authorization" in the
    # parenthetical examples. They MUST NOT be treated as authorization
    # questions, otherwise the saved-answer/profile override returns Yes.
    if any(phrase in q for phrase in [
        "sponsorship", "sponsor", "visa status", "employment based visa",
        "employment based petition", "file a petition",
    ]):
        return "sponsorship"

    if any(phrase in q for phrase in [
        "authorized to work", "authorization to work", "eligible to work",
        "work authorization", "legally authorized",
    ]):
        return "work_authorization"

    if any(phrase in q for phrase in ["context", "immigration sponsorship needs", "sponsorship needs"]):
        return "immigration_context"

    if any(
        phrase in q
        for phrase in [
            "previously worked",
            "currently work at",
            "worked at",
            "worked for",
            "former employee",
            "employee or intern",
            "contractor role",
            "alumni",
        ]
    ):
        return "previous_employment"

    if any(
        phrase in q
        for phrase in [
            "outside business",
            "own operate",
            "consulting",
            "freelance",
            "other business",
            "business activity",
            "provide services",
        ]
    ):
        return "outside_business"

    if any(phrase in q for phrase in ["leadership", "leader", "club officer", "organization officer"]):
        return "leadership"

    if any(
        phrase in q
        for phrase in [
            "internship",
            "apprenticeship",
            "work experience",
            "comparable work experience",
            "technical experience",
        ]
    ):
        return "internship_experience"

    if any(
        phrase in q
        for phrase in [
            "university organization",
            "student organization",
            "club",
            "society",
            "student group",
        ]
    ):
        return "student_organizations"

    if any(phrase in q for phrase in ["available", "availability", "january", "may", "summer"]):
        return "availability"

    if any(phrase in q for phrase in ["onsite", "on site", "in office", "office 5 days", "hybrid"]):
        return "onsite"

    if any(phrase in q for phrase in ["how did you hear", "source", "where did you hear"]):
        return "source"

    if "high school" in q or "secondary school" in q:
        return "high_school"

    if any(phrase in q for phrase in ["standardized test", "act", "sat", "test score"]):
        return "standardized_test"

    if "pronoun" in q:
        return "pronouns"

    if any(phrase in q for phrase in ["applied to this role", "applied within", "last 12 months", "last 12 18 months", "another role"]):
        return "prior_application"

    if "current" in q and "offer" in q:
        return "current_offers"

    if any(phrase in q for phrase in ["further education", "pursuing further", "graduate school", "after completing your current academic"]):
        return "further_education"

    if "privacy statement" in q or "privacy policy" in q:
        return "privacy_acknowledgement"

    if "code of conduct" in q:
        return "code_of_conduct"

    if any(phrase in q for phrase in ["programming language", "languages are you proficient", "java", "python"]):
        return "programming_languages"

    if "university email" in q or "school email" in q or "student email" in q:
        return "university_email"

    if any(phrase in q for phrase in ["context", "immigration sponsorship needs", "sponsorship needs"]):
        return "immigration_context"

    return "unknown"


def reuse_scope_for_question(question: str) -> str:
    return CATEGORY_REUSE_SCOPE.get(question_category(question), "exact")


# ============================================================
# PROFILE FACTS
# ============================================================

def profile_value(key: str, default: str = "") -> str:
    value = PROFILE.get(key, default)
    if value is None:
        return default
    return str(value)


def profile_list(key: str) -> list[str]:
    value = PROFILE.get(key)

    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]

    if value:
        return [str(value)]

    return []


def profile_answers_for_category(category: str) -> list[str]:
    answers: list[str] = []

    def add(value: str | None) -> None:
        if value and str(value).strip() and str(value) not in answers:
            answers.append(str(value))

    def extend(values: list[str]) -> None:
        for value in values:
            add(value)

    if category == "major_field":
        add(profile_value("major"))
        add("Electrical Engineering and Computer Sciences")
        add("Computer Science")
        add("Electrical Engineering")
        add("Computer Engineering")
        add("EECS")

    elif category == "degree_level":
        add(profile_value("degree"))
        extend(profile_list("degree_variants"))

    elif category == "school":
        add(profile_value("school"))
        extend(profile_list("school_variants"))

    elif category == "graduation":
        add(f"{profile_value('graduation_month')} {profile_value('graduation_year')}")
        extend(profile_list("graduation_variants"))
        extend(profile_list("graduation_month_variants"))
        extend(profile_list("graduation_year_variants"))

    elif category == "linkedin":
        add(profile_value("linkedin"))

    elif category == "phone":
        add(profile_value("phone"))

    elif category == "email":
        add(profile_value("email"))

    elif category == "name":
        add(profile_value("preferred_first_name"))
        add(profile_value("first_name"))
        add(profile_value("last_name"))

    elif category == "location":
        add(profile_value("city"))
        add(profile_value("state"))
        add(profile_value("state_full"))
        add(profile_value("country"))
        add(profile_value("zip_code"))
        extend(profile_list("location_variants"))
        extend(profile_list("country_variants"))
        extend(profile_list("state_variants"))

    elif category == "work_authorization":
        add(profile_value("authorized_us"))
        extend(profile_list("authorized_us_variants"))

    elif category == "sponsorship":
        add(profile_value("sponsorship"))
        extend(profile_list("sponsorship_variants"))

    elif category == "previous_employment":
        add(profile_value("previously_worked_for_company"))
        extend(profile_list("previously_worked_variants"))
        add("I have never worked there")
        add("I have never worked at this company")

    elif category == "outside_business":
        add(profile_value("outside_business_activity"))
        extend(profile_list("outside_business_activity_variants"))

    elif category == "availability":
        add(profile_value("available_january_may"))
        extend(profile_list("available_january_may_variants"))

    elif category == "onsite":
        add(profile_value("onsite_willing"))
        extend(profile_list("onsite_willing_variants"))

    elif category == "source":
        # IMC/Greenhouse often has Career website as the safest ATS source option.
        add("Career website")
        add(profile_value("how_heard"))
        add("Handshake")
        add("Handshake Job Board")

    elif category == "high_school":
        add(profile_value("high_school_graduation_year"))

    elif category == "standardized_test":
        add(profile_value("standardized_test_type"))
        add(profile_value("act_score"))
        add(profile_value("sat_score"))
        add("ACT")
        add(profile_value("act_score"))
        add("29")
        add("I don't have SAT score")

    elif category == "gpa":
        add(profile_value("gpa_range"))
        extend(profile_list("gpa_variants"))
        add(profile_value("gpa"))

    elif category == "pronouns":
        add(profile_value("preferred_pronouns"))
        add("he/him")

    elif category == "prior_application":
        add(profile_value("applied_last_12_months"))
        add("No")

    elif category == "current_offers":
        add(profile_value("current_offers"))
        add("No")

    elif category == "further_education":
        add(profile_value("further_education_plan"))

    elif category == "privacy_acknowledgement":
        add(profile_value("privacy_statement"))
        add("I Agree")
        add("I agree")

    elif category == "code_of_conduct":
        add(profile_value("interview_code_of_conduct"))
        add("I agree")
        add("I Agree")

    elif category == "programming_languages":
        extend(profile_list("programming_languages"))
        add("Python")
        add("Java")

    elif category == "university_email":
        add(profile_value("email"))

    elif category == "immigration_context":
        add(profile_value("immigration_sponsorship_context"))
        add("N/A")

    elif category == "gender":
        add(profile_value("gender"))
        extend(profile_list("gender_variants"))

    elif category == "hispanic_latino":
        add(profile_value("hispanic_latino"))
        extend(profile_list("hispanic_latino_variants"))

    elif category == "veteran":
        add(profile_value("veteran_status"))
        extend(profile_list("veteran_status_variants"))

    return answers


# ============================================================
# OPTION MATCHING
# ============================================================

def _extract_leading_option_number(text: str) -> Optional[int]:
    match = re.match(
        r"^(?:option\s*)?(\d+)(?:\s|[.)\-:])?.*$",
        text.strip(),
        flags=re.I,
    )

    if not match:
        return None

    try:
        return int(match.group(1))
    except Exception:
        return None


def _candidate_lines(text: str) -> list[str]:
    lines = [line.strip() for line in str(text).splitlines() if line.strip()]
    full = str(text).strip()

    candidates: list[str] = []

    for item in lines + [full]:
        item = re.sub(r"^(answer|reply|response|option)\s*:\s*", "", item, flags=re.I)
        item = re.sub(r"^(my answer is|i choose|i pick|select)\s+", "", item, flags=re.I)

        if item and item not in candidates:
            candidates.append(item)

    return candidates


def match_answer_to_option(answer: str | None, options: list[str] | None) -> Optional[str]:
    if not answer:
        return None

    if not options:
        return str(answer).strip() or None

    normalized_options = [(option, normalize_text(option)) for option in options]

    for candidate in _candidate_lines(str(answer)):
        number = _extract_leading_option_number(candidate)

        if number is not None:
            index = number - 1
            if 0 <= index < len(options):
                return options[index]

    for candidate in _candidate_lines(str(answer)):
        normalized_candidate = normalize_text(candidate)

        if not normalized_candidate:
            continue

        for option, normalized_option in normalized_options:
            if normalized_candidate == normalized_option:
                return option

    for candidate in _candidate_lines(str(answer)):
        normalized_candidate = normalize_text(candidate)

        if not normalized_candidate:
            continue

        for option, normalized_option in normalized_options:
            if not normalized_option:
                continue

            if normalized_option in normalized_candidate:
                return option

            if normalized_candidate in normalized_option:
                return option

    # Yes / No shorthand.
    for candidate in _candidate_lines(str(answer)):
        normalized_candidate = normalize_text(candidate)
        first_token = normalized_candidate.split(" ")[0] if normalized_candidate else ""

        if first_token in {"y", "yes"}:
            for option, normalized_option in normalized_options:
                if normalized_option in {"yes", "y"}:
                    return option

        if first_token in {"n", "no"}:
            for option, normalized_option in normalized_options:
                if normalized_option in {"no", "n"}:
                    return option

    return None


def yes_option(options: list[str]) -> Optional[str]:
    for option in options:
        if normalize_text(option) in {"yes", "y"}:
            return option
    return None


def no_option(options: list[str]) -> Optional[str]:
    for option in options:
        if normalize_text(option) in {"no", "n"}:
            return option
    return None


def option_contains(options: list[str], *phrases: str) -> Optional[str]:
    normalized_phrases = [normalize_text(phrase) for phrase in phrases]

    for option in options:
        normalized_option = normalize_text(option)
        if all(phrase in normalized_option for phrase in normalized_phrases if phrase):
            return option

    return None


# ============================================================
# SEMANTIC CATEGORY REUSE
# ============================================================

def question_mentions_cs_or_ce(question: str) -> bool:
    q = normalize_text(question)
    return any(
        phrase in q
        for phrase in [
            "computer science",
            "computer sciences",
            "computer engineering",
            "cs",
            "ce",
            "software engineering",
        ]
    )


def facts_indicate_cs_or_ce(facts: list[str]) -> bool:
    joined = normalize_text(" ".join(facts))
    return any(
        phrase in joined
        for phrase in [
            "computer science",
            "computer sciences",
            "computer engineering",
            "eecs",
            "electrical engineering and computer sciences",
        ]
    )


def facts_indicate_bachelors(facts: list[str]) -> bool:
    joined = normalize_text(" ".join(facts))
    return any(phrase in joined for phrase in ["bachelor", "bachelors", "bs", "b s"])


def infer_category_option(
    question: str,
    category: str,
    options: list[str],
    facts: list[str],
) -> Optional[str]:
    if not options:
        return None

    # Previous-employer questions often contain company-specific option text.
    if category == "previous_employment":
        never = option_contains(options, "never", "worked")
        if never:
            return never

        no = no_option(options)
        if no:
            return no

    if category in {"sponsorship", "outside_business"}:
        no = no_option(options)
        if no:
            return no

    if category in {"work_authorization", "availability", "onsite"}:
        yes = yes_option(options)
        if yes:
            return yes

    if category == "major_field":
        # Dropdowns with actual majors.
        for fact in facts:
            matched = match_answer_to_option(fact, options)
            if matched:
                return matched

        for fallback in [
            "Electrical Engineering and Computer Sciences",
            "Computer Science",
            "Computer Engineering",
            "Electrical Engineering",
            "Engineering",
        ]:
            matched = match_answer_to_option(fallback, options)
            if matched:
                return matched

        # Yes/No question about being in CS/CE.
        if question_mentions_cs_or_ce(question) and facts_indicate_cs_or_ce(facts):
            yes = yes_option(options)
            if yes:
                return yes

    if category == "degree_level":
        for fact in facts:
            matched = match_answer_to_option(fact, options)
            if matched:
                return matched

        if facts_indicate_bachelors(facts):
            yes = yes_option(options)
            if yes and any(
                phrase in normalize_text(question)
                for phrase in ["bachelor", "bachelors", "undergraduate"]
            ):
                return yes

    return None


def choose_category_text_answer(category: str, facts: list[str]) -> Optional[str]:
    if category == "major_field":
        for fact in facts:
            if normalize_text(fact) not in {"yes", "no"}:
                return fact

    if category == "degree_level":
        for fact in facts:
            if "bachelor" in normalize_text(fact):
                return fact

    if category in {
        "school",
        "gpa",
        "graduation",
        "linkedin",
        "phone",
        "email",
        "location",
        "work_authorization",
        "sponsorship",
        "previous_employment",
        "outside_business",
        "leadership",
        "internship_experience",
        "student_organizations",
        "availability",
        "onsite",
        "source",
    }:
        for fact in facts:
            if fact and str(fact).strip():
                return str(fact).strip()

    return None




# ============================================================
# PROFILE-FIRST DETERMINISTIC OVERRIDES
# ============================================================

_PROFILE_FIRST_CATEGORIES = {
    "work_authorization",
    "sponsorship",
    "gpa",
    "graduation",
    "high_school",
    "standardized_test",
    "pronouns",
    "prior_application",
    "current_offers",
    "further_education",
    "privacy_acknowledgement",
    "code_of_conduct",
    "programming_languages",
    "university_email",
    "immigration_context",
    "source",
    "gender",
    "hispanic_latino",
    "race_ethnicity",
    "veteran",
    "disability",
    "lgbtq",
    "transgender",
}


def _first_matching_option(options: list[str], *answers: str) -> Optional[str]:
    for answer in answers:
        matched = match_answer_to_option(answer, options)
        if matched:
            return matched
    return None


def _option_with_any(options: list[str], *phrases: str) -> Optional[str]:
    normalized_phrases = [normalize_text(p) for p in phrases if normalize_text(p)]
    for option in options:
        normalized_option = normalize_text(option)
        if any(phrase in normalized_option for phrase in normalized_phrases):
            return option
    return None


def _graduation_option(options: list[str]) -> Optional[str]:
    # User-confirmed source of truth as of 2026-10-01: June 2027.
    preferred = [
        "May 2027 - June 2027",
        "May 2027-June 2027",
        "January 2027 - July 2027",
        "January 2027 – July 2027",
        "Spring 2027",
        "June 2027",
        "2027",
    ]
    matched = _first_matching_option(options, *preferred)
    if matched:
        return matched

    # Prefer any 2027 option that does not push the user into a later Fall/Winter range.
    for option in options:
        n = normalize_text(option)
        if "2027" in n and not any(x in n for x in ["december", "fall", "winter"]):
            return option

    for option in options:
        if "2027" in normalize_text(option):
            return option

    return None


def deterministic_profile_answer(
    question: str,
    category: str | None = None,
    options: Optional[list[str]] = None,
) -> Optional[str]:
    """Return profile-critical answers before stale answer-bank entries can override them."""
    options = options or []
    category = category or question_category(question)
    q = normalize_text(question)

    # Verified employment history: applicant has completed internships.
    # This MUST run before any saved-answer lookup (and must not be confused
    # with questions about availability, previous employment at THIS company,
    # or whether the applicant wants an internship).
    prior_internship_question = (
        ("have you previously completed" in q or "have you completed" in q
         or "have you previously had" in q or "have you had" in q)
        and ("internship" in q or "internships" in q)
    ) or (
        "at least 1 internship" in q and "previously" in q
    )
    if prior_internship_question:
        return yes_option(options) if options else "Yes"

    if category not in _PROFILE_FIRST_CATEGORIES:
        return None

    # Work authorization / sponsorship are high-risk and must never reuse stale wrong answers.
    if category == "work_authorization":
        return yes_option(options) if options else "Yes"

    if category == "sponsorship":
        if any(phrase in q for phrase in ["require immigration sponsorship", "require sponsorship", "sponsorship to begin", "sponsorship in the future", "visa sponsorship"]):
            return no_option(options) if options else "No"
        return no_option(options) if options else "No"

    if category == "graduation":
        if "year" in q and not options:
            return profile_value("graduation_year", "2027")
        if options:
            return _graduation_option(options)
        return profile_value("expected_graduation", "June 2027")

    if category == "gpa":
        if options:
            return _first_matching_option(options, profile_value("gpa_range"), "3.61 - 3.7", "3.7")
        return profile_value("gpa", "3.7")

    if category == "high_school":
        if options:
            return _first_matching_option(options, profile_value("high_school_graduation_year"), "2023")
        return profile_value("high_school_graduation_year", "2023")

    if category == "standardized_test":
        if "sat" in q and "act" not in q:
            if options:
                return _first_matching_option(options, "I don't have SAT score", "No SAT", "N/A") or _option_with_any(options, "dont have", "do not have", "no sat")
            return profile_value("sat_score", "I don't have SAT score")
        if "act" in q:
            if options:
                return _first_matching_option(options, profile_value("act_score"), "29")
            return profile_value("act_score", "29")
        if options:
            return _first_matching_option(options, profile_value("standardized_test_type"), "ACT")
        return profile_value("standardized_test_type", "ACT")

    if category == "pronouns":
        if options:
            return _first_matching_option(options, profile_value("preferred_pronouns"), "he/him", "He/Him")
        return profile_value("preferred_pronouns", "he/him")

    if category == "prior_application":
        return no_option(options) if options else "No"

    if category == "current_offers":
        return no_option(options) if options else "No"

    if category == "further_education":
        answer = profile_value("further_education_plan", "No")
        if options:
            return (
                no_option(options)
                or _first_matching_option(options, answer, "I am not considering further education", "Not considering further education", "No")
            )
        return answer

    if category == "privacy_acknowledgement":
        if options:
            return _first_matching_option(options, "I Agree", "I agree", "Agree") or _option_with_any(options, "agree")
        return "I Agree"

    if category == "code_of_conduct":
        if options:
            return _first_matching_option(options, "I agree", "I Agree", "Agree") or _option_with_any(options, "agree")
        return "I agree"

    if category == "programming_languages":
        # For checkbox groups, callers may ask one field at a time. Prefer Python, then Java.
        if options:
            return _first_matching_option(options, "Python", "Java")
        return "Python, Java"

    if category == "university_email":
        return profile_value("university_email")

    if category == "immigration_context":
        return profile_value("immigration_sponsorship_context", "N/A")

    if category == "source":
        if options:
            return _first_matching_option(options, "Career website", "Handshake", "University career fair", "Campus recruiting")
        return profile_value("how_heard", "Handshake")

    if category == "gender":
        if options:
            return _first_matching_option(options, profile_value("gender"), "Male", "Man")
        return profile_value("gender", "Male")

    if category == "hispanic_latino":
        if options:
            return _first_matching_option(options, "Yes", "Yes, Hispanic or Latino", "Hispanic or Latino")
        return profile_value("hispanic_latino", "Yes")

    if category == "race_ethnicity":
        if options:
            return _first_matching_option(options, "Hispanic or Latino", "Hispanic/Latino", "Latino", "White")
        return profile_value("race_ethnicity", "Hispanic or Latino")

    if category == "veteran":
        if options:
            return _first_matching_option(options, profile_value("veteran_status"), "I am not a veteran", "Not a veteran", "No") or no_option(options)
        return profile_value("veteran_status", "Not a veteran")

    if category == "disability":
        if options:
            return _first_matching_option(options, profile_value("disability_status"), "No", "I do not have a disability", "No, I do not have a disability") or no_option(options)
        return profile_value("disability_status", "No")

    if category == "lgbtq":
        if options:
            return _first_matching_option(options, profile_value("sexual_orientation"), "Straight", "Heterosexual")
        return profile_value("sexual_orientation", "Straight")

    if category == "transgender":
        if options:
            return _first_matching_option(options, profile_value("transgender_status"), "No", "No, I am not transgender") or no_option(options)
        return profile_value("transgender_status", "No")

    return None


# ============================================================
# FILE IO
# ============================================================

def load_entries() -> list[dict[str, Any]]:
    if not ANSWER_BANK_PATH.exists():
        return []

    entries: list[dict[str, Any]] = []

    try:
        for line in ANSWER_BANK_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()

            if not line:
                continue

            try:
                item = json.loads(line)
            except Exception:
                continue

            if isinstance(item, dict):
                entries.append(item)

    except Exception:
        return []

    return entries


def append_entry(entry: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    with ANSWER_BANK_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True))
        handle.write("\n")


# ============================================================
# PUBLIC API
# ============================================================

def find_saved_answer(
    *,
    company: str,
    title: str,
    question: str,
    options: Optional[list[str]] = None,
) -> Optional[str]:
    if not answer_bank_enabled() or not answer_bank_auto_reuse_enabled():
        return None

    options = options or []
    normalized_question = normalize_text(question)
    signature = option_signature(options)
    category = question_category(question)
    scope = CATEGORY_REUSE_SCOPE.get(category, "exact")
    normalized_company = normalize_text(company)

    profile_override = deterministic_profile_answer(question, category, options)
    if profile_override:
        return profile_override

    entries = load_entries()

    # 1. Exact same question + exact same options is always the safest reuse.
    for entry in reversed(entries):
        if entry.get("normalized_question") != normalized_question:
            continue

        if entry.get("options_signature", "") != signature:
            continue

        stored_answer = str(entry.get("answer", "")).strip()

        if not stored_answer:
            continue

        if options:
            matched = match_answer_to_option(stored_answer, options)
            if matched:
                return matched
        else:
            return stored_answer

    # 2. Exact same question without option matching can reuse a prior text answer.
    if not options:
        for entry in reversed(entries):
            if entry.get("normalized_question") != normalized_question:
                continue

            stored_answer = str(entry.get("answer", "")).strip()

            if stored_answer:
                return stored_answer

    # 3. Exact-only categories stop here unless it is the same company + same category.
    if scope == "exact":
        for entry in reversed(entries):
            if entry.get("category") != category:
                continue

            if normalize_text(entry.get("company", "")) != normalized_company:
                continue

            if entry.get("normalized_question") != normalized_question:
                continue

            stored_answer = str(entry.get("answer", "")).strip()

            if not stored_answer:
                continue

            if options:
                matched = match_answer_to_option(stored_answer, options)
                if matched:
                    return matched
            else:
                return stored_answer

        return None

    # 4. Category reuse: collect profile facts plus prior answers in the same category.
    facts = profile_answers_for_category(category)

    for entry in reversed(entries):
        if entry.get("category") != category:
            continue

        stored_answer = str(entry.get("answer", "")).strip()

        if stored_answer and stored_answer not in facts:
            facts.append(stored_answer)

    if options:
        inferred = infer_category_option(question, category, options, facts)
        if inferred:
            return inferred

        for fact in facts:
            matched = match_answer_to_option(fact, options)
            if matched:
                return matched

        return None

    return choose_category_text_answer(category, facts)


def save_answer(
    *,
    company: str,
    title: str,
    question: str,
    answer: str,
    options: Optional[list[str]] = None,
    raw_reply: Optional[str] = None,
    source: str = "email",
) -> None:
    if not answer_bank_enabled():
        return

    answer = str(answer or "").strip()

    if not answer:
        return

    if normalize_text(answer) in {
        "skip",
        "manual",
        "manual review",
        "leave blank",
    }:
        return

    options = options or []
    category = question_category(question)
    scope = CATEGORY_REUSE_SCOPE.get(category, "exact")

    entry = {
        "created_at": current_timestamp(),
        "source": source,
        "company": company,
        "job_title": title,
        "question": question,
        "normalized_question": normalize_text(question),
        "category": category,
        "reuse_scope": scope,
        "options": options,
        "options_signature": option_signature(options),
        "answer": answer,
        "normalized_answer": normalize_text(answer),
    }

    if raw_reply is not None:
        entry["raw_reply"] = str(raw_reply).strip()

    append_entry(entry)
