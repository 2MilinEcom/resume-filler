from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Iterable, Optional

from playwright.sync_api import Page, Locator

from src.profile import PROFILE

try:
    from src.email_helper import ask_application_question
except Exception:
    ask_application_question = None

try:
    from src.application_agent import analyze_and_print_application_page
except Exception:
    analyze_and_print_application_page = None


# ============================================================
# NORMALIZATION / MATCHING
# ============================================================

STATE_ALIASES = {
    "ca": "california",
    "ny": "new york",
    "tx": "texas",
    "wa": "washington",
    "ma": "massachusetts",
}


def normalize(text: str) -> str:
    if not text:
        return ""

    text = unicodedata.normalize("NFKD", str(text))
    text = "".join(
        char for char in text
        if not unicodedata.combining(char)
    )

    text = text.casefold()
    text = text.replace("&", " and ")
    text = re.sub(r"['’`]", "", text)
    text = re.sub(r"[-–—,/()\[\]]", " ", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)

    words = text.split()
    expanded = [STATE_ALIASES.get(word, word) for word in words]

    return " ".join(expanded)


def digits_only(text: str) -> str:
    return re.sub(r"\D", "", text or "")


def token_set(text: str) -> set[str]:
    return set(normalize(text).split())


def similarity_score(
    desired: str,
    candidate: str,
) -> float:
    a = normalize(desired)
    b = normalize(candidate)

    if not a or not b:
        return 0.0

    if a == b:
        return 100.0

    if a in b:
        return 94.0

    if b in a:
        return 91.0

    a_tokens = token_set(a)
    b_tokens = token_set(b)

    if not a_tokens or not b_tokens:
        return 0.0

    intersection = a_tokens & b_tokens
    union = a_tokens | b_tokens

    jaccard = len(intersection) / len(union)
    coverage_a = len(intersection) / len(a_tokens)
    coverage_b = len(intersection) / len(b_tokens)

    return (
        jaccard * 50
        + coverage_a * 30
        + coverage_b * 20
    )


def best_option_match(
    desired_values: Iterable[str],
    options: list[tuple[int, str]],
) -> tuple[int, str, float] | None:
    candidates = []

    for index, option_text in options:
        best_score = 0.0

        for desired in desired_values:
            score = similarity_score(
                desired,
                option_text,
            )

            if score > best_score:
                best_score = score

        candidates.append(
            (
                best_score,
                index,
                option_text,
            )
        )

    if not candidates:
        return None

    candidates.sort(
        reverse=True,
        key=lambda item: item[0],
    )

    best_score, best_index, best_text = candidates[0]

    if best_score < 72:
        return None

    if len(candidates) > 1:
        second_score = candidates[1][0]

        if (
            best_score < 90
            and abs(best_score - second_score) < 4
        ):
            return None

    return (
        best_index,
        best_text,
        best_score,
    )


# ============================================================
# PROFILE HELPERS
# ============================================================

def profile_value(key: str, default: str = "") -> str:
    value = PROFILE.get(key, default)
    return str(value) if value is not None else default


def profile_list(key: str, fallback: Optional[list[str]] = None) -> list[str]:
    value = PROFILE.get(key)

    if isinstance(value, list):
        return [str(item) for item in value]

    if value:
        return [str(value)]

    return fallback or []


def graduation_variants_strict() -> list[str]:
    variants = profile_list("graduation_variants")

    strict = [
        item for item in variants
        if normalize(item) != profile_value("graduation_year", "2027")
    ]

    month = profile_value("graduation_month", "December")
    year = profile_value("graduation_year", "2027")

    preferred = [
        f"{month} {year}",
        f"{month[:3]} {year}",
    ]

    result = []

    for item in preferred + strict:
        if item and item not in result:
            result.append(item)

    return result


# ============================================================
# BASIC TEXT FIELDS
# ============================================================

def fill_text(
    page: Page,
    selector: str,
    value: str,
    name: str,
    *,
    phone: bool = False,
) -> bool:
    try:
        field = page.locator(selector).first

        if field.count() == 0:
            print(f"✗ {name}: field not found")
            return False

        field.scroll_into_view_if_needed()
        field.wait_for(state="visible")
        field.fill(value)
        field.blur()
        page.wait_for_timeout(150)

        actual = field.input_value().strip()

        if phone:
            success = digits_only(actual) == digits_only(value)
        else:
            success = normalize(actual) == normalize(value)

        if success:
            print(f"✓ {name}: {actual}")
            return True

        print(
            f"✗ {name}: verification failed\n"
            f"    Wanted:  {value!r}\n"
            f"    Browser: {actual!r}"
        )

        return False

    except Exception as exc:
        print(f"✗ {name}: {exc}")
        return False


# ============================================================
# DROPDOWN HELPERS
# ============================================================

def close_dropdown(page: Page) -> None:
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass


def read_visible_options(
    page: Page,
) -> list[tuple[int, str]]:
    page.wait_for_timeout(300)
    options = page.get_by_role("option")
    results = []

    try:
        count = options.count()
    except Exception:
        return results

    for i in range(count):
        try:
            option = options.nth(i)

            if not option.is_visible():
                continue

            text = option.inner_text().strip()

            if text:
                results.append((i, text))

        except Exception:
            continue

    return results


def open_and_search(
    page: Page,
    field: Locator,
    search_text: str,
) -> list[tuple[int, str]]:
    close_dropdown(page)

    field.scroll_into_view_if_needed()
    field.wait_for(state="visible")

    try:
        field.click()
    except Exception:
        field.click(force=True)

    page.wait_for_timeout(100)

    if search_text:
        try:
            field.fill("")
            field.fill(search_text)

        except Exception:
            try:
                page.keyboard.press("Meta+A")
                page.keyboard.type(search_text)
            except Exception:
                return []

    page.wait_for_timeout(400)

    return read_visible_options(page)


def click_option(
    page: Page,
    index: int,
    text: str,
) -> None:
    try:
        page.get_by_role(
            "option",
            name=text,
            exact=True,
        ).click()

    except Exception:
        page.get_by_role("option").nth(index).click()


def select_react_smart(
    page: Page,
    selector: str,
    search_variants: list[str],
    name: str,
) -> bool:
    try:
        field = page.locator(selector).first

        if field.count() == 0:
            print(f"✗ {name}: dropdown not found")
            return False

        print(f"\n--- {name} ---")
        all_seen = {}

        for search_text in search_variants:
            options = open_and_search(
                page,
                field,
                search_text,
            )

            for index, text in options:
                all_seen[text] = (index, text)

            match = best_option_match(
                search_variants,
                options,
            )

            if match is None:
                continue

            index, text, score = match

            click_option(
                page,
                index,
                text,
            )

            page.wait_for_timeout(200)

            print(
                f"✓ {name}: {text} "
                f"(confidence {score:.1f})"
            )

            return True

        close_dropdown(page)

        print(
            f"✗ {name}: no confident match"
        )

        if all_seen:
            print("  Options encountered:")

            for text in all_seen:
                print(f"    • {text}")

        return False

    except Exception as exc:
        print(f"✗ {name}: {exc}")
        close_dropdown(page)
        return False


# ============================================================
# LABEL / QUESTION DISCOVERY
# ============================================================

def clean_label_text(text: str) -> str:
    text = text or ""
    text = text.replace("*", "")
    text = re.sub(r"\bindicates a required field\b", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def label_is_required(text: str) -> bool:
    if not text:
        return False

    if "indicates a required field" in text.lower():
        return False

    return "*" in text


def find_fields_by_label_text(
    page: Page,
    phrases: list[str],
) -> list[Locator]:
    labels = page.locator("label")
    results = []
    seen_ids = set()

    normalized_phrases = [
        normalize(p)
        for p in phrases
    ]

    try:
        count = labels.count()
    except Exception:
        return results

    for i in range(count):
        try:
            label = labels.nth(i)
            label_text = normalize(label.inner_text())

            if not any(
                phrase in label_text
                for phrase in normalized_phrases
            ):
                continue

            target = field_for_label(page, label)

            if target is None:
                continue

            target_id = (
                target.get_attribute("id")
                or f"anonymous-{i}"
            )

            if target_id not in seen_ids:
                results.append(target)
                seen_ids.add(target_id)

        except Exception:
            continue

    return results


def find_field_by_label_text(
    page: Page,
    phrases: list[str],
) -> Locator | None:
    fields = find_fields_by_label_text(
        page,
        phrases,
    )

    if fields:
        return fields[0]

    return None


def css_attr_value(value: str) -> str:
    """Return a safely quoted CSS attribute value."""

    value = str(value)
    value = value.replace("\\", "\\\\").replace("\"", "\\\"")
    return f'"{value}"'


def css_id_selector(value: str) -> str:
    """Build an ID selector that works even when the id starts with a digit."""

    return f"[id={css_attr_value(value)}]"


def field_for_label(
    page: Page,
    label: Locator,
) -> Locator | None:
    try:
        target_id = label.get_attribute("for")

        if target_id:
            target = page.locator(css_id_selector(target_id)).first

            if target.count():
                return target

    except Exception:
        pass

    try:
        parent = label.locator("xpath=..")
        possible = parent.locator(
            "input:not([type='hidden']), textarea, [role='combobox'], select"
        )

        if possible.count():
            return possible.first

    except Exception:
        pass

    try:
        grandparent = label.locator("xpath=../..")
        possible = grandparent.locator(
            "input:not([type='hidden']), textarea, [role='combobox'], select"
        )

        if possible.count():
            return possible.first

    except Exception:
        pass

    return None


def select_locator_smart(
    page: Page,
    field: Locator,
    variants: list[str],
    display_name: str,
) -> bool:
    try:
        selector_id = field.get_attribute("id")

        if selector_id:
            return select_react_smart(
                page,
                css_id_selector(selector_id),
                variants,
                display_name,
            )

    except Exception:
        pass

    return False


def select_question(
    page: Page,
    label_phrases: list[str],
    variants: list[str],
    display_name: str,
) -> bool:
    field = find_field_by_label_text(
        page,
        label_phrases,
    )

    if field is None:
        print(
            f"✗ {display_name}: question not found"
        )
        return False

    return select_locator_smart(
        page,
        field,
        variants,
        display_name,
    )


def select_all_matching_questions(
    page: Page,
    label_phrases: list[str],
    variants: list[str],
    display_name: str,
) -> int:
    fields = find_fields_by_label_text(
        page,
        label_phrases,
    )

    if not fields:
        print(
            f"✗ {display_name}: question not found"
        )
        return 0

    completed = 0

    for index, field in enumerate(fields, start=1):
        name = display_name

        if len(fields) > 1:
            name = f"{display_name} #{index}"

        if select_locator_smart(
            page,
            field,
            variants,
            name,
        ):
            completed += 1

    return completed


def fill_question_text(
    page: Page,
    label_phrases: list[str],
    value: str,
    display_name: str,
) -> bool:
    field = find_field_by_label_text(
        page,
        label_phrases,
    )

    if field is None:
        print(
            f"✗ {display_name}: question not found"
        )
        return False

    return fill_locator_text(
        field,
        value,
        display_name,
        page=page,
    )


def fill_locator_text(
    field: Locator,
    value: str,
    display_name: str,
    *,
    page: Optional[Page] = None,
) -> bool:
    try:
        field.scroll_into_view_if_needed()
        field.fill(value)
        field.blur()

        if page is not None:
            page.wait_for_timeout(150)

        actual = field.input_value()

        if normalize(actual) == normalize(value):
            print(f"✓ {display_name}: {actual}")
            return True

        if value.strip() and actual.strip():
            print(f"✓ {display_name}: {actual}")
            return True

    except Exception as exc:
        print(f"✗ {display_name}: {exc}")

    return False


# ============================================================
# HOW DID YOU HEAR?
# ============================================================

def select_source_question(page: Page) -> bool:
    field = find_field_by_label_text(
        page,
        [
            "how did you hear about this opportunity",
            "how did you hear about appian",
            "how did you hear",
            "how did you find",
            "source",
        ],
    )

    if field is None:
        print("✗ How did you hear: question not found")
        return False

    preferences = [
        profile_value("how_heard", "Handshake"),
        "Handshake",
        "Handshake Job Board",
        "University",
        "School",
        "LinkedIn",
        "Other",
    ]

    try:
        selector_id = field.get_attribute("id")

        if selector_id:
            if select_react_smart(
                page,
                css_id_selector(selector_id),
                preferences,
                "How did you hear",
            ):
                return True

    except Exception:
        pass

    for preference in preferences:
        options = open_and_search(
            page,
            field,
            preference,
        )

        for index, text in options:
            option = normalize(text)
            wanted = normalize(preference)

            if wanted not in option:
                continue

            click_option(page, index, text)
            print(f"✓ How did you hear: {text}")

            if preference == "Other":
                page.wait_for_timeout(400)
                fill_other_source_followup(page, field)

            return True

    close_dropdown(page)
    print("✗ How did you hear: no supported source found")
    return False


def fill_other_source_followup(
    page: Page,
    original_field: Locator,
) -> bool:
    original_id = None

    try:
        original_id = original_field.get_attribute("id")
    except Exception:
        pass

    labels = page.locator("label")
    phrases = [
        "please specify",
        "please explain",
        "other source",
        "if other",
        "specify other",
    ]

    try:
        count = labels.count()
    except Exception:
        return False

    for i in range(count):
        try:
            label = labels.nth(i)
            text = normalize(label.inner_text())

            if not any(
                normalize(p) in text
                for p in phrases
            ):
                continue

            target = field_for_label(page, label)

            if target is None:
                continue

            target_id = target.get_attribute("id")

            if target_id and target_id == original_id:
                continue

            if target.count() and target.is_visible():
                target.fill("LinkedIn")
                target.blur()
                print("✓ Other source: LinkedIn")
                return True

        except Exception:
            continue

    return False


# ============================================================
# RESUME / FILE UPLOADS
# ============================================================

def upload_resume(page: Page) -> bool:
    resume = Path(PROFILE["resume"])

    if not resume.exists():
        print(f"✗ Resume not found: {resume}")
        return False

    try:
        upload = page.locator("#resume")

        if upload.count() == 0:
            print("✗ Resume upload field not found")
            return False

        upload.set_input_files(str(resume))
        page.wait_for_timeout(400)
        print(f"✓ Resume uploaded: {resume.name}")
        return True

    except Exception as exc:
        print(f"✗ Resume upload failed: {exc}")
        return False


def required_file_uploads_for_manual_review(page: Page) -> list[str]:
    manual = []
    labels = page.locator("label")

    try:
        count = labels.count()
    except Exception:
        return manual

    for i in range(count):
        try:
            label = labels.nth(i)
            raw_label = label.inner_text()

            if not label_is_required(raw_label):
                continue

            question = clean_label_text(raw_label)
            target = field_for_label(page, label)

            if target is None:
                continue

            input_type = (target.get_attribute("type") or "").lower()

            if input_type != "file":
                continue

            value = ""

            try:
                value = target.input_value()
            except Exception:
                pass

            if value:
                continue

            manual.append(question)

        except Exception:
            continue

    return manual


# ============================================================
# GENERALIZED PROFILE QUESTIONS
# ============================================================

def fill_general_profile_questions(page: Page) -> None:
    print("\n===== GENERAL PROFILE QUESTIONS =====")

    fill_question_text(
        page,
        [
            "preferred first name",
            "preferred name",
        ],
        profile_value("preferred_first_name", profile_value("first_name")),
        "Preferred first name",
    )

    select_question(
        page,
        [
            "end date month",
            "graduation month",
            "expected graduation month",
        ],
        profile_list(
            "graduation_month_variants",
            [profile_value("graduation_month", "December")],
        ),
        "Graduation month",
    )

    select_question(
        page,
        [
            "end date year",
            "graduation year",
            "expected graduation year",
        ],
        profile_list(
            "graduation_year_variants",
            [profile_value("graduation_year", "2027")],
        ),
        "Graduation year",
    )

    # Important: do not use generic "2027" here. Some forms offer
    # Spring 2027 / Fall 2027 / December 2027, and year-only matching can
    # select the wrong term. If no exact month+year option exists, the
    # email fallback will ask you instead.
    select_question(
        page,
        [
            "anticipated graduation date",
            "expected graduation date",
            "expected graduation",
            "graduation date",
            "graduation month and year",
        ],
        graduation_variants_strict(),
        "Graduation date",
    )

    select_question(
        page,
        [
            "willing and able to accommodate this work environment",
            "willing and able to work",
            "willing to work onsite",
            "willing to work on site",
            "able to work onsite",
            "able to work on site",
            "in office",
            "work environment",
        ],
        profile_list(
            "onsite_willing_variants",
            [profile_value("onsite_willing", "Yes")],
        ),
        "Onsite / office requirement",
    )

    select_question(
        page,
        [
            "country of residence",
            "country do you currently reside",
            "country in which you reside",
        ],
        profile_list(
            "country_variants",
            [
                profile_value("country", "United States"),
                "United States of America",
                "USA",
                "US",
            ],
        ),
        "Country of residence",
    )

    select_all_matching_questions(
        page,
        [
            "eligible to work in the country where this vacancy is posted",
            "eligible to work in the country",
            "legally authorized to work",
            "currently authorized to work",
            "authorized to work",
            "work authorization",
        ],
        profile_list(
            "authorized_us_variants",
            [profile_value("authorized_us", "Yes")],
        ),
        "Work eligibility",
    )

    select_all_matching_questions(
        page,
        [
            "require company sponsorship",
            "require sponsorship",
            "future require sponsorship",
            "future require",
            "employment based visa status",
            "employment-based visa status",
            "visa sponsorship",
            "sponsorship",
            "file a petition",
            "application for employment based visa",
            "application for employment-based visa",
        ],
        profile_list(
            "sponsorship_variants",
            [profile_value("sponsorship", "No")],
        ),
        "Requires sponsorship",
    )

    fill_question_text(
        page,
        [
            "zip code of your primary residence",
            "zip code",
            "postal code",
        ],
        profile_value("zip_code", ""),
        "ZIP code",
    )

    select_question(
        page,
        [
            "state in which you currently reside",
            "state do you currently reside",
            "state of residence",
            "current state of residence",
        ],
        profile_list(
            "state_variants",
            [
                profile_value("state_full", "California"),
                profile_value("state", "CA"),
            ],
        ),
        "State of residence",
    )

    select_question(
        page,
        [
            "previously worked for",
            "previously been employed by",
            "worked for us before",
            "previous employee",
            "former employee",
        ],
        profile_list(
            "previously_worked_variants",
            [profile_value("previously_worked_for_company", "No")],
        ),
        "Previous employment with company",
    )

    select_question(
        page,
        [
            "currently own operate or provide services",
            "own operate or provide services",
            "other business or organization",
            "consultancy freelance",
            "outside business activity",
            "outside employment",
        ],
        profile_list(
            "outside_business_activity_variants",
            [profile_value("outside_business_activity", "No")],
        ),
        "Outside business activity",
    )

    select_question(
        page,
        [
            "agree to be a part of the talent community",
            "part of the talent community",
            "join our talent community",
            "future career opportunities",
        ],
        profile_list(
            "talent_community_variants",
            [profile_value("talent_community", "Yes")],
        ),
        "Talent community",
    )

    fill_question_text(
        page,
        [
            "linkedin profile",
            "linkedin url",
            "linkedin",
        ],
        profile_value("linkedin", ""),
        "LinkedIn",
    )


# ============================================================
# VOLUNTARY SELF-ID
# ============================================================

def fill_self_identification(page: Page) -> None:
    print("\n===== VOLUNTARY SELF-IDENTIFICATION =====")

    select_question(
        page,
        [
            "gender",
            "what is your gender",
        ],
        profile_list(
            "gender_variants",
            [profile_value("gender", "Male")],
        ),
        "Gender",
    )

    select_question(
        page,
        [
            "are you hispanic/latino",
            "are you hispanic or latino",
            "hispanic/latino",
            "hispanic or latino",
        ],
        profile_list(
            "hispanic_latino_variants",
            [profile_value("hispanic_latino", "Yes")],
        ),
        "Hispanic/Latino",
    )

    select_question(
        page,
        [
            "veteran status",
            "protected veteran",
            "veteran",
        ],
        profile_list(
            "veteran_status_variants",
            [profile_value("veteran_status", "Not a veteran")],
        ),
        "Veteran status",
    )


# ============================================================
# EMAIL FALLBACK FOR GREENHOUSE REQUIRED QUESTIONS
# ============================================================

def get_page_title(page: Page) -> str:
    try:
        title = page.title().strip()

        if title:
            return title

    except Exception:
        pass

    try:
        h1 = page.locator("h1").first

        if h1.count():
            text = h1.inner_text().strip()

            if text:
                return text

    except Exception:
        pass

    return "Greenhouse application"


def get_company_from_title(page: Page) -> str:
    title = get_page_title(page)

    match = re.search(r" at (.+)$", title, flags=re.I)

    if match:
        return match.group(1).strip()

    return "Greenhouse"


def current_field_value(field: Locator) -> str:
    values = []

    for attr in [
        "value",
        "aria-valuetext",
        "aria-label",
        "title",
    ]:
        try:
            value = field.get_attribute(attr)

            if value:
                values.append(value)
        except Exception:
            pass

    try:
        value = field.input_value()

        if value:
            values.append(value)
    except Exception:
        pass

    try:
        text = field.inner_text().strip()

        if text:
            values.append(text)
    except Exception:
        pass

    combined = " ".join(values)
    combined = re.sub(r"\s+", " ", combined).strip()

    return combined


def field_is_answered(field: Locator) -> bool:
    try:
        tag = (field.evaluate("el => el.tagName") or "").lower()
    except Exception:
        tag = ""

    try:
        input_type = (field.get_attribute("type") or "").lower()
    except Exception:
        input_type = ""

    if input_type in {"checkbox", "radio"}:
        try:
            return bool(field.is_checked())
        except Exception:
            return False

    value = current_field_value(field)
    normalized = normalize(value)

    if not normalized:
        return False

    blank_markers = {
        "select",
        "select one",
        "select an option",
        "choose",
        "choose one",
        "please select",
        "no file chosen",
    }

    return normalized not in blank_markers


def should_skip_email_question(question: str) -> bool:
    normalized = normalize(question)

    if not normalized:
        return True

    skip_phrases = [
        "indicates a required field",
        "powered by",
        "recaptcha",
        "captcha",
        "privacy policy",
        "privacy notice",
        "candidate privacy",
        "consent",
        "attestation",
        "certify",
        "signature",
        "terms",
        "agreement",
        "authorization to contact",
    ]

    if any(phrase in normalized for phrase in skip_phrases):
        return True

    # These are Greenhouse built-in profile fields that the deterministic
    # filler already handles earlier. Some Greenhouse React widgets expose
    # their hidden inputs as blank even after the visible dropdown has been
    # filled, which caused duplicate email questions for Country, Location,
    # School, and Degree. Leave any remaining problem visible for final manual
    # review instead of emailing repeatedly for fields we already attempted.
    built_in_profile_questions = {
        "country",
        "country code",
        "location city",
        "location",
        "school",
        "degree",
        "first name",
        "last name",
        "email",
        "phone",
        "resume",
    }

    if normalized in built_in_profile_questions:
        return True

    return False


def options_from_dropdown(
    page: Page,
    field: Locator,
) -> list[str]:
    options_seen = []

    try:
        selector_id = field.get_attribute("id")
    except Exception:
        selector_id = None

    searches = ["", "yes", "no", "a", "1"]

    for search in searches:
        try:
            if selector_id:
                live_field = page.locator(css_id_selector(selector_id)).first
            else:
                live_field = field

            options = open_and_search(
                page,
                live_field,
                search,
            )

            for _, text in options:
                text = text.strip()

                if not text:
                    continue

                if normalize(text) in {
                    "select",
                    "select one",
                    "please select",
                }:
                    continue

                if text not in options_seen:
                    options_seen.append(text)

        except Exception:
            continue

    close_dropdown(page)
    return options_seen


def options_from_radio_or_checkbox_group(label: Locator) -> list[str]:
    options = []

    for scope_query in ["xpath=..", "xpath=../..", "xpath=../../.."]:
        try:
            scope = label.locator(scope_query)
            labels = scope.locator("label")
            count = labels.count()

            for i in range(count):
                text = clean_label_text(labels.nth(i).inner_text())

                if not text:
                    continue

                if text not in options:
                    options.append(text)

        except Exception:
            continue

    return options


def click_radio_or_checkbox_option(
    label: Locator,
    answer: str,
) -> bool:
    normalized_answer = normalize(answer)

    for scope_query in ["xpath=..", "xpath=../..", "xpath=../../.."]:
        try:
            scope = label.locator(scope_query)
            labels = scope.locator("label")
            count = labels.count()

            for i in range(count):
                option_label = labels.nth(i)
                text = clean_label_text(option_label.inner_text())

                if not text:
                    continue

                if normalize(text) != normalized_answer:
                    continue

                try:
                    option_label.click()
                except Exception:
                    option_label.click(force=True)

                return True

        except Exception:
            continue

    return False


def ask_question_by_email(
    page: Page,
    question: str,
    options: Optional[list[str]] = None,
) -> Optional[str]:
    company = get_company_from_title(page)
    title = get_page_title(page)

    if ask_application_question is None:
        print("  ⚠ Email helper unavailable; leaving for manual review")
        return None

    return ask_application_question(
        company=company,
        title=title,
        question=question,
        options=options or [],
    )


def fill_required_greenhouse_question(
    page: Page,
    label: Locator,
    field: Locator,
    question: str,
) -> bool:
    try:
        input_type = (field.get_attribute("type") or "").lower()
    except Exception:
        input_type = ""

    try:
        role = (field.get_attribute("role") or "").lower()
    except Exception:
        role = ""

    try:
        tag = (field.evaluate("el => el.tagName") or "").lower()
    except Exception:
        tag = ""

    if input_type == "file":
        print(f"  ⚠ Required file upload left for manual review: {question}")
        return False

    print("  Found unanswered required Greenhouse question:")
    print(f"    {question}")

    if input_type in {"radio", "checkbox"}:
        options = options_from_radio_or_checkbox_group(label)
        answer = ask_question_by_email(page, question, options)

        if not answer:
            print("  ⚠ No answer available; leaving this question blank")
            return False

        if click_radio_or_checkbox_option(label, answer):
            print(f"  ✓ Selected answer: {answer}")
            return True

        print("  ⚠ Could not click matching radio/checkbox option")
        return False

    if role == "combobox" or tag == "select":
        options = options_from_dropdown(page, field)
        answer = ask_question_by_email(page, question, options)

        if not answer:
            print("  ⚠ No answer available; leaving this question blank")
            return False

        if select_locator_smart(page, field, [answer], question):
            print(f"  ✓ Selected answer: {answer}")
            return True

        print("  ⚠ Could not select matching dropdown option")
        return False

    answer = None

    # First try the short-answer agent for open-ended prompts. This avoids
    # emailing a blank question and instead drafts a completed response from
    # the applicant profile, applicant_brief.md, and visible job/page context.
    try:
        from src.short_answer_agent import draft_short_answer_for_field

        draft_result = draft_short_answer_for_field(
            page=page,
            company=get_company_from_title(page),
            title=get_page_title(page),
            question=question,
            source="greenhouse",
        )

        if draft_result.get("status") == "use" and draft_result.get("answer"):
            answer = str(draft_result["answer"]).strip()
        elif draft_result.get("status") == "stop":
            print("  ⚠ Short-answer draft stopped for manual review")
            return False
        else:
            reason = draft_result.get("reason") or "short-answer agent unavailable"
            print(f"  ⚠ Short-answer agent did not draft this field: {reason}")

    except Exception as exc:
        print(f"  ⚠ Short-answer agent failed safely: {exc}")

    if not answer:
        answer = ask_question_by_email(page, question, [])

    if not answer:
        print("  ⚠ No answer available; leaving this question blank")
        return False

    if fill_locator_text(field, answer, question, page=page):
        print("  ✓ Filled text answer")
        return True

    return False


def email_unanswered_required_greenhouse_questions(page: Page) -> None:
    print("\n===== GREENHOUSE EMAIL FALLBACK =====")

    labels = page.locator("label")
    asked_questions = set()
    asked_count = 0

    manual_uploads = required_file_uploads_for_manual_review(page)

    for question in manual_uploads:
        print(f"⚠ Required upload still manual: {question}")

    try:
        count = labels.count()
    except Exception:
        print("⚠ Could not inspect Greenhouse labels")
        return

    for i in range(count):
        try:
            label = labels.nth(i)
            raw_label = label.inner_text()

            if not label_is_required(raw_label):
                continue

            question = clean_label_text(raw_label)
            normalized_question = normalize(question)

            if not normalized_question:
                continue

            if normalized_question in asked_questions:
                continue

            if should_skip_email_question(question):
                continue

            field = field_for_label(page, label)

            if field is None:
                continue

            if field_is_answered(field):
                continue

            filled = fill_required_greenhouse_question(
                page,
                label,
                field,
                question,
            )

            asked_questions.add(normalized_question)

            if filled:
                asked_count += 1

        except Exception as exc:
            print(f"⚠ Could not inspect required question: {exc}")
            continue

    if asked_count == 0:
        print("No additional Greenhouse questions were filled by email.")
    else:
        print(f"✓ Email-filled Greenhouse questions: {asked_count}")


def run_application_agent_analysis(page: Page) -> None:
    """
    Analyze-only LLM pass.

    This prints what the agent thinks about the page, but it does not click,
    fill, email, or submit anything. The deterministic filler and email
    fallback above remain the only code that mutates the form.
    """

    if analyze_and_print_application_page is None:
        print("\n===== APPLICATION AGENT ANALYSIS =====")
        print("Application agent is unavailable. Make sure src/application_agent.py exists.")
        return

    try:
        analyze_and_print_application_page(
            page,
            company=get_company_from_title(page),
            title=get_page_title(page),
        )

    except Exception as exc:
        print("\n===== APPLICATION AGENT ANALYSIS =====")
        print(f"⚠ Application agent failed safely: {exc}")


# ============================================================
# APPLICATION
# ============================================================

def fill_greenhouse_application(page: Page) -> None:
    print("\n===== GREENHOUSE AUTOFILL V9 =====\n")

    # --------------------------------------------------------
    # CONTACT
    # --------------------------------------------------------

    fill_text(page, "#first_name", profile_value("first_name"), "First name")
    fill_text(page, "#last_name", profile_value("last_name"), "Last name")
    fill_text(page, "#email", profile_value("email"), "Email")

    select_react_smart(
        page,
        "#country",
        profile_list(
            "country_variants",
            [
                profile_value("country", "United States"),
                "United States of America",
                "USA",
                "US",
            ],
        ),
        "Country",
    )

    fill_text(
        page,
        "#phone",
        profile_value("phone"),
        "Phone",
        phone=True,
    )

    # --------------------------------------------------------
    # LOCATION
    # --------------------------------------------------------

    select_react_smart(
        page,
        "#candidate-location",
        profile_list(
            "location_variants",
            [
                f"{profile_value('city')}, {profile_value('state_full', profile_value('state'))}, {profile_value('country')}",
                f"{profile_value('city')}, {profile_value('state')}",
                profile_value("city"),
            ],
        ),
        "Location",
    )

    # --------------------------------------------------------
    # RESUME
    # --------------------------------------------------------

    upload_resume(page)

    # --------------------------------------------------------
    # EDUCATION
    # --------------------------------------------------------

    select_react_smart(
        page,
        "#school--0",
        profile_list(
            "school_variants",
            [profile_value("school")],
        ),
        "School",
    )

    select_react_smart(
        page,
        "#degree--0",
        profile_list(
            "degree_variants",
            [profile_value("degree")],
        ),
        "Degree",
    )

    select_react_smart(
        page,
        "#discipline--0",
        [
            profile_value("major"),
            "Computer Science",
            "Electrical Engineering and Computer Sciences",
            "Computer Engineering",
        ],
        "Discipline",
    )

    # --------------------------------------------------------
    # EMPLOYER-SPECIFIC BUT REUSABLE QUESTIONS
    # --------------------------------------------------------

    select_question(
        page,
        [
            "what archetype are you most closely aligned with",
            "archetype",
            "specialization",
            "discipline",
        ],
        [
            profile_value("archetype", "Machine Learning"),
            "Machine Learning",
            "ML",
        ],
        "Archetype",
    )

    fill_question_text(
        page,
        [
            "what school are you currently attending",
            "school are you currently attending",
            "current school",
        ],
        profile_value("school"),
        "Current school",
    )

    fill_general_profile_questions(page)

    # --------------------------------------------------------
    # SOURCE
    # --------------------------------------------------------

    select_source_question(page)

    # --------------------------------------------------------
    # VOLUNTARY SELF-ID
    # --------------------------------------------------------

    fill_self_identification(page)

    # --------------------------------------------------------
    # APPLICATION AGENT ANALYSIS
    #
    # Analyze-only. This does not click, fill, email, or submit.
    # Run this before email fallback so local tests can verify the agent
    # without getting stuck waiting for an email reply first.
    # --------------------------------------------------------

    run_application_agent_analysis(page)

    # --------------------------------------------------------
    # EMAIL FALLBACK FOR REQUIRED GREENHOUSE QUESTIONS
    # --------------------------------------------------------

    email_unanswered_required_greenhouse_questions(page)

    # --------------------------------------------------------
    # FINAL CHECK
    # --------------------------------------------------------

    print("\n===== FINAL TEXT-FIELD CHECK =====")

    verification_fields = [
        ("First name", "#first_name"),
        ("Last name", "#last_name"),
        ("Email", "#email"),
        ("Phone", "#phone"),
    ]

    for name, selector in verification_fields:
        try:
            field = page.locator(selector).first

            if not field.count():
                continue

            value = field.input_value()

            if value.strip():
                print(f"✓ {name} retained: {value}")
            else:
                print(f"✗ {name} IS EMPTY")

        except Exception as exc:
            print(f"⚠ Could not verify {name}: {exc}")

    # --------------------------------------------------------
    # MANUAL REVIEW
    # --------------------------------------------------------

    print("\n===== LEFT FOR MANUAL REVIEW =====")
    print("• Required file uploads that are not configured, such as transcripts")
    print("• Required consent / attestation checkboxes")
    print("• Questions you replied Skip/manual review to by email")
    print("• Human verification / CAPTCHA")
    print("• Anything that still looks blank or incorrect")
    print("\n🚫 SUBMIT BUTTON NOT TOUCHED")


# ---------------------------------------------------------------------
# GREENHOUSE SUBMIT-TO-VERIFICATION EMAIL-CODE FLOW
# ---------------------------------------------------------------------
# This keeps final human control by requiring you to reply with the
# Greenhouse verification code before the final submission is completed.

def _gh_env_true(name: str, default: str = "false") -> bool:
    import os
    return str(os.getenv(name, default)).strip().lower() in {"1", "true", "yes", "y", "on"}


def _gh_clean_code(text: str) -> str | None:
    import re

    text = str(text or "").strip()
    match = re.search(r"\b[A-Za-z0-9]{8}\b", text)
    if not match:
        compact = re.sub(r"[^A-Za-z0-9]", "", text)
        if len(compact) == 8:
            return compact
        return None

    return match.group(0)


def _greenhouse_fill_outside_business_na(page) -> bool:
    js = r"""
    () => {
      const norm = s => (s || "").replace(/\s+/g, " ").trim();

      function visible(el) {
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== "none" &&
               style.visibility !== "hidden" &&
               rect.width > 0 &&
               rect.height > 0;
      }

      function labelFor(el) {
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

        const container = el.closest("div, fieldset, section");
        if (container) parts.push(container.innerText || container.textContent || "");

        return norm(parts.filter(Boolean).join(" "));
      }

      function setValue(el, value) {
        const setter = Object.getOwnPropertyDescriptor(el.constructor.prototype, "value")?.set;
        if (setter) setter.call(el, value);
        else el.value = value;

        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
        el.dispatchEvent(new Event("blur", { bubbles: true }));
      }

      const value = "N/A - I do not currently own, operate, or provide services to any other business or organization.";

      for (const textarea of Array.from(document.querySelectorAll("textarea"))) {
        if (!visible(textarea)) continue;
        if (norm(textarea.value)) continue;

        const label = labelFor(textarea).toLowerCase();

        if (
          label.includes("if yes") &&
          label.includes("describe") &&
          (
            label.includes("nature of the activity") ||
            label.includes("your role") ||
            label.includes("responsibilities or interests of veeam") ||
            label.includes("overlap with the responsibilities")
          )
        ) {
          setValue(textarea, value);
          return true;
        }
      }

      return false;
    }
    """

    try:
        filled = bool(page.evaluate(js))
        if filled:
            print("✓ Conditional outside-business textarea filled: N/A")
        return filled
    except Exception as exc:
        print(f"⚠ Could not fill outside-business N/A textarea: {exc}")
        return False


def _greenhouse_check_required_consent_boxes(page) -> int:
    js = r"""
    () => {
      const norm = s => (s || "").replace(/\s+/g, " ").trim();

      function visible(el) {
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== "none" &&
               style.visibility !== "hidden" &&
               rect.width > 0 &&
               rect.height > 0;
      }

      function labelFor(el) {
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

        const container = el.closest("div, fieldset, section");
        if (container) parts.push(container.innerText || container.textContent || "");

        return norm(parts.filter(Boolean).join(" "));
      }

      let clicked = 0;

      for (const cb of Array.from(document.querySelectorAll('input[type="checkbox"]'))) {
        if (!visible(cb)) continue;
        if (cb.checked) continue;

        const label = labelFor(cb).toLowerCase();

        const looksLikeRequiredDataConsent =
          (
            label.includes("store and process my data") ||
            label.includes("process my data") ||
            label.includes("data processing") ||
            label.includes("considering my eligibility regarding my current application")
          ) &&
          !label.includes("talent community") &&
          !label.includes("future career opportunities");

        if (looksLikeRequiredDataConsent) {
          cb.click();
          cb.dispatchEvent(new Event("input", { bubbles: true }));
          cb.dispatchEvent(new Event("change", { bubbles: true }));
          clicked += 1;
        }
      }

      return clicked;
    }
    """

    try:
        count = int(page.evaluate(js) or 0)
        if count:
            print(f"✓ Checked required data-processing consent checkbox(es): {count}")
        else:
            print("⚠ No required data-processing consent checkbox was checked.")
        return count
    except Exception as exc:
        print(f"⚠ Could not check consent checkbox: {exc}")
        return 0


def _greenhouse_collect_review_summary(page) -> str:
    js = r"""
    () => {
      const norm = s => (s || "").replace(/\s+/g, " ").trim();

      function visible(el) {
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== "none" &&
               style.visibility !== "hidden" &&
               rect.width > 0 &&
               rect.height > 0;
      }

      function labelFor(el) {
        const parts = [];
        const aria = el.getAttribute("aria-label");
        if (aria) parts.push(aria);

        const placeholder = el.getAttribute("placeholder");
        if (placeholder) parts.push(placeholder);

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

        const container = el.closest("div, fieldset, section");
        if (container) {
          const text = norm(container.innerText || container.textContent || "");
          if (text && text.length < 700) parts.push(text);
        }

        return norm(parts.filter(Boolean).join(" | ")).slice(0, 350);
      }

      function optionText(el) {
        const id = el.getAttribute("id");
        const parts = [];

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
        return norm(parts.filter(Boolean).join(" "));
      }

      const responses = [];
      const manual = [];
      const seenGroups = new Set();

      for (const el of Array.from(document.querySelectorAll("input, textarea, select"))) {
        if (!visible(el)) continue;

        const tag = el.tagName.toLowerCase();
        const type = (el.getAttribute("type") || tag).toLowerCase();

        if (["hidden", "submit", "button", "file"].includes(type)) continue;

        const name = el.getAttribute("name") || "";
        const label = labelFor(el);
        const required = !!el.required || label.includes("*") || el.getAttribute("aria-required") === "true";

        if (type === "radio" && name) {
          const key = "radio:" + name;
          if (seenGroups.has(key)) continue;
          seenGroups.add(key);

          const group = Array.from(document.querySelectorAll('input[type="radio"]'))
            .filter(x => (x.getAttribute("name") || "") === name)
            .filter(visible);

          const checked = group.find(x => x.checked);
          const value = checked ? optionText(checked) : "";

          responses.push({ label, value, required });

          if (required && !value) {
            manual.push(label);
          }

          continue;
        }

        if (type === "checkbox") {
          const checked = el.checked ? "Checked" : "Unchecked";
          responses.push({ label, value: checked, required });

          if (required && !el.checked) {
            manual.push(label);
          }

          continue;
        }

        if (tag === "select") {
          const  el.options && el.selectedIndex >= 0
            ? norm(el.options[el.selectedIndex].textContent || el.value || "")
            : norm(el.value || "");

          responses.push({ label, value: selected, required });

          if (required && !selected) {
            manual.push(label);
          }

          continue;
        }

        const value = norm(el.value || "");
        responses.push({ label, value, required });

        if (required && !value) {
          manual.push(label);
        }
      }

      return {
        title: document.title,
        url: window.location.href,
        responses,
        manual
      };
    }
    """

    try:
        data = page.evaluate(js) or {}
    except Exception as exc:
        return f"Could not collect review summary: {exc}"

    lines = []
    lines.append("GREENHOUSE APPLICATION REVIEW SUMMARY")
    lines.append("")
    lines.append(f"Title: {data.get('title', '')}")
    lines.append(f"URL: {data.get('url', '')}")
    lines.append("")
    lines.append("Filled / selected responses:")

    responses = data.get("responses") or []
    for item in responses[:80]:
        label = str(item.get("label") or "Unknown field").strip()
        value = str(item.get("value") or "").strip()
        required = "required" if item.get("required") else "optional"

        if value:
            lines.append(f"- [{required}] {label}: {value}")
        else:
            lines.append(f"- [{required}] {label}: BLANK")

    manual = data.get("manual") or []
    lines.append("")
    lines.append("Blank / manual-review items detected:")
    if manual:
        for item in manual[:40]:
            lines.append(f"- {item}")
    else:
        lines.append("- None detected by DOM scan.")

    lines.append("")
    lines.append("Reply with the 8-character Greenhouse verification code to complete final submission.")
    lines.append("Reply STOP to leave the application open and not submit.")

    return "\n".join(lines)


def _greenhouse_email_and_wait_for_reply(subject: str, body: str) -> str | None:
    import os
    import time
    import uuid
    import smtplib
    import imaplib
    import email
    from email.mime.text import MIMEText
    from email.header import decode_header
    from datetime import datetime

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass

    bot_email = os.getenv("BOT_EMAIL", "").strip()
    app_password = os.getenv("BOT_EMAIL_APP_PASSWORD", "").strip()
    notify_email = os.getenv("NOTIFY_EMAIL", "").strip() or bot_email

    timeout = int(os.getenv("GREENHOUSE_SECURITY_CODE_TIMEOUT_SECONDS", "900"))
    poll = int(os.getenv("GREENHOUSE_SECURITY_CODE_POLL_SECONDS", "10"))

    if not bot_email or not app_password or not notify_email:
        print("⚠ Email is not configured. Falling back to terminal input.")
        return input("Paste the 8-character Greenhouse verification code, or STOP: ").strip()

    token = uuid.uuid4().hex[:8].upper()
    full_subject = f"{subject} [{token}]"

    msg = MIMEText(body + f"\n\nTracking token: {token}", "plain", "utf-8")
    msg["Subject"] = full_subject
    msg["From"] = bot_email
    msg["To"] = notify_email

    print(f"Sending verification-code request email to {notify_email}...")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(bot_email, app_password)
        smtp.send_message(msg)

    print("Waiting for your email reply with the 8-character code...")

    def decode_subject(raw_subject):
        if not raw_subject:
            return ""
        decoded_parts = decode_header(raw_subject)
        parts = []
        for value, enc in decoded_parts:
            if isinstance(value, bytes):
                parts.append(value.decode(enc or "utf-8", errors="replace"))
            else:
                parts.append(value)
        return "".join(parts)

    def extract_body(message):
        parts = []

        if message.is_multipart():
            for part in message.walk():
                ctype = part.get_content_type()
                disp = str(part.get("Content-Disposition") or "").lower()

                if ctype == "text/plain" and "attachment" not in disp:
                    payload = part.get_payload(decode=True)
                    if payload:
                        parts.append(payload.decode(part.get_content_charset() or "utf-8", errors="replace"))
        else:
            payload = message.get_payload(decode=True)
            if payload:
                parts.append(payload.decode(message.get_content_charset() or "utf-8", errors="replace"))

        text = "\n".join(parts).strip()

        # Keep only the fresh reply above quoted history when possible.
        cleaned_lines = []
        for line in text.splitlines():
            low = line.strip().lower()

            if low.startswith("on ") and "wrote:" in low:
                break
            if low.startswith(">"):
                continue
            if "tracking token:" in low:
                continue

            cleaned_lines.append(line)

        return "\n".join(cleaned_lines).strip()

    deadline = time.time() + timeout
    since = datetime.now().strftime("%d-%b-%Y")

    while time.time() < deadline:
        try:
            with imaplib.IMAP4_SSL("imap.gmail.com") as imap:
                imap.login(bot_email, app_password)
                imap.select("INBOX")

                status, data = imap.search(None, "SINCE", since)
                if status != "OK":
                    time.sleep(poll)
                    continue

                ids = data[0].split()[-50:]

                for msg_id in reversed(ids):
                    status, msg_data = imap.fetch(msg_id, "(RFC822)")
                    if status != "OK" or not msg_data or not msg_data[0]:
                        continue

                    raw = msg_data[0][1]
                    message = email.message_from_bytes(raw)

                    subj = decode_subject(message.get("Subject", ""))
                    body_text = extract_body(message)

                    if token in subj or token in body_text:
                        return body_text.strip()

        except Exception as exc:
            print(f"⚠ Email polling issue: {exc}")

        time.sleep(poll)

    print("⚠ Timed out waiting for verification-code email reply.")
    return None


def _greenhouse_click_submit_application(page) -> bool:
    js = r"""
    () => {
      function visible(el) {
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== "none" &&
               style.visibility !== "hidden" &&
               rect.width > 0 &&
               rect.height > 0;
      }

      const candidates = Array.from(document.querySelectorAll("button, input[type='submit']"))
        .filter(visible)
        .filter(el => {
          const text = ((el.innerText || el.textContent || el.value || "") + "").trim().toLowerCase();
          return text.includes("submit application") || text === "submit";
        });

      if (!candidates.length) {
        return false;
      }

      const button = candidates[candidates.length - 1];
      button.scrollIntoView({ block: "center" });
      button.click();
      return true;
    }
    """

    try:
        clicked = bool(page.evaluate(js))
        if clicked:
            print("✓ Clicked Submit application")
        else:
            print("⚠ Submit application button not found")
        return clicked
    except Exception as exc:
        print(f"⚠ Could not click Submit application: {exc}")
        return False


def _greenhouse_wait_for_security_code_page(page) -> bool:
    try:
        page.wait_for_function(
            """
            () => {
              const text = (document.body?.innerText || "").toLowerCase();
              return (
                text.includes("verification code") ||
                text.includes("security code") ||
                text.includes("8-character code") ||
                text.includes("confirm you're human") ||
                text.includes("confirm you’re human")
              );
            }
            """,
            timeout=45000,
        )
        print("✓ Greenhouse verification-code page detected")
        return True
    except Exception:
        print("⚠ Verification-code page was not detected after submit click.")
        return False


def _greenhouse_fill_security_code(page, code: str) -> bool:
    js = r"""
    ({ code }) => {
      function visible(el) {
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== "none" &&
               style.visibility !== "hidden" &&
               rect.width > 0 &&
               rect.height > 0;
      }

      function setValue(el, value) {
        const setter = Object.getOwnPropertyDescriptor(el.constructor.prototype, "value")?.set;
        if (setter) setter.call(el, value);
        else el.value = value;

        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
        el.dispatchEvent(new Event("keyup", { bubbles: true }));
        el.dispatchEvent(new Event("blur", { bubbles: true }));
      }

      const inputs = Array.from(document.querySelectorAll("input"))
        .filter(visible)
        .filter(el => {
          const type = (el.getAttribute("type") || "text").toLowerCase();
          return !["hidden", "submit", "button", "checkbox", "radio", "file"].includes(type);
        });

      const singleCharInputs = inputs.filter(el => {
        const max = Number(el.getAttribute("maxlength") || "0");
        const w = el.getBoundingClientRect().width;
        return max === 1 || w < 120;
      });

      if (singleCharInputs.length >= code.length) {
        for (let i = 0; i < code.length; i++) {
          setValue(singleCharInputs[i], code[i]);
        }
        return true;
      }

      if (inputs.length) {
        setValue(inputs[0], code);
        return true;
      }

      return false;
    }
    """

    try:
        ok = bool(page.evaluate(js, {"code": code}))
        if ok:
            print("✓ Verification code filled")
        else:
            print("⚠ Could not find verification-code input")
        return ok
    except Exception as exc:
        print(f"⚠ Could not fill verification code: {exc}")
        return False


def _greenhouse_submit_to_verification_and_finish(page) -> None:
    if not _gh_env_true("GREENHOUSE_SUBMIT_TO_VERIFICATION", "false"):
        return

    print("\n===== GREENHOUSE EMAIL-CODE SUBMISSION LAYER =====")

    # Safe conditional cleanup before triggering validation.
    _greenhouse_fill_outside_business_na(page)

    summary = _greenhouse_collect_review_summary(page)

    if _gh_env_true("GREENHOUSE_AUTO_CHECK_REQUIRED_CONSENT", "false"):
        _greenhouse_check_required_consent_boxes(page)
    else:
        print("GREENHOUSE_AUTO_CHECK_REQUIRED_CONSENT is not enabled.")
        print("Leaving consent and submit manual.")
        return

    if not _greenhouse_click_submit_application(page):
        return

    if not _greenhouse_wait_for_security_code_page(page):
        print("Submit was clicked, but no verification-code page was detected.")
        print("Review the browser manually.")
        return

    reply = _greenhouse_email_and_wait_for_reply(
        subject="Resume Filler: Greenhouse verification code needed",
        body=summary,
    )

    if not reply:
        print("No verification code received. Leaving browser open.")
        return

    if reply.strip().upper().startswith("STOP"):
        print("Received STOP. Leaving browser open without final submission.")
        return

    code = _gh_clean_code(reply)
    if not code:
        print(f"Could not find an 8-character code in reply: {reply!r}")
        print("Leaving browser open.")
        return

    print(f"Received verification code: {code}")

    if not _greenhouse_fill_security_code(page, code):
        print("Leaving browser open for manual code entry.")
        return

    page.wait_for_timeout(1000)

    if not _greenhouse_click_submit_application(page):
        print("Code filled, but final submit button was not clicked.")
        return

    try:
        page.wait_for_timeout(5000)
    except Exception:
        pass

    print("✓ Final submit clicked after email-code confirmation.")


# Wrap existing Greenhouse filler.
if "_GREENHOUSE_ORIGINAL_FILL_GREENHOUSE_APPLICATION" not in globals():
    _GREENHOUSE_ORIGINAL_FILL_GREENHOUSE_APPLICATION = fill_greenhouse_application


def fill_greenhouse_application(page, *args, **kwargs):
    result = _GREENHOUSE_ORIGINAL_FILL_GREENHOUSE_APPLICATION(page, *args, **kwargs)
    _greenhouse_submit_to_verification_and_finish(page)
    return result


# ---------------------------------------------------------------------
# HOTFIX: safer Greenhouse review-summary collector
# ---------------------------------------------------------------------
# Overrides the previous _greenhouse_collect_review_summary implementation.
# Uses simpler JS so the email summary does not fail with a const syntax error.

def _greenhouse_collect_review_summary(page) -> str:
    js = r"""
    () => {
      function norm(s) {
        return (s || "").replace(/\s+/g, " ").trim();
      }

      function visible(el) {
        if (!el) return false;
        var style = window.getComputedStyle(el);
        var rect = el.getBoundingClientRect();
        return style.display !== "none" &&
               style.visibility !== "hidden" &&
               rect.width > 0 &&
               rect.height > 0;
      }

      function labelFor(el) {
        var parts = [];

        var aria = el.getAttribute("aria-label");
        if (aria) parts.push(aria);

        var placeholder = el.getAttribute("placeholder");
        if (placeholder) parts.push(placeholder);

        var id = el.getAttribute("id");
        if (id) {
          var labels = Array.from(document.querySelectorAll("label"));
          for (var i = 0; i < labels.length; i++) {
            if (labels[i].getAttribute("for") === id) {
              parts.push(labels[i].innerText || labels[i].textContent || "");
            }
          }
        }

        var wrap = el.closest("label");
        if (wrap) {
          parts.push(wrap.innerText || wrap.textContent || "");
        }

        var container = el.closest("div, fieldset, section");
        if (container) {
          var containerText = norm(container.innerText || container.textContent || "");
          if (containerText && containerText.length < 700) {
            parts.push(containerText);
          }
        }

        var out = norm(parts.filter(Boolean).join(" | "));
        if (!out) {
          out = norm(el.getAttribute("name") || el.getAttribute("id") || el.tagName || "Unknown field");
        }

        return out.slice(0, 350);
      }

      function optionText(el) {
        var parts = [];
        var id = el.getAttribute("id");

        if (id) {
          var labels = Array.from(document.querySelectorAll("label"));
          for (var i = 0; i < labels.length; i++) {
            if (labels[i].getAttribute("for") === id) {
              parts.push(labels[i].innerText || labels[i].textContent || "");
            }
          }
        }

        var wrap = el.closest("label");
        if (wrap) parts.push(wrap.innerText || wrap.textContent || "");

        var parent = el.parentElement;
        if (parent) parts.push(parent.innerText || parent.textContent || "");

        parts.push(el.value || "");
        return norm(parts.filter(Boolean).join(" "));
      }

      var responses = [];
      var manual = [];
      var seen = {};

      var controls = Array.from(document.querySelectorAll("input, textarea, select"));

      for (var c = 0; c < controls.length; c++) {
        var el = controls[c];
        if (!visible(el)) continue;

        var tag = el.tagName.toLowerCase();
        var type = (el.getAttribute("type") || tag).toLowerCase();

        if (type === "hidden" || type === "submit" || type === "button" || type === "file") {
          continue;
        }

        var name = el.getAttribute("name") || "";
        var label = labelFor(el);
        var required = !!el.required || label.indexOf("*") >= 0 || el.getAttribute("aria-required") === "true";
        var value = "";

        if (type === "radio" && name) {
          var key = "radio:" + name;
          if (seen[key]) continue;
          seen[key] = true;

          var group = Array.from(document.querySelectorAll('input[type="radio"]'));
          for (var r = 0; r < group.length; r++) {
            var radio = group[r];
            if ((radio.getAttribute("name") || "") === name && visible(radio) && radio.checked) {
              value = optionText(radio);
              break;
            }
          }

          responses.push({ label: label, value: value, required: required });
          if (required && !value) manual.push(label);
          continue;
        }

        if (type === "checkbox") {
          value = el.checked ? "Checked" : "Unchecked";
          responses.push({ label: label, value: value, required: required });
          if (required && !el.checked) manual.push(label);
          continue;
        }

        if (tag === "select") {
          if (el.options && el.selectedIndex >= 0) {
            value = norm(el.options[el.selectedIndex].textContent || el.value || "");
          } else {
            value = norm(el.value || "");
          }

          responses.push({ label: label, value: value, required: required });
          if (required && !value) manual.push(label);
          continue;
        }

        value = norm(el.value || "");
        responses.push({ label: label, value: value, required: required });
        if (required && !value) manual.push(label);
      }

      return {
        title: document.title || "",
        url: window.location.href || "",
        responses: responses,
        manual: manual
      };
    }
    """

    try:
        data = page.evaluate(js)
    except Exception as exc:
        try:
            body_text = page.locator("body").inner_text(timeout=3000)
        except Exception:
            body_text = ""

        return (
            "GREENHOUSE APPLICATION REVIEW SUMMARY\n\n"
            f"Could not collect structured field summary: {exc}\n\n"
            "Visible page text fallback:\n"
            f"{body_text[:4000]}\n\n"
            "Reply with the 8-character Greenhouse verification code to complete final submission.\n"
            "Reply STOP to leave the application open and not submit."
        )

    lines = []
    lines.append("GREENHOUSE APPLICATION REVIEW SUMMARY")
    lines.append("")
    lines.append(f"Title: {data.get('title', '')}")
    lines.append(f"URL: {data.get('url', '')}")
    lines.append("")
    lines.append("Filled / selected responses:")

    for item in (data.get("responses") or [])[:90]:
        label = str(item.get("label") or "Unknown field").strip()
        value = str(item.get("value") or "").strip()
        required = "required" if item.get("required") else "optional"

        if value:
            lines.append(f"- [{required}] {label}: {value}")
        else:
            lines.append(f"- [{required}] {label}: BLANK")

    lines.append("")
    lines.append("Blank / manual-review items detected:")

    manual = data.get("manual") or []
    if manual:
        for item in manual[:40]:
            lines.append(f"- {item}")
    else:
        lines.append("- None detected by DOM scan.")

    lines.append("")
    lines.append("Reply with the 8-character Greenhouse verification code to complete final submission.")
    lines.append("Reply STOP to leave the application open and not submit.")

    return "\n".join(lines)


# ---------------------------------------------------------------------
# HOTFIX: safe Greenhouse security-code input targeting
# ---------------------------------------------------------------------
# Overrides _greenhouse_fill_security_code so it only fills the actual
# 8-character verification-code boxes, not Greenhouse dropdown/search fields.

def _greenhouse_fill_security_code(page, code: str) -> bool:
    code = str(code or "").strip()
    if not code:
        print("⚠ Empty verification code.")
        return False

    js = r"""
    ({ code }) => {
      function norm(s) {
        return (s || "").replace(/\s+/g, " ").trim();
      }

      function visible(el) {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return (
          style.display !== "none" &&
          style.visibility !== "hidden" &&
          rect.width > 0 &&
          rect.height > 0
        );
      }

      function setValue(el, value) {
        const setter = Object.getOwnPropertyDescriptor(el.constructor.prototype, "value")?.set;
        if (setter) setter.call(el, value);
        else el.value = value;

        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
        el.dispatchEvent(new Event("keyup", { bubbles: true }));
        el.dispatchEvent(new Event("blur", { bubbles: true }));
      }

      function isUsableCodeInput(el) {
        if (!visible(el)) return false;

        const type = (el.getAttribute("type") || "text").toLowerCase();
        if (["hidden", "submit", "button", "checkbox", "radio", "file"].includes(type)) {
          return false;
        }

        const rect = el.getBoundingClientRect();
        const maxLength = Number(el.getAttribute("maxlength") || "0");

        // Verification boxes are usually single-character boxes.
        // Greenhouse dropdown search inputs may also be inputs, but they are
        // not visually clustered right after the "Security code" label.
        return maxLength === 1 || rect.width <= 130;
      }

      const allElements = Array.from(document.querySelectorAll("body *")).filter(visible);

      let securityLabel = null;

      for (const el of allElements) {
        const text = norm(el.innerText || el.textContent || "").toLowerCase();

        // Prefer the compact label, not the whole page/form.
        if (text === "security code" || text === "security code*") {
          securityLabel = el;
          break;
        }
      }

      if (!securityLabel) {
        for (const el of allElements) {
          const text = norm(el.innerText || el.textContent || "").toLowerCase();
          if (
            text.includes("security code") &&
            text.length < 120
          ) {
            securityLabel = el;
            break;
          }
        }
      }

      if (!securityLabel) {
        for (const el of allElements) {
          const text = norm(el.innerText || el.textContent || "").toLowerCase();
          if (
            text.includes("verification code") ||
            text.includes("8-character code") ||
            text.includes("confirm you're human") ||
            text.includes("confirm you’re human")
          ) {
            securityLabel = el;
            break;
          }
        }
      }

      if (!securityLabel) {
        return {
          ok: false,
          reason: "Could not find Security code / verification label."
        };
      }

      const labelRect = securityLabel.getBoundingClientRect();

      const candidates = Array.from(document.querySelectorAll("input"))
        .filter(isUsableCodeInput)
        .map(el => {
          const rect = el.getBoundingClientRect();
          return { el, rect };
        })
        .filter(item => {
          const r = item.rect;

          // Must be below the security-code label and close to it.
          const belowLabel = r.top >= labelRect.bottom - 20;
          const closeVertically = r.top <= labelRect.bottom + 260;

          // Must be reasonably aligned with the label/message area.
          const notFarLeft = r.left >= labelRect.left - 80;
          const notFarRight = r.left <= window.innerWidth - 20;

          return belowLabel && closeVertically && notFarLeft && notFarRight;
        })
        .sort((a, b) => {
          if (Math.abs(a.rect.top - b.rect.top) > 20) {
            return a.rect.top - b.rect.top;
          }
          return a.rect.left - b.rect.left;
        })
        .map(item => item.el);

      if (candidates.length >= code.length) {
        for (let i = 0; i < code.length; i++) {
          setValue(candidates[i], code[i]);
        }

        const combined = candidates
          .slice(0, code.length)
          .map(el => el.value || "")
          .join("");

        return {
          ok: combined.length === code.length,
          method: "clustered_single_character_inputs",
          filled: combined,
          count: candidates.length
        };
      }

      // Fallback: look only for a single input explicitly marked as code-related.
      const explicit = Array.from(document.querySelectorAll("input"))
        .filter(visible)
        .filter(el => {
          const attrs = [
            el.getAttribute("name"),
            el.getAttribute("id"),
            el.getAttribute("aria-label"),
            el.getAttribute("autocomplete"),
            el.getAttribute("placeholder")
          ].join(" ").toLowerCase();

          return (
            attrs.includes("code") ||
            attrs.includes("otp") ||
            attrs.includes("verification") ||
            attrs.includes("one-time")
          );
        });

      if (explicit.length === 1) {
        setValue(explicit[0], code);
        return {
          ok: true,
          method: "explicit_code_input"
        };
      }

      return {
        ok: false,
        reason: `Could not safely isolate code inputs. Candidate count=${candidates.length}, explicit count=${explicit.length}`
      };
    }
    """

    try:
        result = page.evaluate(js, {"code": code})

        if isinstance(result, dict) and result.get("ok"):
            print(f"✓ Verification code filled safely using {result.get('method')}")
            return True

        print(f"⚠ Could not safely fill verification code: {result}")
        return False

    except Exception as exc:
        print(f"⚠ Could not fill verification code safely: {exc}")
        return False


# ---------------------------------------------------------------------
# TRANSCRIPT UPLOAD SUPPORT
# ---------------------------------------------------------------------

def _greenhouse_upload_transcript_if_requested(page) -> bool:
    from pathlib import Path

    try:
        from src.profile import PROFILE
    except Exception:
        try:
            from profile import PROFILE
        except Exception:
            PROFILE = {}

    transcript_path = PROFILE.get("transcript")
    if not transcript_path:
        print("✗ Transcript upload requested but PROFILE['transcript'] is not configured.")
        return False

    transcript_path = Path(transcript_path).expanduser().resolve()

    if not transcript_path.exists():
        print(f"✗ Transcript file not found: {transcript_path}")
        return False

    js = r"""
    () => {
      function norm(s) {
        return (s || "").replace(/\s+/g, " ").trim().toLowerCase();
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

      function labelFor(input) {
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

        const container = input.closest("div, fieldset, section");
        if (container) {
          const text = container.innerText || container.textContent || "";
          if (text && text.length < 1000) parts.push(text);
        }

        return norm(parts.join(" "));
      }

      const inputs = Array.from(document.querySelectorAll('input[type="file"]'));
      const matches = [];

      for (const input of inputs) {
        const label = labelFor(input);

        if (
          label.includes("transcript") ||
          label.includes("academic record") ||
          label.includes("unofficial transcript") ||
          label.includes("official transcript")
        ) {
          input.setAttribute("data-transcript-upload-target", "true");
          matches.push(label);
        }
      }

      return matches;
    }
    """

    try:
        matches = page.evaluate(js) or []
    except Exception as exc:
        print(f"✗ Could not scan for transcript upload field: {exc}")
        return False

    if not matches:
        print("✗ Transcript upload field not found")
        return False

    try:
        locator = page.locator('input[type="file"][data-transcript-upload-target="true"]').first
        locator.set_input_files(str(transcript_path))
        print(f"✓ Transcript uploaded: {transcript_path.name}")
        return True
    except Exception as exc:
        print(f"✗ Could not upload transcript: {exc}")
        return False


# Wrap existing Greenhouse filler again so transcript upload runs before the
# submit-to-verification layer if transcript fields are present.
if "_GREENHOUSE_ORIGINAL_FILL_WITH_TRANSCRIPT_SUPPORT" not in globals():
    _GREENHOUSE_ORIGINAL_FILL_WITH_TRANSCRIPT_SUPPORT = fill_greenhouse_application


def fill_greenhouse_application(page, *args, **kwargs):
    result = _GREENHOUSE_ORIGINAL_FILL_WITH_TRANSCRIPT_SUPPORT(page, *args, **kwargs)
    _greenhouse_upload_transcript_if_requested(page)
    return result


# ---------------------------------------------------------------------
# TRANSCRIPT UPLOAD SUPPORT
# ---------------------------------------------------------------------

def _greenhouse_upload_transcript_if_requested(page) -> bool:
    from pathlib import Path

    try:
        from src.profile import PROFILE
    except Exception:
        try:
            from profile import PROFILE
        except Exception:
            PROFILE = {}

    transcript_path = PROFILE.get("transcript")
    if not transcript_path:
        print("✗ Transcript upload requested but PROFILE['transcript'] is not configured.")
        return False

    transcript_path = Path(transcript_path).expanduser().resolve()

    if not transcript_path.exists():
        print(f"✗ Transcript file not found: {transcript_path}")
        return False

    js = r"""
    () => {
      function norm(s) {
        return (s || "").replace(/\s+/g, " ").trim().toLowerCase();
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

      function labelFor(input) {
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

        const container = input.closest("div, fieldset, section");
        if (container) {
          const text = container.innerText || container.textContent || "";
          if (text && text.length000) parts.push(text);
        }

        return norm(parts.join(" "));
      }

      const inputs = Array.from(document.querySelectorAll('input[type="file"]'));
      const matches = [];

      for (const input of inputs) {
        const label = labelFor(input);

        if (
          label.includes("transcript") ||
          label.includes("academic record") ||
          label.includes("unofficial transcript") ||
          label.includes("official transcript")
        ) {
          input.setAttribute("data-transcript-upload-target", "true");
          matches.push(label);
        }
      }

      return matches;
    }
    """

    try:
        matches = page.evaluate(js) or []
    except Exception as exc:
        print(f"✗ Could not scan for transcript upload field: {exc}")
        return False

    if not matches:
        print("✗ Transcript upload field not found")
        return False

    try:
        locator = page.locator('input[type="file"][data-transcript-upload-target="true"]').first
        locator.set_input_files(str(transcript_path))
        print(f"✓ Transcript uploaded: {transcript_path.name}")
        return True
    except Exception as exc:
        print(f"✗ Could not upload transcript: {exc}")
        return False


# Wrap existing Greenhouse filler again so transcript upload runs before the
# submit-to-verification layer if transcript fields are present.
if "_GREENHOUSE_ORIGINAL_FILL_WITH_TRANSCRIPT_SUPPORT" not in globals():
    _GREENHOUSE_ORIGINAL_FILL_WITH_TRANSCRIPT_SUPPORT = fill_greenhouse_application


def fill_greenhouse_application(page, *args, **kwargs):
    result = _GREENHOUSE_ORIGINAL_FILL_WITH_TRANSCRIPT_SUPPORT(page, *args, **kwargs)
    _greenhouse_upload_transcript_if_requested(page)
    return result




def _verify_critical_immigration_answers(page: Page) -> None:
    """Fail closed on incorrect/unknown authorization and sponsorship selections.

    Only handles unambiguous questions: authorized to work and whether
    immigration sponsorship is required now or in the future. Runs after
    recovery, not before, so a recovery pass cannot silently undo the fix.
    """
    rules = (
        ("legally authorized to work", "Yes", "Work authorization"),
        ("will you now require immigration sponsorship", "No", "Sponsorship now"),
        ("will you in the future require immigration sponsorship", "No", "Future sponsorship"),
    )
    labels = page.locator("label")
    seen = set()
    for idx in range(labels.count()):
        label = labels.nth(idx)
        try:
            question = normalize(label.inner_text())
        except Exception:
            continue
        rule = next(((phrase, expected, title) for phrase, expected, title in rules
                     if normalize(phrase) in question), None)
        if rule is None:
            continue
        _, expected, title = rule
        field = field_for_label(page, label)
        if field is None:
            raise RuntimeError(f"{title}: could not locate form control; review manually")
        field_id = field.get_attribute("id") or str(idx)
        if field_id in seen:
            continue
        seen.add(field_id)

        # Deterministic correction, without asking a language model to pick Yes/No.
        if not select_locator_smart(page, field, [expected], f"Critical check: {title}"):
            raise RuntimeError(f"{title}: unable to set {expected}; review manually")

        # Read the browser's selected option, not the model's stated answer.
        actual = field.evaluate("""el => {
          if (el.tagName === 'SELECT') {
            return el.selectedOptions?.[0]?.textContent?.trim() || '';
          }
          if (el.getAttribute('role') === 'radio' || el.type === 'radio') {
            return el.checked ? (el.value || el.getAttribute('aria-label') || '') : '';
          }
          // React-select renders the selected value separately from its input.
          let node = el;
          for (let i = 0; i < 5 && node; i++, node = node.parentElement) {
            const selected = node.querySelector('[class*="singleValue"], [class*="SingleValue"], [data-testid*="single-value"]');
            if (selected) return selected.textContent.trim();
            if (node.tagName === 'SELECT') return node.selectedOptions?.[0]?.textContent?.trim() || '';
          }
          return el.value || '';
        }""")
        if normalize(str(actual)) != normalize(expected):
            raise RuntimeError(
                f"{title}: browser displays {actual!r}, expected {expected!r}; "
                "automatic submission blocked. Correct and review manually."
            )
        print(f"✓ Verified {title}: {actual}")


# ---------------------------------------------------------------------
# FINAL OVERRIDE: Greenhouse recovery-agent before email-code submit layer
# ---------------------------------------------------------------------
# This makes the order deterministic:
#   original Greenhouse filler -> recovery agent -> submit-to-verification.
# It bypasses older transcript wrappers that may run too late.

if "_GREENHOUSE_FILL_BASE_RECOVERY_AGENT" not in globals():
    _GREENHOUSE_FILL_BASE_RECOVERY_AGENT = (
        globals().get("_GREENHOUSE_ORIGINAL_FILL_GREENHOUSE_APPLICATION")
        or fill_greenhouse_application
    )


def fill_greenhouse_application(page, *args, **kwargs):
    result = _GREENHOUSE_FILL_BASE_RECOVERY_AGENT(page, *args, **kwargs)

    try:
        from src.recovery_agent import run_recovery_agent

        run_recovery_agent(
            page,
            context="greenhouse_after_fill_before_submit",
            company=get_company_from_title(page),
            title=get_page_title(page),
        )
    except Exception as exc:
        print(f"⚠ Recovery agent failed safely before Greenhouse submit layer: {exc}")

    # Run a final check after the recovery agent, before any submit attempt.
    # Do not swallow failures: incorrect eligibility answers must block submission.
    _verify_critical_immigration_answers(page)

    try:
        _greenhouse_submit_to_verification_and_finish(page)
    except Exception as exc:
        print(f"⚠ Greenhouse submit-to-verification layer failed safely: {exc}")

    return result
