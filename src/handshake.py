from __future__ import annotations

import os
import re
from dataclasses import dataclass, asdict
from typing import Optional
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from playwright.sync_api import Page

from src.email_helper import ask_application_question, normalize_reply_to_option
from src.profile import PROFILE

try:
    from src.choice_answer_agent import infer_choice_answer
except Exception:
    infer_choice_answer = None


HANDSHAKE_HOME = "https://app.joinhandshake.com"


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


# ============================================================
# DATA MODEL
# ============================================================

@dataclass
class HandshakeJob:
    title: str
    company: str
    handshake_url: str
    application_url: Optional[str] = None
    application_type: str = "unknown"
    tab_number: Optional[int] = None

    def to_dict(self) -> dict:
        return asdict(self)


# ============================================================
# BASIC HELPERS
# ============================================================

def normalize_space(text: str) -> str:
    return " ".join((text or "").split())


def hostname_for(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def is_handshake_url(url: str) -> bool:
    return "joinhandshake.com" in hostname_for(url)


def is_greenhouse_url(url: str) -> bool:
    return "greenhouse.io" in hostname_for(url)


def is_real_external_url(url: str) -> bool:
    if not url:
        return False

    lower = url.lower().strip()

    if lower in {"about:blank", "about:srcdoc"}:
        return False

    if not lower.startswith(("http://", "https://")):
        return False

    if is_handshake_url(url):
        return False

    return True


def unwrap_external_url(url: str | None) -> Optional[str]:
    """
    Handshake sometimes wraps the employer URL in a redirect URL.
    This extracts the real employer URL if it appears in query params.
    """

    if not url:
        return None

    if is_real_external_url(url):
        return url

    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
    except Exception:
        return None

    likely_keys = [
        "url",
        "href",
        "target",
        "redirect",
        "redirect_url",
        "return_to",
        "application_url",
        "external_url",
    ]

    for key in likely_keys:
        for value in params.get(key, []):
            candidate = unquote(value)
            if is_real_external_url(candidate):
                return candidate

    for values in params.values():
        for value in values:
            candidate = unquote(value)
            if is_real_external_url(candidate):
                return candidate

    return None


def safe_text(locator) -> str:
    try:
        if locator.count() == 0:
            return ""
        return normalize_space(locator.first.inner_text())
    except Exception:
        return ""


def visible(locator) -> bool:
    try:
        return locator.count() > 0 and locator.first.is_visible()
    except Exception:
        return False


def locator_enabled(locator) -> bool:
    try:
        return locator.count() > 0 and locator.first.is_enabled()
    except Exception:
        return False


# ============================================================
# HANDSHAKE SETUP
# ============================================================

def open_handshake(page: Page) -> None:
    print("\n" + "=" * 68)
    print("HANDSHAKE DISCOVERY")
    print("=" * 68)

    start_url = os.getenv("HANDSHAKE_START_URL", "").strip() or HANDSHAKE_HOME

    print("\nOpening Handshake...")
    if start_url != HANDSHAKE_HOME:
        print(f"Using saved Handshake search URL: {start_url}")

    page.goto(
        start_url,
        wait_until="domcontentloaded",
        timeout=60_000,
    )

    try:
        page.wait_for_load_state("networkidle", timeout=10_000)
    except Exception:
        pass

    print("\nHandshake is open.")

    print(
        "\nIf needed:"
        "\n  1. Log in normally"
        "\n  2. Complete Berkeley authentication"
        "\n  3. Go to Jobs"
        "\n  4. Configure your search"
    )

    print(
        "\nRecommended:"
        "\n  Search: Software Engineer Intern"
        "\n  Job type: Internship"
        "\n  Sort: Most relevant"
    )

    print("\nEach discovered job will get its OWN tab.")
    print("\nNative Handshake resume drops will auto-submit once required fields are complete.")
    print("External applications and Greenhouse forms still remain manual at final submit.")

    if (env_flag("HEADLESS") or env_flag("BACKGROUND_BROWSER")) and os.getenv("HANDSHAKE_START_URL", "").strip():
        print("\nHidden/background mode: using HANDSHAKE_START_URL and skipping manual setup prompt.")
        return

    input(
        "\nWhen the search results are ready, "
        "return to Terminal and press ENTER..."
    )


# ============================================================
# JOB LINK DISCOVERY
# ============================================================

def find_job_links(page: Page) -> list[dict]:
    selectors = [
        "a[href*='/jobs/']",
        "a[href*='/job/']",
    ]

    candidates = []
    seen = set()

    for selector in selectors:
        try:
            links = page.locator(selector)
            count = links.count()
        except Exception:
            continue

        for i in range(count):
            try:
                link = links.nth(i)
                href = link.get_attribute("href")

                if not href:
                    continue

                href = urljoin(HANDSHAKE_HOME, href).split("#")[0]

                if not is_handshake_url(href):
                    continue

                lower = href.lower()

                if "/jobs/" not in lower and "/job/" not in lower:
                    continue

                if href in seen:
                    continue

                text = safe_text(link)

                if not text:
                    continue

                seen.add(href)
                candidates.append({"url": href, "text": text})

            except Exception:
                continue

    return candidates


# ============================================================
# JOB TITLE / COMPANY
# ============================================================

def get_job_title(page: Page) -> str:
    selectors = [
        "h1",
        "[data-testid*='job-title']",
        "[data-hook*='job-title']",
    ]

    for selector in selectors:
        try:
            locator = page.locator(selector)
            if locator.count():
                text = safe_text(locator)
                if text:
                    return text
        except Exception:
            continue

    return "Unknown job"


def company_from_apply_dialog(page: Page) -> Optional[str]:
    try:
        dialogs = page.get_by_role("dialog")

        if not dialogs.count():
            return None

        text = normalize_space(dialogs.first.inner_text())

        markers = [
            "Apply to ",
            "Details from ",
        ]

        for marker in markers:
            if marker not in text:
                continue

            company = text.split(marker, 1)[1]

            endings = [
                ":",
                "Applying requires",
                "Details from",
                "Attach your resume",
                "Additional Instructions",
            ]

            for ending in endings:
                if ending in company:
                    company = company.split(ending, 1)[0]

            company = company.strip().rstrip(".").strip()

            if company and len(company) < 120:
                return company

    except Exception:
        pass

    return None


def get_company_name(page: Page) -> str:
    selectors = [
        "[data-testid*='employer-name']",
        "[data-testid*='company-name']",
        "[data-hook*='employer-name']",
        "[data-hook*='company-name']",
    ]

    for selector in selectors:
        try:
            locator = page.locator(selector)

            if not locator.count():
                continue

            text = safe_text(locator)

            if text and text.lower() not in {"employer", "employers"}:
                return text

        except Exception:
            continue

    try:
        heading = page.locator("h1").first

        if heading.count():
            parent = heading.locator("xpath=..")
            links = parent.locator("a")

            ignored = {
                "employer",
                "employers",
                "jobs",
                "save",
                "share",
                "apply",
                "apply now",
                "quick apply",
            }

            for i in range(links.count()):
                text = safe_text(links.nth(i))
                lower = text.lower()

                if not text:
                    continue

                if lower in ignored:
                    continue

                if len(text) > 100:
                    continue

                return text

    except Exception:
        pass

    return "Unknown company"


# ============================================================
# APPLICATION CONTROLS
# ============================================================

def find_quick_apply_button(page: Page):
    names = [
        "Quick apply",
        "Quick Apply",
    ]

    for name in names:
        try:
            button = page.get_by_role("button", name=name, exact=True)
            if visible(button):
                return button.first
        except Exception:
            continue

    return None


def find_external_apply_control(page: Page):
    names = [
        "Apply",
        "Apply now",
        "Apply Now",
        "Apply externally",
        "Apply Externally",
        "Apply on company site",
        "Apply on employer site",
        "Apply on website",
    ]

    for name in names:
        try:
            link = page.get_by_role("link", name=name, exact=True)
            if visible(link):
                return link.first
        except Exception:
            pass

        try:
            button = page.get_by_role("button", name=name, exact=True)
            if visible(button):
                return button.first
        except Exception:
            pass

    return None


def find_view_application_control(page: Page):
    pattern = re.compile(r"View\s+application", re.I)

    try:
        link = page.get_by_role("link", name=pattern)
        if visible(link):
            return link.first
    except Exception:
        pass

    try:
        button = page.get_by_role("button", name=pattern)
        if visible(button):
            return button.first
    except Exception:
        pass

    try:
        control = page.get_by_text(pattern, exact=False)
        if visible(control):
            return control.first
    except Exception:
        pass

    return None


def find_submit_application_button(page: Page):
    names = [
        "Submit Application",
        "Submit application",
    ]

    for name in names:
        try:
            button = page.get_by_role("button", name=name, exact=True)
            if visible(button):
                return button.first
        except Exception:
            continue

    return None


def find_external_step_button(page: Page):
    names = [
        "Step 2: External Application",
        "External Application",
        "Continue to External Application",
    ]

    for name in names:
        try:
            button = page.get_by_role("button", name=name, exact=True)
            if visible(button):
                return button.first
        except Exception:
            pass

        try:
            link = page.get_by_role("link", name=name, exact=True)
            if visible(link):
                return link.first
        except Exception:
            pass

    try:
        buttons = page.locator("button")

        for i in range(buttons.count()):
            button = buttons.nth(i)

            if not button.is_visible():
                continue

            text = normalize_space(button.inner_text()).lower()

            if "external application" in text and "submit" not in text:
                return button

    except Exception:
        pass

    return None


# ============================================================
# EXTERNAL URL CAPTURE
# ============================================================

def direct_external_url(control) -> Optional[str]:
    attributes = [
        "href",
        "data-href",
        "data-url",
    ]

    for attribute in attributes:
        try:
            value = control.get_attribute(attribute)
            destination = unwrap_external_url(value)

            if destination:
                return destination

        except Exception:
            continue

    return None


def wait_for_real_url(page: Page, timeout_ms: int = 20_000) -> Optional[str]:
    elapsed = 0
    interval = 250

    while elapsed < timeout_ms:
        try:
            destination = unwrap_external_url(page.url)

            if destination:
                return destination

        except Exception:
            return None

        try:
            page.wait_for_timeout(interval)
        except Exception:
            return None

        elapsed += interval

    return None


def capture_external_after_click(page: Page, control) -> Optional[str]:
    """
    Click a Handshake control and capture the employer destination.

    Handles direct hrefs, popup tabs, same-tab navigation, and Handshake
    wrapped redirect URLs. The permanent Handshake job tab is restored
    whenever possible.
    """

    direct = direct_external_url(control)

    if direct:
        print("  ✓ External URL found directly")
        return direct

    original_url = page.url

    try:
        existing_pages = set(page.context.pages)
    except Exception:
        existing_pages = set()

    try:
        control.click(timeout=10_000)
    except Exception as exc:
        print(f"  ⚠ Could not click external control: {exc}")
        return None

    elapsed = 0
    interval = 250

    while elapsed < 25_000:
        try:
            current_pages = set(page.context.pages)
            new_pages = list(current_pages - existing_pages)
        except Exception:
            new_pages = []

        for popup in new_pages:
            destination = wait_for_real_url(popup, timeout_ms=10_000)

            if destination:
                print("  ✓ Captured external destination:")
                print(f"    {destination}")

                try:
                    popup.close()
                except Exception:
                    pass

                return destination

        try:
            current_url = page.url
            destination = unwrap_external_url(current_url)

            if current_url != original_url and destination:
                print("  ✓ Captured external destination:")
                print(f"    {destination}")

                try:
                    page.goto(
                        original_url,
                        wait_until="domcontentloaded",
                        timeout=30_000,
                    )

                    try:
                        page.wait_for_load_state("networkidle", timeout=8_000)
                    except Exception:
                        pass

                except Exception:
                    pass

                return destination

        except Exception:
            pass

        try:
            page.wait_for_timeout(interval)
        except Exception:
            break

        elapsed += interval

    try:
        current_pages = set(page.context.pages)
        temporary_pages = list(current_pages - existing_pages)

        for popup in temporary_pages:
            try:
                popup.close()
            except Exception:
                pass

    except Exception:
        pass

    try:
        if page.url != original_url:
            page.goto(
                original_url,
                wait_until="domcontentloaded",
                timeout=30_000,
            )
    except Exception:
        pass

    print("  ⚠ External destination did not resolve")
    return None


# ============================================================
# PREVIOUSLY CLICKED / VIEW APPLICATION BANNER
# ============================================================

def handle_previously_clicked_banner(page: Page) -> Optional[str]:
    """
    Handles Handshake jobs that say:

      Did you apply to this job?
      You started an application on the employer's website.
      View application

    In this state, Apply externally can be disabled, so the bot must click
    View application and capture the actual employer URL.
    """

    try:
        banner = page.get_by_text("Did you apply to this job?", exact=False)
        view_application = find_view_application_control(page)

        if not visible(banner) and view_application is None:
            return None

        print("  ℹ Detected previously-clicked application state")
        print("  Using 'View application' because Apply externally may be disabled")

        if view_application is None:
            print("  ⚠ Banner detected, but 'View application' was not found")
            return None

        destination = capture_external_after_click(page, view_application)

        if destination:
            print("  ✓ Captured destination from 'View application'")
            print(f"    {destination}")
            return destination

        print("  ⚠ Clicked 'View application', but no external destination was captured")
        return None

    except Exception as exc:
        print(f"  ⚠ Error in previously-clicked handler: {exc}")
        return None


# ============================================================
# HANDSHAKE SCREENING QUESTION HANDLER
# ============================================================

def get_application_root(page: Page):
    try:
        dialog = page.get_by_role("dialog")
        if visible(dialog):
            return dialog.first
    except Exception:
        pass

    return page.locator("body")


def radio_label_text(radio) -> str:
    try:
        label = radio.evaluate(
            """
            el => {
                if (el.labels && el.labels.length) {
                    return Array.from(el.labels).map(label => label.innerText || label.textContent || '').join(' ');
                }
                const aria = el.getAttribute('aria-label');
                if (aria) return aria;
                const labelledBy = el.getAttribute('aria-labelledby');
                if (labelledBy) {
                    return labelledBy.split(/\\s+/).map(id => {
                        const node = document.getElementById(id);
                        return node ? (node.innerText || node.textContent || '') : '';
                    }).join(' ');
                }
                const value = el.getAttribute('value');
                if (value) return value;
                return '';
            }
            """
        )
        text = normalize_space(label or "")
        if text:
            return text
    except Exception:
        pass

    try:
        text = safe_text(radio.locator("xpath=ancestor::label[1]"))
        if text:
            return text
    except Exception:
        pass

    try:
        value = radio.get_attribute("value") or ""
        return normalize_space(value)
    except Exception:
        return ""


def radio_is_checked(radio) -> bool:
    try:
        return radio.is_checked()
    except Exception:
        return False


def group_has_checked_radio(container) -> bool:
    try:
        radios = container.get_by_role("radio")
        for i in range(radios.count()):
            if radio_is_checked(radios.nth(i)):
                return True
    except Exception:
        pass

    try:
        inputs = container.locator("input[type='radio']")
        for i in range(inputs.count()):
            if radio_is_checked(inputs.nth(i)):
                return True
    except Exception:
        pass

    return False


def get_radio_options(container) -> list[str]:
    options: list[str] = []

    try:
        radios = container.get_by_role("radio")
        count = radios.count()
    except Exception:
        count = 0

    if count == 0:
        try:
            radios = container.locator("input[type='radio']")
            count = radios.count()
        except Exception:
            count = 0

    for i in range(count):
        try:
            option = radio_label_text(radios.nth(i))
            option = normalize_space(option)

            if option and option not in options:
                options.append(option)
        except Exception:
            continue

    cleaned = []

    for option in options:
        lower = option.lower().strip()

        if lower in {"true", "1"}:
            option = "Yes"
        elif lower in {"false", "0"}:
            option = "No"

        if option not in cleaned:
            cleaned.append(option)

    return cleaned


def get_radio_question_text(container, options: list[str]) -> str:
    try:
        text = normalize_space(container.inner_text())
    except Exception:
        text = ""

    if not text:
        return "Required radio question"

    for option in options:
        # Remove standalone option labels from the text.
        text = re.sub(rf"\b{re.escape(option)}\b", " ", text, flags=re.I)

    cleanup_phrases = [
        "Select one",
        "Required",
        "*",
    ]

    for phrase in cleanup_phrases:
        text = text.replace(phrase, " ")

    text = normalize_space(text)

    if not text:
        return "Required radio question"

    if len(text) > 500:
        text = text[:500].rsplit(" ", 1)[0] + "..."

    return text


def collect_radio_question_groups(root) -> list[tuple[object, str, list[str]]]:
    groups: list[tuple[object, str, list[str]]] = []
    seen_texts = set()

    # Best case: questions are inside fieldsets.
    try:
        fieldsets = root.locator("fieldset")
        for i in range(fieldsets.count()):
            fieldset = fieldsets.nth(i)
            options = get_radio_options(fieldset)

            if not options:
                continue

            question = get_radio_question_text(fieldset, options)
            key = normalize_space(question + " " + "|".join(options)).lower()

            if key in seen_texts:
                continue

            seen_texts.add(key)
            groups.append((fieldset, question, options))
    except Exception:
        pass

    if groups:
        return groups

    # Fallback: collect ancestor containers around radio inputs.
    try:
        radios = root.locator("input[type='radio']")
        for i in range(radios.count()):
            radio = radios.nth(i)

            try:
                container = radio.locator(
                    "xpath=ancestor::*[self::fieldset or self::div or self::section][.//input[@type='radio']][1]"
                )
            except Exception:
                continue

            if not container.count():
                continue

            options = get_radio_options(container)

            if not options:
                continue

            question = get_radio_question_text(container, options)
            key = normalize_space(question + " " + "|".join(options)).lower()

            if key in seen_texts:
                continue

            seen_texts.add(key)
            groups.append((container, question, options))

    except Exception:
        pass

    return groups


def _norm_option_text(value: str) -> str:
    return " ".join("".join(ch.lower() if ch.isalnum() else " " for ch in str(value)).split())


def _option_contains_any(options: list[str], *phrases: str) -> Optional[str]:
    normalized_phrases = [_norm_option_text(p) for p in phrases if _norm_option_text(p)]
    for option in options:
        normalized_option = _norm_option_text(option)
        if any(phrase in normalized_option for phrase in normalized_phrases):
            return option
    return None


def _option_exact(options: list[str], *answers: str) -> Optional[str]:
    normalized_answers = {_norm_option_text(a) for a in answers if _norm_option_text(a)}
    for option in options:
        if _norm_option_text(option) in normalized_answers:
            return option
    return None


def _sensitive_answer_from_options_only(options: list[str]) -> Optional[str]:
    """Handle demographic dropdowns when Handshake hides the actual question label.

    Some Handshake/Greenhouse embedded forms surface only "Required dropdown question"
    to Playwright while exposing distinctive option sets. These must be answered
    from the locked profile, not by the LLM, because stale/ambiguous reasoning once
    selected the wrong sexual-orientation option.
    """
    normalized = [_norm_option_text(o) for o in options]
    joined = " | ".join(normalized)

    # Sexual orientation / LGBTQ identity: user-confirmed answer is Straight.
    # If the form asks the common yes/no/questioning/non-disclosure LGBTQ question,
    # Straight maps to No. Never choose Yes here.
    if (
        "questioning" in joined
        and any(o in {"yes", "y"} for o in normalized)
        and any(o in {"no", "n"} for o in normalized)
        and any("wish" in o or "prefer" in o or "decline" in o for o in normalized)
    ):
        return _option_exact(options, "No")

    # Direct sexual-orientation list.
    if any(term in joined for term in ["heterosexual", "straight", "lesbian", "gay", "bisexual", "asexual", "pansexual", "queer"]):
        return (
            _option_exact(options, "Straight", "Heterosexual")
            or _option_contains_any(options, "straight", "heterosexual")
            or _option_contains_any(options, "prefer not", "decline", "don't wish", "do not wish")
        )

    # Disability: user-confirmed answer is no disabilities.
    if "disability" in joined or "disabled" in joined:
        return (
            _option_contains_any(options, "no", "disability")
            or _option_contains_any(options, "do not have a disability", "don't have a disability")
            or _option_exact(options, "No")
        )

    # Gender identity lists. User-confirmed: male; not transgender.
    if any(term in joined for term in ["cisgender", "transgender", "non binary", "two spirit"]):
        return (
            _option_contains_any(options, "cisgender man")
            or _option_contains_any(options, "cis man")
            or _option_exact(options, "Male", "Man")
            or _option_contains_any(options, "don't wish", "do not wish", "prefer not")
        )

    return None


def known_answer_for_question(question: str, options: list[str]) -> Optional[str]:
    lower = question.lower()

    # High-risk locked answers. Never let the LLM or stale answer bank answer these.
    # Sample confirmed: U.S. citizen; no visa sponsorship now or in the future.
    if (
        "sponsorship" in lower
        or "sponsor" in lower
        or "visa" in lower and "work" in lower
        or "employment based visa" in lower
        or "employment visa" in lower
        or "visa status" in lower
    ):
        return _option_exact(options, "No") or _option_contains_any(options, "no")

    # Robinhood-style conflict/disclosure question. Sample confirmed default is No.
    if any(phrase in lower for phrase in [
        "personal/familial",
        "familial relationship",
        "personal relationship",
        "robinhood employees",
        "vendors",
        "outside business activities",
        "outside business activity",
        "investment that is greater than 5",
        "publicly-traded company",
        "publicly traded company",
        "private company",
        "business relationship",
        "current competitor",
        "intellectual property ownership",
        "patents",
        "trademarks",
        "copyrights",
        "conflict of interest",
    ]):
        return _option_exact(options, "No") or _option_contains_any(options, "no")

    options_only_answer = _sensitive_answer_from_options_only(options)
    if options_only_answer:
        return options_only_answer

    checks = []

    if "january" in lower and "may" in lower and "available" in lower:
        checks.append(PROFILE.get("available_january_may", ""))

    if (
        "authorized" in lower
        and "work" in lower
        and ("united states" in lower or " u.s" in lower or " us" in lower)
    ):
        checks.append(PROFILE.get("authorized_us", ""))

    if (
        "sponsorship" in lower
        or "sponsor" in lower
        or "employment visa" in lower
        or "visa status" in lower
    ):
        checks.append(PROFILE.get("sponsorship", ""))

    if "military" in lower or "veteran" in lower:
        checks.extend(PROFILE.get("veteran_status_variants", []))
        checks.append(PROFILE.get("veteran_status", ""))

    if "gender" in lower and "identity" not in lower:
        checks.extend(PROFILE.get("gender_variants", []))
        checks.append(PROFILE.get("gender", ""))

    if "hispanic" in lower or "latino" in lower:
        checks.extend(PROFILE.get("hispanic_latino_variants", []))
        checks.append(PROFILE.get("hispanic_latino", ""))

    # Only answer the broad race/ethnicity question if one of the choices
    # exactly matches the Hispanic/Latino profile answer. Do not infer race.
    if "race" in lower or "ethnicity" in lower:
        checks.extend(PROFILE.get("hispanic_latino_variants", []))

    for configured in checks:
        answer = normalize_reply_to_option(str(configured), options)
        if answer:
            return answer

    return None


def known_text_answer_for_question(question: str) -> Optional[str]:
    lower = question.lower()

    if "phone" in lower:
        return str(PROFILE.get("phone", "")).strip()

    if "preferred" in lower and "name" in lower:
        return str(PROFILE.get("preferred_first_name", "")).strip()

    if "first name" in lower:
        return str(PROFILE.get("first_name", "")).strip()

    if "last name" in lower:
        return str(PROFILE.get("last_name", "")).strip()

    if "email" in lower:
        return str(PROFILE.get("email", "")).strip()

    if "linkedin" in lower:
        return str(PROFILE.get("linkedin", "")).strip()

    return None


def field_is_required(field, label: str) -> bool:
    lower = label.lower()

    if "required" in lower:
        return True

    try:
        if field.get_attribute("required") is not None:
            return True
    except Exception:
        pass

    try:
        if (field.get_attribute("aria-required") or "").lower() == "true":
            return True
    except Exception:
        pass

    return False


def locator_key(locator) -> str:
    try:
        box = locator.bounding_box()
        if box:
            return (
                f"{round(box.get('x', 0))}:"
                f"{round(box.get('y', 0))}:"
                f"{round(box.get('width', 0))}:"
                f"{round(box.get('height', 0))}"
            )
    except Exception:
        pass

    try:
        return normalize_space(locator.inner_text())[:200]
    except Exception:
        return str(id(locator))


def find_unanswered_dropdown_controls(root) -> list[object]:
    controls: list[object] = []
    seen = set()

    selectors = [
        "[role='combobox']",
        "[aria-haspopup='listbox']",
        "button:has-text('Select One')",
        "button:has-text('Select one')",
    ]

    for selector in selectors:
        try:
            found = root.locator(selector)
            count = found.count()
        except Exception:
            continue

        for i in range(count):
            control = found.nth(i)

            try:
                if not control.is_visible() or not control.is_enabled():
                    continue
            except Exception:
                continue

            text = safe_text(control).lower()
            aria = ""
            try:
                aria = (control.get_attribute("aria-label") or "").lower()
            except Exception:
                pass

            if "select one" not in text and "select one" not in aria:
                continue

            key = locator_key(control)
            if key in seen:
                continue

            seen.add(key)
            controls.append(control)

    return controls


def dropdown_question_text(control) -> str:
    try:
        raw = control.evaluate(
            r"""
            el => {
                function clean(text) {
                    return (text || '').replace(/\s+/g, ' ').trim();
                }
                function selectCount(text) {
                    return (text.match(/Select One|Select one/g) || []).length;
                }

                let current = el;
                let fallback = clean(el.parentElement ? el.parentElement.innerText : '');

                for (let depth = 0; current && depth < 8; depth++, current = current.parentElement) {
                    const text = clean(current.innerText || current.textContent || '');
                    if (!text.includes('Select One') && !text.includes('Select one')) {
                        continue;
                    }
                    if (selectCount(text) === 1 && text.length < 900) {
                        return text;
                    }
                    if (!fallback && text.length < 900) {
                        fallback = text;
                    }
                }

                return fallback;
            }
            """
        )
    except Exception:
        raw = safe_text(control)

    raw = normalize_space(raw)

    if "Select One" in raw:
        question = raw.split("Select One", 1)[0]
    elif "Select one" in raw:
        question = raw.split("Select one", 1)[0]
    else:
        question = raw

    question = normalize_space(question)

    if not question:
        try:
            question = control.evaluate(
                r"""
                el => {
                    function clean(text) { return (text || '').replace(/\s+/g, ' ').trim(); }
                    function useful(text) {
                        const t = clean(text);
                        if (!t) return '';
                        if (/^(select one|select)$/i.test(t)) return '';
                        if (/^(yes|no)$/i.test(t)) return '';
                        if (t.length > 1200) return '';
                        return t;
                    }
                    // Look backward through nearby siblings for the actual prompt text.
                    let node = el;
                    for (let depth = 0; node && depth < 6; depth++, node = node.parentElement) {
                        let prev = node.previousElementSibling;
                        for (let i = 0; prev && i < 6; i++, prev = prev.previousElementSibling) {
                            const t = useful(prev.innerText || prev.textContent || '');
                            if (t) return t;
                        }
                    }
                    // Labels connected through aria-labelledby/labelledby.
                    const labelledby = el.getAttribute('aria-labelledby') || el.getAttribute('aria-describedby') || '';
                    for (const id of labelledby.split(/\s+/).filter(Boolean)) {
                        const labelled = document.getElementById(id);
                        const t = useful(labelled && (labelled.innerText || labelled.textContent));
                        if (t) return t;
                    }
                    return '';
                }
                """
            ) or ""
            question = normalize_space(question)
        except Exception:
            question = ""

    if not question:
        question = "Required dropdown question"

    # If a container still includes too much copy, keep the final sentence-like
    # question before the dropdown.
    if len(question) > 500:
        question = question[-500:]
        parts = re.split(r"(?<=[.?])\s+", question)
        if parts:
            question = parts[-1]

    return normalize_space(question)


def read_visible_dropdown_options(page: Page) -> list[str]:
    options: list[str] = []

    selectors = [
        "[role='option']",
        "[role='listbox'] *",
        "[data-testid*='option']",
    ]

    for selector in selectors:
        try:
            found = page.locator(selector)
            count = found.count()
        except Exception:
            continue

        for i in range(count):
            item = found.nth(i)

            try:
                if not item.is_visible():
                    continue
            except Exception:
                continue

            text = safe_text(item)
            text = normalize_space(text)

            if not text:
                continue

            if text.lower() in {"select one", "select"}:
                continue

            if len(text) > 200:
                continue

            if text not in options:
                options.append(text)

    return options


def open_dropdown_and_get_options(page: Page, control) -> list[str]:
    try:
        control.scroll_into_view_if_needed(timeout=5_000)
    except Exception:
        pass

    try:
        control.click(timeout=5_000)
        page.wait_for_timeout(500)
    except Exception:
        return []

    options = read_visible_dropdown_options(page)

    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(150)
    except Exception:
        pass

    return options


def select_dropdown_option(page: Page, control, answer: str, options: list[str]) -> bool:
    matched = normalize_reply_to_option(answer, options) if options else answer

    if not matched:
        return False

    try:
        control.scroll_into_view_if_needed(timeout=5_000)
    except Exception:
        pass

    try:
        control.click(timeout=5_000)
        page.wait_for_timeout(300)
    except Exception:
        return False

    escaped = re.escape(matched.strip())
    pattern = re.compile(rf"^{escaped}$", re.I)

    try:
        option = page.get_by_role("option", name=pattern)
        if visible(option):
            option.first.click(timeout=5_000)
            return True
    except Exception:
        pass

    try:
        option_text = page.get_by_text(matched, exact=True)
        if visible(option_text):
            option_text.first.click(timeout=5_000)
            return True
    except Exception:
        pass

    try:
        page.keyboard.press("Escape")
    except Exception:
        pass

    return False


def answer_dropdown_questions_by_email(page: Page, title: str, company: str) -> bool:
    root = get_application_root(page)
    controls = find_unanswered_dropdown_controls(root)

    if not controls:
        return True

    all_answered = True

    for control in controls:
        question = dropdown_question_text(control)
        options = open_dropdown_and_get_options(page, control)

        print("  Found required Handshake dropdown question:")
        print(f"    {question}")

        if options:
            print("  Options:")
            for index, option in enumerate(options, start=1):
                print(f"    {index}. {option}")
        else:
            print("  ⚠ Could not read dropdown options")
            all_answered = False
            continue

        answer = known_answer_for_question(question, options)

        if answer:
            print(f"  ✓ Using saved profile answer: {answer}")
        elif infer_choice_answer is not None:
            answer = infer_choice_answer(
                company=company,
                title=title,
                question=question,
                options=options,
                context="handshake_dropdown",
            )

        if not answer and infer_choice_answer is None:
            print("  ⚠ Choice-answer AI resolver is unavailable; falling back to email.")

        if not answer:
            answer = ask_application_question(
                company=company,
                title=title,
                question=question,
                options=options,
            )

        if not answer:
            print("  ⚠ No answer available; leaving this job for manual review")
            all_answered = False
            continue

        if select_dropdown_option(page, control, answer, options):
            print(f"  ✓ Selected dropdown answer: {answer}")
            try:
                page.wait_for_timeout(500)
            except Exception:
                pass
        else:
            print(f"  ⚠ Could not select dropdown answer: {answer}")
            all_answered = False

    return all_answered


def select_radio_option(container, answer: str) -> bool:
    escaped = re.escape(answer.strip())
    pattern = re.compile(rf"^{escaped}$", re.I)

    try:
        radio = container.get_by_role("radio", name=pattern)
        if visible(radio):
            try:
                radio.first.check(timeout=5_000)
            except Exception:
                radio.first.click(timeout=5_000)
            return True
    except Exception:
        pass

    try:
        labels = container.locator("label")
        for i in range(labels.count()):
            label = labels.nth(i)
            text = normalize_space(label.inner_text())
            if text.lower() == answer.lower():
                label.click(timeout=5_000)
                return True
    except Exception:
        pass

    try:
        option_text = container.get_by_text(answer, exact=True)
        if visible(option_text):
            option_text.first.click(timeout=5_000)
            return True
    except Exception:
        pass

    return False


def answer_radio_questions_by_email(page: Page, title: str, company: str) -> bool:
    root = get_application_root(page)
    groups = collect_radio_question_groups(root)

    if not groups:
        return True

    all_answered = True

    for container, question, options in groups:
        if group_has_checked_radio(container):
            continue

        print("  Found required Handshake screening question:")
        print(f"    {question}")

        answer = known_answer_for_question(question, options)

        if answer:
            print(f"  ✓ Using saved profile answer: {answer}")
        elif infer_choice_answer is not None:
            answer = infer_choice_answer(
                company=company,
                title=title,
                question=question,
                options=options,
                context="handshake_radio",
            )

        if not answer and infer_choice_answer is None:
            print("  ⚠ Choice-answer AI resolver is unavailable; falling back to email.")

        if not answer:
            answer = ask_application_question(
                company=company,
                title=title,
                question=question,
                options=options,
            )

        if not answer:
            print("  ⚠ No answer available; leaving this job for manual review")
            all_answered = False
            continue

        if select_radio_option(container, answer):
            print(f"  ✓ Selected answer: {answer}")
            try:
                page.wait_for_timeout(500)
            except Exception:
                pass
        else:
            print(f"  ⚠ Could not select answer: {answer}")
            all_answered = False

    return all_answered


def get_text_field_label(field) -> str:
    try:
        field_id = field.get_attribute("id")
        if field_id:
            label = field.page.locator(f"label[for='{field_id}']")
            text = safe_text(label)
            if text:
                return text
    except Exception:
        pass

    try:
        label = field.locator("xpath=ancestor::label[1]")
        text = safe_text(label)
        if text:
            return text
    except Exception:
        pass

    try:
        container = field.locator("xpath=ancestor::*[self::div or self::section][1]")
        text = safe_text(container)
        if text:
            return text
    except Exception:
        pass

    return "Required text question"


def answer_text_questions_by_email(page: Page, title: str, company: str) -> bool:
    root = get_application_root(page)
    fields = []

    try:
        textareas = root.locator("textarea")
        for i in range(textareas.count()):
            fields.append(textareas.nth(i))
    except Exception:
        pass

    try:
        inputs = root.locator(
            "input:not([type]), input[type='text'], input[type='tel'], input[type='email'], input[type='url'], input[type='number']"
        )
        for i in range(inputs.count()):
            fields.append(inputs.nth(i))
    except Exception:
        pass

    if not fields:
        return True

    all_answered = True

    for field in fields:
        try:
            if not field.is_visible() or not field.is_enabled():
                continue

            value = field.input_value()
            if value.strip():
                continue

            label = get_text_field_label(field)
            label = normalize_space(label)

            if len(label) > 500:
                label = label[:500].rsplit(" ", 1)[0] + "..."

            known_answer = known_text_answer_for_question(label)
            required = field_is_required(field, label)

            # Fill known profile fields such as phone even when the DOM does
            # not mark them cleanly as required.
            if known_answer:
                field.fill(known_answer, timeout=5_000)
                print(f"  ✓ Filled {label}: {known_answer}")
                try:
                    page.wait_for_timeout(300)
                except Exception:
                    pass
                continue

            # Do not email for optional blank follow-up text boxes, such as
            # "If yes, explain" fields that are not required.
            if not required:
                continue

            print("  Found required Handshake text question:")
            print(f"    {label}")

            answer = None

            # First try the short-answer agent. For prompts like
            # "Why are you interested...", this drafts a finished response
            # from the applicant profile, applicant_brief.md, and page/job text.
            try:
                from src.short_answer_agent import draft_short_answer_for_field

                draft_result = draft_short_answer_for_field(
                    page=page,
                    company=company,
                    title=title,
                    question=label,
                    source="handshake",
                )

                if draft_result.get("status") == "use" and draft_result.get("answer"):
                    answer = str(draft_result["answer"]).strip()
                elif draft_result.get("status") == "stop":
                    print("  ⚠ Short-answer draft stopped for manual review")
                    all_answered = False
                    continue
                else:
                    reason = draft_result.get("reason") or "short-answer agent unavailable"
                    print(f"  ⚠ Short-answer agent did not draft this field: {reason}")

            except Exception as exc:
                print(f"  ⚠ Short-answer agent failed safely: {exc}")

            # Fallback to the old email question flow only when the prompt
            # is not a draftable short-answer prompt or the agent is unavailable.
            if not answer:
                answer = ask_application_question(
                    company=company,
                    title=title,
                    question=label,
                    options=[],
                )

            if not answer:
                print("  ⚠ No answer available; leaving this job for manual review")
                all_answered = False
                continue

            field.fill(answer, timeout=5_000)
            print("  ✓ Filled text answer")

            try:
                page.wait_for_timeout(300)
            except Exception:
                pass

        except Exception as exc:
            print(f"  ⚠ Could not process text question: {exc}")
            all_answered = False

    return all_answered

def answer_handshake_screening_questions(page: Page, title: str, company: str) -> bool:
    """
    Answer required questions inside a Handshake application modal.
    Known profile answers are used first. Unknown choice/text questions are sent to the AI resolver before email fallback.
    """

    # Do text fields first so phone is filled before the bot asks about
    # dropdowns/radio questions.
    texts_ok = answer_text_questions_by_email(page, title, company)
    dropdowns_ok = answer_dropdown_questions_by_email(page, title, company)
    radios_ok = answer_radio_questions_by_email(page, title, company)

    return texts_ok and dropdowns_ok and radios_ok


# ============================================================
# RESUME DETECTION
# ============================================================

def handshake_resume_attached(page: Page) -> bool:
    try:
        dialogs = page.get_by_role("dialog")

        if not dialogs.count():
            return False

        text = normalize_space(dialogs.first.inner_text()).lower()

        # The words "Attach your resume" are a prompt, not evidence of an
        # attachment; a transcript .pdf can also appear in the same modal.
        # Require the selected marketing resume's name explicitly.
        from pathlib import Path
        configured = Path(str(PROFILE.get("resume", ""))).name.lower()
        if not configured or not configured.endswith(".pdf"):
            return False
        return configured in text

    except Exception:
        return False


# ============================================================
# HANDSHAKE NATIVE SUBMIT
# ============================================================

def auto_submit_handshake_resume_drops_enabled() -> bool:
    """
    The user explicitly asked for native Handshake resume-drop apps to
    submit automatically once all required fields are handled.

    This can still be disabled later by adding this to PROFILE:

        "auto_submit_handshake_resume_drops": False
    """

    return bool(
        PROFILE.get(
            "auto_submit_handshake_resume_drops",
            True,
        )
    )


def handshake_submission_confirmed(page: Page) -> bool:
    indicators = [
        "Application submitted",
        "Application submitted!",
        "Your application has been submitted",
        "You applied",
    ]

    for text in indicators:
        try:
            marker = page.get_by_text(
                text,
                exact=False,
            )

            if visible(marker):
                return True

        except Exception:
            continue

    return False


def submit_handshake_native_application(page: Page) -> bool:
    submit_button = find_submit_application_button(page)

    if submit_button is None:
        print("  ⚠ Submit Application button not found")
        return False

    if not locator_enabled(submit_button):
        print("  ⚠ Submit Application button is disabled")
        return False

    print("  Auto-submit is enabled for native Handshake resume drops")
    print("  Clicking Submit Application...")

    try:
        submit_button.click(timeout=10_000)
        page.wait_for_timeout(1_500)

    except Exception as exc:
        print(f"  ⚠ Submit Application click failed: {exc}")
        return False

    if handshake_submission_confirmed(page):
        print("  ✓ Handshake application submitted")
        return True

    # Some Handshake pages update slowly. Give them one more moment.
    try:
        page.wait_for_timeout(2_000)
    except Exception:
        pass

    if handshake_submission_confirmed(page):
        print("  ✓ Handshake application submitted")
        return True

    print("  ⚠ Submit was clicked, but confirmation was not detected")
    print("  Please inspect this tab manually")
    return False


# ============================================================
# OPEN INITIAL APPLY FLOW
# ============================================================

def open_application_flow(page: Page) -> str:
    quick_apply = find_quick_apply_button(page)

    if quick_apply is not None:
        print("  Apply control: Quick Apply")

        try:
            quick_apply.click(timeout=10_000)
            page.wait_for_timeout(750)
            return "opened"

        except Exception as exc:
            print(f"  ⚠ Could not open Quick Apply: {exc}")
            return "failed"

    apply_control = find_external_apply_control(page)

    if apply_control is None:
        return "not_found"

    direct = direct_external_url(apply_control)

    if direct:
        return "direct_external"

    print("  Apply control: Apply")

    try:
        apply_control.click(timeout=10_000)
        page.wait_for_timeout(750)
        return "opened"

    except Exception as exc:
        print(f"  ⚠ Could not open Apply flow: {exc}")
        return "failed"


# ============================================================
# INSPECT OPEN APPLICATION FLOW
# ============================================================

def inspect_open_application_flow(
    page: Page,
    title: str,
    company: str,
    job_url: str,
    tab_number: int,
) -> Optional[HandshakeJob]:
    modal_company = company_from_apply_dialog(page)

    if modal_company and company == "Unknown company":
        company = modal_company
        print(f"  ✓ Company from application dialog: {company}")

    submit_button = find_submit_application_button(page)

    if submit_button is not None:
        resume_attached = handshake_resume_attached(page)

        print("  Type:    Handshake native application")

        if resume_attached:
            print("  ✓ Resume appears attached")
        else:
            print("  ⚠ Resume attachment not confirmed")

        questions_ok = answer_handshake_screening_questions(
            page=page,
            title=title,
            company=company,
        )

        if not questions_ok or not resume_attached:
            print("  ⚠ Required native Handshake questions or resume attachment are not verified")
            print("  🚫 Submit Application NOT clicked")
            return HandshakeJob(
                title=title,
                company=company,
                handshake_url=job_url,
                application_type="handshake_screening_required",
                tab_number=tab_number,
            )

        print("  ✓ Native Handshake required fields handled")

        if auto_submit_handshake_resume_drops_enabled():
            submitted = submit_handshake_native_application(page)

            if submitted:
                return HandshakeJob(
                    title=title,
                    company=company,
                    handshake_url=job_url,
                    application_type="handshake_submitted",
                    tab_number=tab_number,
                )

            return HandshakeJob(
                title=title,
                company=company,
                handshake_url=job_url,
                application_type="handshake_submit_uncertain",
                tab_number=tab_number,
            )

        print("  ✓ Left open at Submit Application")
        print("  🚫 Submit Application NOT clicked")

        return HandshakeJob(
            title=title,
            company=company,
            handshake_url=job_url,
            application_type="handshake_resume_drop",
            tab_number=tab_number,
        )

    external_step = find_external_step_button(page)

    if external_step is not None:
        print("  Type:    Handshake employer instructions")
        print("  Found:   Step 2: External Application")

        if not locator_enabled(external_step):
            print("  Step 2 appears locked until required questions are answered")

        questions_ok = answer_handshake_screening_questions(
            page=page,
            title=title,
            company=company,
        )

        if not questions_ok:
            return HandshakeJob(
                title=title,
                company=company,
                handshake_url=job_url,
                application_type="handshake_screening_required",
                tab_number=tab_number,
            )

        external_step = find_external_step_button(page)

        if external_step is None:
            print("  ⚠ Step 2 disappeared after answering questions")
            return HandshakeJob(
                title=title,
                company=company,
                handshake_url=job_url,
                application_type="external_unknown",
                tab_number=tab_number,
            )

        print("  Opening Step 2 to capture destination...")

        destination = capture_external_after_click(page, external_step)

        if not destination:
            print("  ⚠ Step 2 opened, but external destination could not be captured")
            return HandshakeJob(
                title=title,
                company=company,
                handshake_url=job_url,
                application_type="external_unknown",
                tab_number=tab_number,
            )

        if is_greenhouse_url(destination):
            print("  ✓ Greenhouse destination")
            application_type = "external_greenhouse"
        else:
            domain = hostname_for(destination)
            print(f"  ⚠ External ATS not supported yet ({domain})")
            application_type = "external_other"

        return HandshakeJob(
            title=title,
            company=company,
            handshake_url=job_url,
            application_url=destination,
            application_type=application_type,
            tab_number=tab_number,
        )

    return None


# ============================================================
# INSPECT ONE JOB
# ============================================================

def inspect_job(
    page: Page,
    job_url: str,
    number: int,
    total: int,
    tab_number: int,
) -> HandshakeJob:
    print(f"\n[{number}/{total}] Opening Handshake job in TAB {tab_number}...")

    try:
        page.goto(job_url, wait_until="domcontentloaded", timeout=45_000)

    except Exception as exc:
        print(f"  ✗ Could not open job: {exc}")
        return HandshakeJob(
            title="Unknown job",
            company="Unknown company",
            handshake_url=job_url,
            application_type="failed",
            tab_number=tab_number,
        )

    try:
        page.wait_for_load_state("networkidle", timeout=8_000)
    except Exception:
        pass

    try:
        page.wait_for_timeout(700)
    except Exception:
        pass

    title = get_job_title(page)
    company = get_company_name(page)

    print(f"  Tab:     {tab_number}")
    print(f"  Job:     {title}")
    print(f"  Company: {company}")

    # Previously-opened Handshake jobs can show a "View application" banner.
    # In that state, Apply externally may be disabled.
    banner_url = handle_previously_clicked_banner(page)

    if banner_url:
        if is_greenhouse_url(banner_url):
            print("  ✓ Greenhouse destination")
            app_type = "external_greenhouse"
        else:
            domain = hostname_for(banner_url)
            print(f"  ⚠ External ATS not supported yet ({domain})")
            app_type = "external_other"

        return HandshakeJob(
            title=title,
            company=company,
            handshake_url=job_url,
            application_url=banner_url,
            application_type=app_type,
            tab_number=tab_number,
        )

    existing_flow = inspect_open_application_flow(
        page=page,
        title=title,
        company=company,
        job_url=job_url,
        tab_number=tab_number,
    )

    if existing_flow is not None:
        return existing_flow

    apply_control = find_external_apply_control(page)

    if apply_control is not None:
        direct = direct_external_url(apply_control)

        if direct:
            print("  Type:    Direct external application")
            print(f"  External: {direct}")

            if is_greenhouse_url(direct):
                print("  ✓ Greenhouse destination")
                application_type = "external_greenhouse"
            else:
                domain = hostname_for(direct)
                print(f"  ⚠ External ATS not supported yet ({domain})")
                application_type = "external_other"

            return HandshakeJob(
                title=title,
                company=company,
                handshake_url=job_url,
                application_url=direct,
                application_type=application_type,
                tab_number=tab_number,
            )

    result = open_application_flow(page)

    if result == "not_found":
        print("  Type:    Application control not detected")
        return HandshakeJob(
            title=title,
            company=company,
            handshake_url=job_url,
            application_type="unknown",
            tab_number=tab_number,
        )

    if result == "failed":
        return HandshakeJob(
            title=title,
            company=company,
            handshake_url=job_url,
            application_type="failed",
            tab_number=tab_number,
        )

    if result == "direct_external":
        control = find_external_apply_control(page)

        if control is not None:
            destination = direct_external_url(control)

            if destination:
                if is_greenhouse_url(destination):
                    application_type = "external_greenhouse"
                else:
                    application_type = "external_other"

                return HandshakeJob(
                    title=title,
                    company=company,
                    handshake_url=job_url,
                    application_url=destination,
                    application_type=application_type,
                    tab_number=tab_number,
                )

    try:
        page.wait_for_timeout(500)
    except Exception:
        pass

    opened_flow = inspect_open_application_flow(
        page=page,
        title=title,
        company=company,
        job_url=job_url,
        tab_number=tab_number,
    )

    if opened_flow is not None:
        return opened_flow

    try:
        destination = unwrap_external_url(page.url)

        if destination:
            print("  ✓ Apply navigated directly to:")
            print(f"    {destination}")

            try:
                page.goto(job_url, wait_until="domcontentloaded", timeout=30_000)
            except Exception:
                pass

            if is_greenhouse_url(destination):
                application_type = "external_greenhouse"
            else:
                application_type = "external_other"

            return HandshakeJob(
                title=title,
                company=company,
                handshake_url=job_url,
                application_url=destination,
                application_type=application_type,
                tab_number=tab_number,
            )

    except Exception:
        pass

    print("  ⚠ Application flow opened, but its type was not recognized.")

    return HandshakeJob(
        title=title,
        company=company,
        handshake_url=job_url,
        application_type="unknown",
        tab_number=tab_number,
    )


# ============================================================
# DISCOVERY
# ============================================================

def discover_handshake_jobs(
    page: Page,
    max_jobs: int = 20,
    stop_after_submissions: int | None = None,
) -> list[HandshakeJob]:
    print("\nScanning Handshake results and loading more job cards...")

    links = collect_handshake_job_links(page, max_jobs=max_jobs)

    if not links:
        print("\n✗ No Handshake job links were detected.")
        print(
            "\nMake sure:"
            "\n  • You are on Jobs → Search"
            "\n  • Search results are visible"
            "\n  • Several job cards have loaded"
        )
        return []

    print(f"\n✓ Found {len(links)} unique Handshake job links.")
    print("\nCreating one permanent tab for every discovered job until target is reached...")

    jobs = []
    total = len(links)
    submitted_count = 0

    for index, item in enumerate(links, start=1):
        if stop_after_submissions is not None and submitted_count >= stop_after_submissions:
            print(f"\n✓ Stop target reached inside Handshake discovery: {submitted_count}/{stop_after_submissions}")
            break

        job_page = page.context.new_page()
        tab_number = index + 1

        job = inspect_job(
            page=job_page,
            job_url=item["url"],
            number=index,
            total=total,
            tab_number=tab_number,
        )

        jobs.append(job)

        if job.application_type == "handshake_submitted":
            submitted_count += 1
            if stop_after_submissions is not None:
                print(f"  Batch confirmed submissions: {submitted_count}/{stop_after_submissions}")

    try:
        page.bring_to_front()
    except Exception:
        pass

    return jobs


# ============================================================
# SUMMARY
# ============================================================

def print_discovery_summary(jobs: list[HandshakeJob]) -> None:
    print("\n" + "=" * 68)
    print("HANDSHAKE DISCOVERY RESULTS")
    print("=" * 68)

    if not jobs:
        print("\nNo jobs collected.")
        return

    greenhouse = [job for job in jobs if job.application_type == "external_greenhouse"]
    native = [job for job in jobs if job.application_type == "handshake_resume_drop"]
    submitted = [job for job in jobs if job.application_type == "handshake_submitted"]
    submit_uncertain = [job for job in jobs if job.application_type == "handshake_submit_uncertain"]
    other = [job for job in jobs if job.application_type == "external_other"]
    screening = [job for job in jobs if job.application_type == "handshake_screening_required"]
    unknown = [
        job
        for job in jobs
        if job.application_type in {"unknown", "external_unknown", "failed"}
    ]

    print(f"\nJobs inspected:          {len(jobs)}")
    print(f"Greenhouse supported:    {len(greenhouse)}")
    print(f"Handshake auto-submitted:{len(submitted)}")
    print(f"Handshake ready manual:  {len(native)}")
    print(f"Submit uncertain:        {len(submit_uncertain)}")
    print(f"Other external ATS:      {len(other)}")
    print(f"Screening still needed:  {len(screening)}")
    print(f"Unknown / failed:        {len(unknown)}")

    print("\nOPEN HANDSHAKE JOB TABS")

    for job in jobs:
        tab = job.tab_number if job.tab_number is not None else "?"
        print(f"  Tab {tab}: {job.company} — {job.title}")
        print(f"           Type: {job.application_type}")

    if submitted:
        print("\nHANDSHAKE — AUTO-SUBMITTED")

        for index, job in enumerate(submitted, start=1):
            print(f"  {index}. Tab {job.tab_number}: {job.company} — {job.title}")

        print("\nThese native Handshake applications were submitted automatically.")

    if native:
        print("\nHANDSHAKE — READY FOR MANUAL SUBMIT")

        for index, job in enumerate(native, start=1):
            print(f"  {index}. Tab {job.tab_number}: {job.company} — {job.title}")

        print("\nThese tabs should be sitting at Submit Application.")
        print("🚫 The bot did NOT click Submit Application.")

    if submit_uncertain:
        print("\nHANDSHAKE — SUBMIT NEEDS CHECK")

        for index, job in enumerate(submit_uncertain, start=1):
            print(f"  {index}. Tab {job.tab_number}: {job.company} — {job.title}")

        print("\nThe bot clicked submit, but did not detect a confirmation.")
        print("Please inspect these tabs manually.")

    if greenhouse:
        print("\nGREENHOUSE — READY TO AUTOFILL")

        for index, job in enumerate(greenhouse, start=1):
            print(f"  {index}. Tab {job.tab_number}: {job.company} — {job.title}")

    if other:
        print("\nOTHER EXTERNAL ATS")

        for index, job in enumerate(other, start=1):
            domain = hostname_for(job.application_url or "")
            print(
                f"  {index}. Tab {job.tab_number}: "
                f"{job.company} — {job.title} [{domain}]"
            )

    if screening:
        print("\nHANDSHAKE SCREENING STILL NEEDED")

        for index, job in enumerate(screening, start=1):
            print(f"  {index}. Tab {job.tab_number}: {job.company} — {job.title}")

        print("\nThese need an email reply or manual answer before Step 2 can open.")

    if unknown:
        print("\nNEEDS MANUAL INSPECTION")

        for index, job in enumerate(unknown, start=1):
            print(f"  {index}. Tab {job.tab_number}: {job.company} — {job.title}")

    print("\nThe Handshake search-results tab and every discovered job tab remain open.")


# ============================================================
# GREENHOUSE URL EXTRACTION
# ============================================================

def get_greenhouse_urls(jobs: list[HandshakeJob]) -> list[str]:
    urls = []
    seen = set()

    for job in jobs:
        if job.application_type != "external_greenhouse":
            continue

        if not job.application_url:
            continue

        if job.application_url in seen:
            continue

        seen.add(job.application_url)
        urls.append(job.application_url)

    return urls

# ============================================================
# BATCH DISCOVERY HELPERS
# ============================================================

def _click_more_results_control(page: Page) -> bool:
    """Click visible Load more / Next style controls if Handshake shows one."""

    patterns = [
        r"(?i)^\s*load\s+more\s*$",
        r"(?i)^\s*show\s+more\s*$",
        r"(?i)^\s*more\s+jobs\s*$",
        r"(?i)^\s*next\s*$",
        r"(?i)^\s*next\s+page\s*$",
    ]

    for pattern in patterns:
        for role in ("button", "link"):
            try:
                control = page.get_by_role(role, name=re.compile(pattern)).first
                if control.count() and control.is_visible():
                    control.scroll_into_view_if_needed(timeout=2_000)
                    control.click(timeout=5_000)
                    page.wait_for_timeout(1_200)
                    print("  Clicked a Handshake results pagination/load-more control.")
                    return True
            except Exception:
                continue

    try:
        clicked = page.evaluate(
            r"""
            () => {
                const re = /^(load\s+more|show\s+more|more\s+jobs|next|next\s+page)$/i;
                const controls = Array.from(document.querySelectorAll('button, a, [role="button"], [role="link"]'));

                for (const el of controls) {
                    const text = (el.innerText || el.textContent || el.getAttribute('aria-label') || '').trim();
                    if (!text || !re.test(text)) continue;

                    const rect = el.getBoundingClientRect();
                    if (rect.width < 2 || rect.height < 2) continue;

                    el.scrollIntoView({block: 'center', inline: 'center'});
                    el.click();
                    return true;
                }

                return false;
            }
            """
        )
        if clicked:
            page.wait_for_timeout(1_200)
            print("  Clicked a Handshake results pagination/load-more control.")
            return True
    except Exception:
        pass

    return False


def _results_scroll_target_box(page: Page) -> dict | None:
    """Return the best visible scrollable element that contains job links."""

    try:
        box = page.evaluate(
            r"""
            () => {
                const jobSelector = "a[href*='/jobs/'], a[href*='/job/']";
                const candidates = Array.from(document.querySelectorAll('*'))
                    .filter(el => {
                        const rect = el.getBoundingClientRect();
                        if (rect.width < 120 || rect.height < 120) return false;
                        const style = window.getComputedStyle(el);
                        const overflow = `${style.overflowY} ${style.overflow}`;
                        const scrollable = /(auto|scroll|overlay)/i.test(overflow) && el.scrollHeight > el.clientHeight + 60;
                        if (!scrollable) return false;
                        return el.querySelectorAll(jobSelector).length > 0;
                    })
                    .map(el => {
                        const rect = el.getBoundingClientRect();
                        const links = el.querySelectorAll(jobSelector).length;
                        return {
                            x: rect.left,
                            y: rect.top,
                            width: rect.width,
                            height: rect.height,
                            links,
                            scrollTop: el.scrollTop,
                            scrollHeight: el.scrollHeight,
                            clientHeight: el.clientHeight,
                        };
                    })
                    .sort((a, b) => {
                        if (b.links !== a.links) return b.links - a.links;
                        return b.height - a.height;
                    });

                return candidates[0] || null;
            }
            """
        )
        return box or None
    except Exception:
        return None


def scroll_handshake_results_page(page: Page) -> None:
    """
    Handshake often puts job cards inside an inner virtual-list panel, not the
    document body. Scroll the job-link ancestors, move the mouse over the best
    result panel, use wheel/PageDown/End, and try any Load More/Next control.
    """

    try:
        page.evaluate(
            r"""
            () => {
                const jobSelector = "a[href*='/jobs/'], a[href*='/job/']";
                const targets = new Set();

                // Scroll ancestors of actual job cards first. This is the most
                // reliable way to advance Handshake's virtual list.
                for (const link of Array.from(document.querySelectorAll(jobSelector))) {
                    let el = link.parentElement;
                    let depth = 0;
                    while (el && depth < 12) {
                        const style = window.getComputedStyle(el);
                        const overflow = `${style.overflowY} ${style.overflow}`;
                        const scrollable = /(auto|scroll|overlay)/i.test(overflow) && el.scrollHeight > el.clientHeight + 60;
                        if (scrollable) targets.add(el);
                        el = el.parentElement;
                        depth += 1;
                    }
                }

                // Also consider large page regions that contain job links.
                for (const el of Array.from(document.querySelectorAll('main, [role="main"], section, aside, div'))) {
                    try {
                        const rect = el.getBoundingClientRect();
                        if (rect.width < 160 || rect.height < 180) continue;
                        if (!el.querySelector(jobSelector)) continue;
                        if (el.scrollHeight > el.clientHeight + 60) targets.add(el);
                    } catch (error) {}
                }

                targets.add(document.scrollingElement || document.documentElement);
                targets.add(document.body);

                for (const el of targets) {
                    try {
                        const amount = Math.max(900, Math.floor((el.clientHeight || window.innerHeight) * 0.9));
                        el.scrollTop = Math.min(el.scrollTop + amount, el.scrollHeight);
                    } catch (error) {}
                }

                window.scrollBy(0, Math.max(900, window.innerHeight * 0.9));
            }
            """
        )
    except Exception:
        pass

    # Mouse wheel only works if the pointer is over the correct scroll panel.
    box = _results_scroll_target_box(page)
    if box:
        try:
            x = max(5, box["x"] + min(box["width"] - 5, box["width"] * 0.5))
            y = max(5, box["y"] + min(box["height"] - 5, box["height"] * 0.75))
            page.mouse.move(x, y)
            page.mouse.wheel(0, 2600)
        except Exception:
            pass
    else:
        try:
            page.mouse.wheel(0, 2600)
        except Exception:
            pass

    try:
        page.keyboard.press("PageDown")
    except Exception:
        pass

    try:
        page.keyboard.press("End")
    except Exception:
        pass


def collect_handshake_job_links(
    page: Page,
    max_links: int | None = None,
    max_jobs: int | None = None,
    max_scrolls: int = 120,
    scroll_pause_ms: int = 1200,
) -> list[dict]:
    """
    Scroll/paginate the current Handshake search page and collect unique job links.

    This does not open or submit applications. It only builds the queue.
    """

    # Backward/forward compatible naming:
    # older callers used max_links; batch main.py calls max_jobs.
    if max_jobs is not None:
        max_links = max_jobs
    if max_links is None:
        max_links = 300

    print("\nCollecting Handshake job links for batch mode...")
    print(f"Target links: {max_links}")

    collected: dict[str, dict] = {}
    last_count = 0
    stagnant_scrolls = 0

    for scroll_number in range(1, max_scrolls + 1):
        links = find_job_links(page)

        for item in links:
            url = item.get("url")
            if not url:
                continue
            if url not in collected:
                collected[url] = item

        current_count = len(collected)
        print(f"  Scroll {scroll_number}/{max_scrolls}: {current_count} unique job links")

        if current_count >= max_links:
            break

        if current_count == last_count:
            stagnant_scrolls += 1
        else:
            stagnant_scrolls = 0

        # After repeated stagnant scrolls, try pagination/load-more once before
        # concluding that the current result set only contains this many jobs.
        if stagnant_scrolls in {8, 16, 24}:
            if _click_more_results_control(page):
                stagnant_scrolls = 0
                last_count = current_count
                continue

        if stagnant_scrolls >= 30:
            print("  No new jobs found after repeated inner-panel scrolling; stopping collection.")
            break

        last_count = current_count

        try:
            scroll_handshake_results_page(page)
            page.wait_for_timeout(scroll_pause_ms)
        except Exception:
            break

    links = list(collected.values())[:max_links]

    print(f"\n✓ Collected {len(links)} unique Handshake job links.")

    if len(links) < min(max_links, 25):
        print(
            "\n⚠ Only a small number of jobs were exposed by the current Handshake results page."
            "\n  Before pressing ENTER next time, broaden filters or click inside the results list"
            "\n  and press End/PageDown until Handshake visibly loads more cards."
        )

    return links



# ---------------------------------------------------------------------
# HANDSHAKE TRANSCRIPT UPLOAD SUPPORT
# ---------------------------------------------------------------------
# If a native Handshake application asks for "Attach your transcript",
# upload PROFILE["transcript"] before clicking Submit Application.

def _handshake_get_transcript_path():
    from pathlib import Path

    try:
        from src.profile import PROFILE
    except Exception:
        try:
            from profile import PROFILE
        except Exception:
            PROFILE = {}

    transcript = PROFILE.get("transcript")
    if not transcript:
        return None

    path = Path(transcript).expanduser().resolve()
    if not path.exists():
        print(f"✗ Transcript file not found: {path}")
        return None

    return path


def _handshake_transcript_required(page) -> bool:
    try:
        body = page.locator("body").inner_text(timeout=3000).lower()
    except Exception:
        return False

    return (
        "attach your transcript" in body
        or "search your transcripts" in body
        or "upload new" in body and "transcript" in body
    )


def _handshake_transcript_already_attached(page) -> bool:
    try:
        text = page.locator("body").inner_text(timeout=3000).lower()
    except Exception:
        return False

    return (
        "transcriptunofficial.pdf" in text
        or "transcript uploaded" in text
        or "preview document" in text and "transcript" in text
    )


def _handshake_upload_transcript_if_requested(page) -> bool:
    transcript_path = _handshake_get_transcript_path()

    if not transcript_path:
        return False

    if not _handshake_transcript_required(page):
        return False

    if _handshake_transcript_already_attached(page):
        print("✓ Transcript already appears attached")
        return True

    print("\n===== HANDSHAKE TRANSCRIPT UPLOAD =====")
    print(f"Transcript required. Uploading: {transcript_path.name}")

    # Try the visible "Upload new" button first.
    try:
        upload_button = page.get_by_role("button", name="Upload new").last

        with page.expect_file_chooser(timeout=5000) as fc_info:
            upload_button.click(timeout=5000)

        file_chooser = fc_info.value
        file_chooser.set_files(str(transcript_path))

        page.wait_for_timeout(3000)

        if _handshake_transcript_already_attached(page):
            print(f"✓ Transcript uploaded: {transcript_path.name}")
            return True

        print("⚠ Transcript file was sent, but attachment confirmation was not detected.")
        return True

    except Exception as exc:
        print(f"Upload-new file chooser did not work: {exc}")

    # Fallback: set any file input near the modal.
    try:
        file_inputs = page.locator('input[type="file"]')
        count = file_inputs.count()

        for i in range(count):
            try:
                file_inputs.nth(i).set_input_files(str(transcript_path), timeout=3000)
                page.wait_for_timeout(3000)

                if _handshake_transcript_already_attached(page):
                    print(f"✓ Transcript uploaded via file input: {transcript_path.name}")
                    return True
            except Exception:
                continue

    except Exception as exc:
        print(f"File-input transcript fallback failed: {exc}")

    print("✗ Could not upload transcript automatically.")
    return False


# Wrap the existing native Handshake submit function so transcript upload runs
# before the bot tries to submit the native application modal.
if "submit_handshake_native_application" in globals():
    if "_ORIGINAL_SUBMIT_HANDSHAKE_NATIVE_APPLICATION_WITHOUT_TRANSCRIPT" not in globals():
        _ORIGINAL_SUBMIT_HANDSHAKE_NATIVE_APPLICATION_WITHOUT_TRANSCRIPT = submit_handshake_native_application

    def submit_handshake_native_application(page, *args, **kwargs):
        _handshake_upload_transcript_if_requested(page)
        return _ORIGINAL_SUBMIT_HANDSHAKE_NATIVE_APPLICATION_WITHOUT_TRANSCRIPT(page, *args, **kwargs)


# ---------------------------------------------------------------------
# FINAL: HANDSHAKE TRANSCRIPT UPLOAD LIKE RESUME DROP
# ---------------------------------------------------------------------
# Native Handshake apply modals can require:
#   Attach your resume
#   Attach your transcript
#
# This uploads PROFILE["transcript"] when the modal asks for a transcript,
# then continues the normal native Handshake submit flow.

def _handshake_profile_transcript_path_final():
    from pathlib import Path

    try:
        from src.profile import PROFILE
    except Exception:
        try:
            from profile import PROFILE
        except Exception:
            PROFILE = {}

    transcript = PROFILE.get("transcript")

    if transcript:
        path = Path(transcript).expanduser().resolve()
        if path.exists():
            return path
        print(f"✗ PROFILE transcript path does not exist: {path}")

    # Fallback: find likely transcript PDF in documents folder.
    try:
        root = Path(__file__).resolve().parent.parent
        docs = root / "documents"
        candidates = list(docs.glob("*Transcript*.pdf")) + list(docs.glob("*transcript*.pdf"))
        for candidate in candidates:
            if candidate.exists():
                print(f"Using transcript fallback file: {candidate.name}")
                return candidate.resolve()
    except Exception:
        pass

    return None


def _handshake_transcript_required_final(page) -> bool:
    try:
        body = page.locator("body").inner_text(timeout=3000).lower()
    except Exception:
        return False

    return (
        "attach your transcript" in body
        or "search your transcripts" in body
    )


def _handshake_transcript_attached_final(page, transcript_path=None) -> bool:
    try:
        body = page.locator("body").inner_text(timeout=3000).lower()
    except Exception:
        return False

    names = []

    if transcript_path is not None:
        try:
            names.append(transcript_path.name.lower())
        except Exception:
            pass

    names.extend([
        "transcriptunofficial.pdf",
        "guzmansample_transcript.pdf",
        "transcript.pdf",
    ])

    # Important: do NOT treat "Preview document" as transcript attached,
    # because that can be the resume preview.
    return any(name in body for name in names)


def _handshake_click_transcript_upload_new_final(page) -> bool:
    js = r"""
    () => {
      function norm(s) {
        return (s || "").replace(/\s+/g, " ").trim().toLowerCase();
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

      const all = Array.from(document.querySelectorAll("body *")).filter(visible);

      let transcriptLabel = null;

      for (const el of all) {
        const text = norm(el.innerText || el.textContent || "");
        if (text === "attach your transcript") {
          transcriptLabel = el;
          break;
        }
      }

      if (!transcriptLabel) {
        for (const el of all) {
          const text = norm(el.innerText || el.textContent || "");
          if (text.includes("attach your transcript") && text.length < 300) {
            transcriptLabel = el;
            break;
          }
        }
      }

      if (!transcriptLabel) {
        return { ok: false, reason: "Attach your transcript label not found" };
      }

      const labelRect = transcriptLabel.getBoundingClientRect();

      const buttons = all
        .filter(el => norm(el.innerText || el.textContent || "") === "upload new")
        .map(el => ({ el, rect: el.getBoundingClientRect() }))
        .filter(item => {
          const r = item.rect;

          // Pick Upload new below the transcript label, close to that section.
          return (
            r.top >= labelRect.top - 10 &&
            r.top <= labelRect.top + 260
          );
        })
        .sort((a, b) => {
          if (Math.abs(a.rect.top - b.rect.top) > 10) {
            return a.rect.top - b.rect.top;
          }
          return a.rect.left - b.rect.left;
        });

      if (!buttons.length) {
        return { ok: false, reason: "Upload new button near transcript not found" };
      }

      buttons[0].el.scrollIntoView({ block: "center" });
      buttons[0].el.click();

      return { ok: true };
    }
    """

    try:
        result = page.evaluate(js)
        if isinstance(result, dict) and result.get("ok"):
            return True

        print(f"Transcript Upload new click failed: {result}")
        return False
    except Exception as exc:
        print(f"Transcript Upload new click error: {exc}")
        return False


def _handshake_upload_transcript_like_resume_final(page) -> bool:
    transcript_path = _handshake_profile_transcript_path_final()

    if not transcript_path:
        print("✗ No transcript PDF found/configured.")
        return False

    if not _handshake_transcript_required_final(page):
        return False

    if _handshake_transcript_attached_final(page, transcript_path):
        print("✓ Transcript already attached")
        return True

    print("\n===== HANDSHAKE TRANSCRIPT UPLOAD =====")
    print(f"Transcript required. Uploading: {transcript_path.name}")

    # Method 1: click transcript Upload new and handle file chooser.
    try:
        with page.expect_file_chooser(timeout=8000) as chooser_info:
            clicked = _handshake_click_transcript_upload_new_final(page)
            if not clicked:
                raise RuntimeError("Transcript Upload new button was not clicked")

        chooser = chooser_info.value
        chooser.set_files(str(transcript_path))

        page.wait_for_timeout(5000)

        if _handshake_transcript_attached_final(page, transcript_path):
            print(f"✓ Transcript uploaded: {transcript_path.name}")
            return True

        print("⚠ Transcript file chooser accepted file, but attachment confirmation was not detected.")
        return True

    except Exception as exc:
        print(f"Transcript file chooser method failed: {exc}")

    # Method 2: click transcript Upload new, then set newest file input.
    try:
        _handshake_click_transcript_upload_new_final(page)
        page.wait_for_timeout(1500)

        inputs = page.locator('input[type="file"]')
        count = inputs.count()

        print(f"Found {count} file input(s) after transcript Upload new.")

        for i in reversed(range(count)):
            try:
                inputs.nth(i).set_input_files(str(transcript_path), timeout=5000)
                page.wait_for_timeout(5000)

                if _handshake_transcript_attached_final(page, transcript_path):
                    print(f"✓ Transcript uploaded via file input: {transcript_path.name}")
                    return True
            except Exception:
                continue

    except Exception as exc:
        print(f"Transcript file-input method failed: {exc}")

    print("✗ Could not upload transcript automatically.")
    return False


# Override native Handshake submit so transcript upload runs before submit.
# This bypasses any earlier experimental required-doc guard if it was pasted.
if "submit_handshake_native_application" in globals():
    if "_HANDSHAKE_NATIVE_SUBMIT_BASE_FOR_TRANSCRIPT_FINAL" not in globals():
        _HANDSHAKE_NATIVE_SUBMIT_BASE_FOR_TRANSCRIPT_FINAL = (
            globals().get("_ORIGINAL_SUBMIT_HANDSHAKE_NATIVE_APPLICATION_WITHOUT_TRANSCRIPT")
            or globals().get("_ORIGINAL_SUBMIT_HANDSHAKE_NATIVE_APPLICATION_REQUIRED_DOC_GUARD")
            or submit_handshake_native_application
        )

    def submit_handshake_native_application(page, *args, **kwargs):
        _handshake_upload_transcript_like_resume_final(page)
        return _HANDSHAKE_NATIVE_SUBMIT_BASE_FOR_TRANSCRIPT_FINAL(page, *args, **kwargs)


# ---------------------------------------------------------------------
# FINAL OVERRIDE: OpenAI recovery-agent before native Handshake submit
# ---------------------------------------------------------------------
# This is the stable integration point.  It avoids stacking older transcript
# wrappers by calling the original native submit function after recovery.
# The recovery agent may upload configured resume/transcript files and fill
# safe known fields. It will not invent other required documents.

if "_HANDSHAKE_NATIVE_SUBMIT_BASE_RECOVERY_AGENT" not in globals():
    _HANDSHAKE_NATIVE_SUBMIT_BASE_RECOVERY_AGENT = (
        globals().get("_ORIGINAL_SUBMIT_HANDSHAKE_NATIVE_APPLICATION_WITHOUT_TRANSCRIPT")
        or globals().get("_HANDSHAKE_NATIVE_SUBMIT_BASE_FOR_TRANSCRIPT_FINAL")
        or globals().get("_ORIGINAL_SUBMIT_HANDSHAKE_NATIVE_APPLICATION_REQUIRED_DOC_GUARD")
        or submit_handshake_native_application
    )


def submit_handshake_native_application(page: Page) -> bool:
    title = "Handshake application"
    company = "Handshake"

    try:
        title = get_job_title(page)
    except Exception:
        pass

    try:
        company = company_from_apply_dialog(page) or get_company_name(page)
    except Exception:
        pass

    try:
        from src.recovery_agent import run_recovery_agent

        run_recovery_agent(
            page,
            context="handshake_before_native_submit",
            company=company,
            title=title,
        )
    except Exception as exc:
        print(f"  ⚠ Recovery agent failed safely before Handshake submit: {exc}")

    return _HANDSHAKE_NATIVE_SUBMIT_BASE_RECOVERY_AGENT(page)
