from __future__ import annotations

import html
import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from src.greenhouse import fill_greenhouse_application
from src.handshake import (
    discover_handshake_jobs,
    open_handshake,
    print_discovery_summary,
)
from src.web_apply_agent import run_web_apply_agent
from src.paid_remote_guard import install_verified_paid_remote_guard

# Enforce remote eligibility inside Handshake discovery, before opening any application.
install_verified_paid_remote_guard()


ROOT = Path(__file__).resolve().parent
# Apply configured marketing resume across site agents at runtime, without changing
# the user's profile.py or bundling personal files into this patch.
MARKETING_RESUME = ROOT / "documents" / "SampleApplicant_Market_Resume.pdf"
if MARKETING_RESUME.is_file():
    from src.profile import PROFILE
    PROFILE["resume"] = MARKETING_RESUME
    print("Marketing resume selected:", MARKETING_RESUME.name)
else:
    raise RuntimeError("Missing marketing resume: documents/SampleApplicant_Market_Resume.pdf")
BROWSER_DATA = ROOT / "browser-data"


# ============================================================
# BATCH SETTINGS
# ============================================================

def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


APPLICATION_TARGET = int(os.getenv("APPLICATION_TARGET", "50"))
DISCOVERY_MAX_JOBS = int(os.getenv("DISCOVERY_MAX_JOBS", "120"))
FAST_BATCH_MODE = env_flag("FAST_BATCH_MODE", False)
COUNT_RESOLVED_EXTERNAL_AS_DONE = False  # Confirmed submissions only

# Run the actual application batch in a hidden Playwright browser so it does
# not steal focus or interrupt your normal Chrome tabs.
#
# BACKGROUND_BROWSER=true:
#   - opens one visible setup window only if HANDSHAKE_START_URL is not given
#   - after you configure the Handshake search and press Enter, it closes that
#     setup window and reopens the same logged-in profile in headless mode
#   - all scanning/filling/submitting happens hidden in the background
#
# HEADLESS=true:
#   - fully hidden from the start; best used with HANDSHAKE_START_URL=<saved search URL>
BACKGROUND_BROWSER = env_flag("BACKGROUND_BROWSER", False)
HEADLESS = env_flag("HEADLESS", False)

# Important: true headless mode can make Handshake expose 0 results or a
# "Just a moment" page. By default BACKGROUND_BROWSER now runs in a headed
# off-screen/minimized browser instead of true headless. This keeps the bot out
# of your way while preserving normal site behavior. Set BACKGROUND_HEADLESS=true
# only if the target site works in headless mode.
BACKGROUND_HEADLESS = env_flag("BACKGROUND_HEADLESS", False)
BACKGROUND_WINDOW_OFFSCREEN = env_flag("BACKGROUND_WINDOW_OFFSCREEN", True)

SLOW_MO_MS = int(os.getenv("SLOW_MO_MS", "0" if (BACKGROUND_BROWSER or HEADLESS) else "75"))

# Auto-start Handshake search so you do not have to click Jobs and type the
# search phrase on every run. Set AUTO_HANDSHAKE_SEARCH=false to restore the
# old manual setup flow.
AUTO_HANDSHAKE_SEARCH = env_flag("AUTO_HANDSHAKE_SEARCH", True)
HANDSHAKE_QUERY = os.getenv("HANDSHAKE_QUERY", "Remote Marketing Internship").strip()
HANDSHAKE_SEARCH_URL = os.getenv("HANDSHAKE_SEARCH_URL", "https://app.joinhandshake.com/job-search").strip()

# Best-effort UI filter. When enabled, the bot opens the Handshake Filters menu
# and checks the Paid compensation option before collecting job cards.
# HANDSHAKE_SKIP_UNPAID remains a second safety net at the individual job page.
HANDSHAKE_FILTER_PAID = (
    env_flag("HANDSHAKE_FILTER_PAID", False)
    or env_flag("HANDSHAKE_REQUIRE_PAID", False)
    or env_flag("HANDSHAKE_SKIP_UNPAID", False)
)

# Show a Mac popup when the hidden/background run finishes so you know it is done.
# Set COMPLETION_POPUP=false to disable.
COMPLETION_POPUP = env_flag("COMPLETION_POPUP", True)

# After a hidden/background run, reopen unfinished applications in a visible
# review browser so you can manually inspect/submit the leftovers.
# This is enabled by default because headless tabs cannot be brought to front.
REVIEW_BROWSER_ON_FINISH = env_flag("REVIEW_BROWSER_ON_FINISH", False)
REVIEW_MAX_TABS = int(os.getenv("REVIEW_MAX_TABS", "40"))

# Open every application/job the bot touched, not just leftovers. This makes the
# final visible review browser useful as an audit trail. Set to false if you
# only want unresolved tabs.
REVIEW_OPEN_ALL_WORKED = env_flag("REVIEW_OPEN_ALL_WORKED", False)
REVIEW_OPEN_SUBMITTED = env_flag("REVIEW_OPEN_SUBMITTED", False)

# These are slow or verification-heavy in bulk mode. They are better handled
# separately after the high-volume Handshake/Greenhouse run finishes.
BAD_EXTERNAL_DOMAINS = {
    "successfactors",
    "workday",
    "icims",
    "jobvite",
}

# Keep Cargill out of normal batch runs unless you explicitly remove it or set
# SKIP_COMPANIES yourself.
DEFAULT_SKIP_COMPANIES = {"cargill"}


# ============================================================
# DISPLAY
# ============================================================

def print_header() -> None:
    print("=" * 68)
    print("             ENRIQUE'S JOB APPLICATION ASSISTANT")
    print("=" * 68)


def _applescript_string(value: str) -> str:
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"') + '"'


def completion_popup(message: str) -> None:
    """Show a macOS popup when the batch is finished.

    This is intentionally best-effort: if osascript is unavailable or blocked,
    the batch still completes normally and the terminal summary remains intact.
    """
    if not COMPLETION_POPUP:
        return

    message = (message or "This ran!").strip()
    if not message.lower().startswith("this ran"):
        message = f"This ran!\n\n{message}"

    print(f"\n🔔 Completion popup: {message.replace(chr(10), ' | ')}")

    osascript = Path("/usr/bin/osascript")
    if not osascript.exists():
        return

    script = (
        f"display dialog {_applescript_string(message)} "
        f"with title {_applescript_string('Resume Filler Finished')} "
        "buttons {\"OK\"} default button \"OK\" giving up after 120"
    )

    try:
        subprocess.run(
            [str(osascript), "-e", script],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=125,
        )
    except Exception:
        pass


# ============================================================
# PLATFORM DETECTION
# ============================================================

def detect_platform(url: str) -> str:
    url_lower = str(url or "").lower()

    if "greenhouse.io" in url_lower:
        return "greenhouse"

    if any(marker in url_lower for marker in [
        "successfactors",
        "workday",
        "ashbyhq",
        "lever.co",
        "smartrecruiters",
        "icims",
        "jobvite",
        "careers.",
        "jobs.",
        "/career",
        "/careers",
        "/job/",
        "/jobs/",
        "/talentcommunity",
    ]):
        return "external_site"

    return "external_site"


# ============================================================
# BATCH HELPERS
# ============================================================

def _norm(value) -> str:
    return str(value or "").strip().lower()


def load_skip_companies() -> set[str]:
    skipped = set(DEFAULT_SKIP_COMPANIES)

    env_value = os.getenv("SKIP_COMPANIES", "")
    for item in env_value.split(","):
        item = item.strip().lower()
        if item:
            skipped.add(item)

    skip_file = ROOT / "data" / "skip_companies.txt"
    if skip_file.exists():
        for line in skip_file.read_text(errors="ignore").splitlines():
            item = line.strip().lower()
            if item and not item.startswith("#"):
                skipped.add(item)

    return skipped


def company_is_skipped(job, skipped_companies: set[str]) -> bool:
    company = _norm(getattr(job, "company", ""))
    if not company:
        return False
    return any(skipped in company for skipped in skipped_companies)


def looks_like_bad_external(job) -> bool:
    url = _norm(getattr(job, "application_url", ""))
    company = _norm(getattr(job, "company", ""))
    host = _norm(urlparse(url).netloc)
    combined = f"{host} {url} {company}"

    return any(marker in combined for marker in BAD_EXTERNAL_DOMAINS)


def is_handshake_submitted(job) -> bool:
    return getattr(job, "application_type", None) == "handshake_submitted"


def count_handshake_submitted(jobs) -> int:
    return len([job for job in jobs if is_handshake_submitted(job)])


# ============================================================
# APPLICATION JOB SELECTION
# ============================================================

def get_external_application_jobs(jobs, remaining_target: int | None = None):
    selected = []
    seen = set()
    skipped_companies = load_skip_companies()

    for job in jobs:
        if remaining_target is not None and len(selected) >= remaining_target:
            break

        if not getattr(job, "application_url", None):
            continue

        if job.application_type not in {
            "external_greenhouse",
            "external_other",
            "external_unknown",
        }:
            continue

        if company_is_skipped(job, skipped_companies):
            print(f"  Skipping company in skip list: {job.company} — {job.title}")
            continue

        if FAST_BATCH_MODE:
            # Greenhouse is usually fast and reliable, so keep it.
            if job.application_type == "external_greenhouse":
                pass
            # Bad external ATS sites are skipped in high-volume mode.
            elif looks_like_bad_external(job):
                print(f"  Skipping slow external ATS in fast batch: {job.company} — {job.title}")
                continue
            # Generic external ATS sites are left for manual/review mode.
            else:
                print(f"  Skipping generic external site in fast batch: {job.company} — {job.title}")
                continue

        if job.application_url in seen:
            continue

        seen.add(job.application_url)
        selected.append(job)

    return selected


def completed_count(handshake_submitted_count: int, results: dict[str, int]) -> int:
    total = handshake_submitted_count + results.get("submitted", 0)
    return total


# ============================================================
# GREENHOUSE / AGENTIC EXTERNAL PROCESSING
# ============================================================

def process_application(
    page,
    job,
    number: int,
    total: int,
) -> str:
    url = job.application_url
    title = job.title
    company = job.company

    print("\n" + "=" * 68)
    print(f"APPLICATION {number}/{total}")
    print("=" * 68)

    print(f"\nOpening application in its own tab:\n{url}\n")

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    except Exception as exc:
        print(f"✗ Could not open application: {exc}")
        return "failed"

    try:
        page.wait_for_load_state("networkidle", timeout=15_000)
    except Exception:
        pass

    try:
        page.wait_for_timeout(800)
    except Exception:
        pass

    try:
        page_title = page.title()
    except Exception:
        page_title = "Unknown"

    try:
        current_url = page.url
    except Exception:
        current_url = url

    print(f"Target job: {company} — {title}")
    print(f"Title:      {page_title}")
    print(f"URL:        {current_url}")

    platform = detect_platform(current_url)
    print(f"Platform:   {platform}")

    # --------------------------------------------------------
    # AI-FIRST WEB APPLY AGENT
    # --------------------------------------------------------
    # This replaces the old stack of per-site patches. The agent observes the
    # actual browser state, chooses one safe primitive action, executes it, and
    # repeats until it reaches Greenhouse, an external final-review step, a
    # verification/manual boundary, or a missing-document boundary.

    if platform != "greenhouse":
        try:
            agent_result = run_web_apply_agent(
                page,
                target_title=title,
                target_company=company,
            )
        except Exception as exc:
            print(f"\n✗ Web apply agent crashed: {exc}")
            return "failed"

        print(f"\n✓ Web apply agent result: {agent_result.method}")
        print(f"  {agent_result.reason}")
        try:
            current_after_agent = page.url
        except Exception:
            current_after_agent = agent_result.url or ""
        print(f"  Current URL: {current_after_agent}")

        platform = detect_platform(current_after_agent)
        print(f"Platform after web agent: {platform}")

        if platform != "greenhouse":
            print("\n✓ Reached the furthest safe external application step.")
            print("External ATS final submit is disabled, so this tab remains open for review.")
            return "resolved_external" if agent_result.ok else "failed"

    # Fail safe: the installed Greenhouse module has legacy submit-to-verification
    # wrappers. Do not invoke them from a review-only remote internship run.
    if env_flag("REMOTE_GUARD_GREENHOUSE_REVIEW_ONLY", True):
        print("Greenhouse form reserved for manual review (legacy auto-submit code blocked).")
        return "resolved_external"

    # --------------------------------------------------------
    # GREENHOUSE AUTOFILL
    # --------------------------------------------------------

    try:
        page.wait_for_selector("#first_name", state="visible", timeout=15_000)
    except Exception:
        print("\n✗ Greenhouse detected, but the application form could not be found.")
        return "failed"

    try:
        fill_greenhouse_application(page)
    except Exception as exc:
        print("\n✗ Autofill encountered an error:" f"\n{exc}")
        return "failed"

    # Some Greenhouse flows require an emailed verification code and then land
    # on a thank-you page. Treat that as a confirmed submission instead of only
    # "filled", so the summary/report is honest.
    submitted_markers = []
    try:
        submitted_markers.append(page.title())
    except Exception:
        pass
    try:
        submitted_markers.append(page.url)
    except Exception:
        pass
    submitted_text = " ".join(str(x or "") for x in submitted_markers).lower()

    if any(marker in submitted_text for marker in ["thank you", "thanks for applying", "application submitted"]):
        print("\n✓ APPLICATION SUBMITTED")
        print("✓ Submission confirmation/thank-you page detected")
        return "submitted"

    print("\n✓ APPLICATION FILLED")
    print("✓ This tab will remain open")
    print("🚫 Application was NOT submitted unless your Greenhouse verification flow is enabled")

    return "filled"


# ============================================================
# BROWSER LAUNCH
# ============================================================

def launch_browser_context(p, *, headless: bool, background: bool = False):
    """Launch the persistent application browser.

    This project uses a separate Chrome-for-Testing profile under
    ./browser-data, not your everyday Chrome profile. True headless mode can
    break Handshake, so BACKGROUND_BROWSER defaults to a headed browser that is
    minimized/off-screen instead of stealing focus.
    """
    args = []
    if background and not headless and BACKGROUND_WINDOW_OFFSCREEN:
        args.extend([
            "--start-minimized",
            "--window-position=-30000,-30000",
            "--window-size=1440,1000",
        ])

    return p.chromium.launch_persistent_context(
        user_data_dir=str(BROWSER_DATA),
        headless=headless,
        slow_mo=0 if (headless or background) else SLOW_MO_MS,
        viewport={"width": 1440, "height": 1000},
        args=args,
    )


def first_or_new_page(context):
    pages = context.pages
    return pages[0] if pages else context.new_page()



# ============================================================
# HANDSHAKE AUTO SEARCH SETUP
# ============================================================

def _wait_briefly(page, ms: int = 800) -> None:
    try:
        page.wait_for_timeout(ms)
    except Exception:
        pass


def _click_handshake_jobs_nav(page) -> bool:
    """Best-effort click on the Handshake Jobs nav if direct URL is not enough."""
    candidates = [
        lambda: page.get_by_role("link", name="Jobs"),
        lambda: page.get_by_text("Jobs", exact=True),
        lambda: page.locator("a[href*='job-search']"),
        lambda: page.locator("a[href*='/jobs']"),
    ]

    for make_locator in candidates:
        try:
            loc = make_locator()
            if loc.count() > 0 and loc.first.is_visible():
                loc.first.click(timeout=4_000)
                _wait_briefly(page, 1200)
                return True
        except Exception:
            continue
    return False


def _find_handshake_search_box(page):
    """Return the visible Handshake job search input/textarea if available."""
    selectors = [
        "input[placeholder*='Describe a job']",
        "textarea[placeholder*='Describe a job']",
        "input[placeholder*='Search']",
        "textarea[placeholder*='Search']",
        "input[aria-label*='Search' i]",
        "textarea[aria-label*='Search' i]",
        "input[type='search']",
        "input[name*='query' i]",
    ]

    for selector in selectors:
        try:
            loc = page.locator(selector)
            count = loc.count()
        except Exception:
            continue

        for i in range(count):
            try:
                candidate = loc.nth(i)
                if candidate.is_visible() and candidate.is_enabled():
                    return candidate
            except Exception:
                continue

    # Handshake sometimes wraps the input in a combobox-like widget. Use the
    # role locator only as a fallback because it can match unrelated controls.
    for role in ("combobox", "searchbox", "textbox"):
        try:
            loc = page.get_by_role(role)
            count = loc.count()
        except Exception:
            continue
        for i in range(min(count, 8)):
            try:
                candidate = loc.nth(i)
                if candidate.is_visible() and candidate.is_enabled():
                    return candidate
            except Exception:
                continue

    return None


def _set_handshake_search_query(page, query: str) -> bool:
    query = str(query or "").strip()
    if not query:
        return False

    search_box = _find_handshake_search_box(page)
    if search_box is None:
        return False

    try:
        search_box.click(timeout=5_000)
        _wait_briefly(page, 150)
    except Exception:
        pass

    # Use keyboard replacement first because React/Handshake search controls
    # sometimes ignore direct fill() until the input has focus.
    try:
        page.keyboard.press("Meta+A")
        page.keyboard.type(query, delay=8)
        page.keyboard.press("Enter")
        _wait_briefly(page, 2500)
        return True
    except Exception:
        pass

    try:
        search_box.fill(query, timeout=5_000)
        page.keyboard.press("Enter")
        _wait_briefly(page, 2500)
        return True
    except Exception:
        return False


def _dismiss_handshake_overlays(page) -> None:
    """Close common Handshake banners/modals that can block scrolling."""
    for text in ["Maybe later", "Not now", "No thanks", "Skip", "Close"]:
        try:
            loc = page.get_by_role("button", name=text)
            if loc.count() > 0 and loc.first.is_visible():
                loc.first.click(timeout=1500)
                _wait_briefly(page, 250)
        except Exception:
            pass
    # Close icon buttons on banners like "Get alerts for jobs like this".
    try:
        buttons = page.locator("button[aria-label*='close' i], button[aria-label*='dismiss' i]")
        for i in range(min(buttons.count(), 4)):
            try:
                if buttons.nth(i).is_visible():
                    buttons.nth(i).click(timeout=1000)
                    _wait_briefly(page, 200)
            except Exception:
                continue
    except Exception:
        pass



def _apply_handshake_paid_filter(page) -> bool:
    """Best-effort click of Handshake's Filters -> Paid option.

    Handshake changes its DOM often, so this uses multiple safe selectors and
    never treats failure as fatal. HANDSHAKE_SKIP_UNPAID should still be enabled
    as a second layer, because a UI filter can fail or Handshake may still show
    unpaid promoted/sponsored results.
    """
    print("\nApplying Handshake paid filter...")
    _dismiss_handshake_overlays(page)

    opened_filters = False
    filter_locators = [
        lambda: page.get_by_role("button", name="Filters"),
        lambda: page.locator("button:has-text('Filters')"),
        lambda: page.get_by_text("Filters", exact=True),
        lambda: page.locator("[aria-label*='Filters' i]"),
    ]

    for make_locator in filter_locators:
        try:
            loc = make_locator()
            count = loc.count()
        except Exception:
            continue
        for i in range(min(count, 4)):
            try:
                candidate = loc.nth(i)
                if candidate.is_visible() and candidate.is_enabled():
                    candidate.click(timeout=4_000)
                    opened_filters = True
                    _wait_briefly(page, 900)
                    break
            except Exception:
                continue
        if opened_filters:
            break

    if not opened_filters:
        print("  ⚠ Could not open Handshake Filters automatically; unpaid page-level skip is still active if configured.")
        return False

    try:
        result = page.evaluate(
            r"""
            () => {
              const norm = (s) => String(s || '').replace(/\s+/g, ' ').trim();
              const visible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) return false;
                const rect = el.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
              };

              const roots = Array.from(document.querySelectorAll(
                '[role="dialog"], [aria-modal="true"], aside, [data-testid*="filter" i], [class*="filter" i]'
              )).filter(visible);
              const scope = roots.length ? roots[roots.length - 1] : document.body;
              const items = Array.from(scope.querySelectorAll(
                'input[type="checkbox"], input[type="radio"], label, button, [role="checkbox"], [role="radio"], [role="option"], span, div'
              )).filter(visible);

              for (const el of items) {
                const pieces = [
                  el.getAttribute && el.getAttribute('aria-label'),
                  el.getAttribute && el.getAttribute('title'),
                  el.innerText || el.textContent,
                  el.value,
                  el.name,
                ];
                const text = norm(pieces.filter(Boolean).join(' '));
                if (!text || text.length > 120) continue;
                if (!/\bpaid\b/i.test(text)) continue;
                if (/\bunpaid\b/i.test(text)) continue;

                const tag = (el.tagName || '').toLowerCase();
                const role = (el.getAttribute && el.getAttribute('role') || '').toLowerCase();
                const input = tag === 'input'
                  ? el
                  : (el.querySelector && el.querySelector('input[type="checkbox"], input[type="radio"]'));

                if (input) {
                  if (!input.checked) input.click();
                  return { clicked: true, target: text, kind: 'input', rootCount: roots.length };
                }

                const target = el.closest && el.closest('label, button, [role="checkbox"], [role="radio"], [role="option"]') || el;
                const checked = (target.getAttribute && target.getAttribute('aria-checked') || '').toLowerCase();
                if (checked !== 'true') target.click();
                return { clicked: true, target: text, kind: role || tag || 'element', rootCount: roots.length };
              }

              return { clicked: false, rootCount: roots.length };
            }
            """
        )
    except Exception as exc:
        print(f"  ⚠ Could not click Paid option automatically: {exc}")
        result = {"clicked": False}

    if not isinstance(result, dict) or not result.get("clicked"):
        print("  ⚠ Could not locate the Paid compensation option inside Filters.")
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        return False

    print(f"  ✓ Checked Paid filter option: {result.get('target', 'Paid')}")

    # Some Handshake filter panels apply instantly; others require a button.
    for name in ["Show results", "Show Results", "View results", "Apply filters", "Apply", "Done"]:
        try:
            loc = page.get_by_role("button", name=name)
            if loc.count() > 0 and loc.first.is_visible() and loc.first.is_enabled():
                loc.first.click(timeout=3_000)
                print(f"  ✓ Applied filters with: {name}")
                _wait_briefly(page, 2200)
                return True
        except Exception:
            continue

    try:
        page.keyboard.press("Escape")
    except Exception:
        pass
    _wait_briefly(page, 1800)
    print("  ✓ Paid filter selected; closed Filters panel.")
    return True

def open_handshake_for_batch(page) -> None:
    """Open Handshake and, by default, navigate to Jobs and run the saved search.

    This replaces the old setup step where you had to manually click Jobs and
    type the search every run. It still uses the existing open_handshake()
    function when AUTO_HANDSHAKE_SEARCH=false.
    """
    if not AUTO_HANDSHAKE_SEARCH:
        open_handshake(page)
        return

    print("\n" + "=" * 68)
    print("HANDSHAKE DISCOVERY")
    print("=" * 68)
    print("\nOpening Handshake Jobs search automatically...")

    start_url = os.getenv("HANDSHAKE_START_URL", "").strip()
    target_url = start_url or HANDSHAKE_SEARCH_URL or "https://app.joinhandshake.com/job-search"

    try:
        page.goto(target_url, wait_until="domcontentloaded", timeout=60_000)
    except Exception as exc:
        print(f"⚠ Could not open Handshake search URL directly: {exc}")
        try:
            page.goto("https://app.joinhandshake.com/home", wait_until="domcontentloaded", timeout=60_000)
        except Exception:
            pass

    try:
        page.wait_for_load_state("networkidle", timeout=10_000)
    except Exception:
        pass

    _dismiss_handshake_overlays(page)

    # If Handshake lands on Home or a generic page, click Jobs. If direct
    # navigation worked, this is harmless and usually skipped.
    try:
        current_url = page.url.lower()
    except Exception:
        current_url = ""
    if "job-search" not in current_url and "/jobs" not in current_url:
        _click_handshake_jobs_nav(page)
        _dismiss_handshake_overlays(page)

    # Make sure we are on a search page. This works even if the left nav click
    # did not fire because the profile is already authenticated.
    try:
        current_url = page.url.lower()
    except Exception:
        current_url = ""
    if "job-search" not in current_url and "joinhandshake.com" in current_url:
        try:
            page.goto(HANDSHAKE_SEARCH_URL or "https://app.joinhandshake.com/job-search", wait_until="domcontentloaded", timeout=60_000)
            try:
                page.wait_for_load_state("networkidle", timeout=10_000)
            except Exception:
                pass
        except Exception:
            pass

    _dismiss_handshake_overlays(page)

    if HANDSHAKE_QUERY:
        print(f"Search query: {HANDSHAKE_QUERY}")
        if _set_handshake_search_query(page, HANDSHAKE_QUERY):
            print("✓ Entered Handshake search query automatically")
        else:
            print("⚠ Could not find the Handshake search box automatically; using the current page as-is")

    _dismiss_handshake_overlays(page)

    if HANDSHAKE_FILTER_PAID:
        _apply_handshake_paid_filter(page)
        _dismiss_handshake_overlays(page)

    print("\nEach discovered job will get its OWN tab.")
    if env_flag("HANDSHAKE_DRAFT_ONLY", False) or env_flag("HANDSHAKE_REVIEW_ONLY", False) or env_flag("NO_AUTO_SUBMIT", False):
        print("Native Handshake applications will be prepared for review only; Submit Application will NOT be clicked.")
    else:
        print("Native Handshake resume drops will auto-submit once required fields are complete.")
    print("External applications and Greenhouse forms still remain manual at final submit.")

    # Give React/Handshake a moment to render cards after the search.
    _wait_briefly(page, 1800)

# ============================================================
# REVIEW BROWSER
# ============================================================

def _safe_page_url(page, fallback: str = "") -> str:
    try:
        url = page.url
        if url and url not in {"about:blank", "about:srcdoc"}:
            return url
    except Exception:
        pass
    return fallback or ""


def _add_review_item(items: list[dict], seen: set[str], *, url: str, title: str, company: str, status: str) -> None:
    url = str(url or "").strip()
    if not url or url in {"about:blank", "about:srcdoc"}:
        return
    if url in seen:
        return
    seen.add(url)
    items.append({
        "url": url,
        "title": str(title or "Unknown job"),
        "company": str(company or "Unknown company"),
        "status": str(status or "needs_review"),
    })


def _job_review_url(job, status: str = "") -> str:
    """Best-effort URL extraction for a discovered Handshake job.

    Different patch versions have used slightly different field names. Use the
    external application URL for external jobs, otherwise reopen the Handshake
    job URL so the user can inspect/finish native or unknown applications.
    """
    status = str(status or getattr(job, "application_type", "") or "").lower()

    preferred_attrs = []
    if status.startswith("external"):
        preferred_attrs.extend(["application_url", "external_url", "destination_url"])
    preferred_attrs.extend([
        "handshake_url",
        "job_url",
        "url",
        "link",
        "application_url",
        "external_url",
        "destination_url",
    ])

    for attr in preferred_attrs:
        try:
            value = getattr(job, attr, None)
        except Exception:
            value = None
        value = str(value or "").strip()
        if value and value not in {"about:blank", "about:srcdoc"}:
            return value

    return ""


def _collect_context_page_items(context) -> list[dict]:
    """Capture currently-open hidden pages before closing the headless context."""
    items: list[dict] = []
    seen: set[str] = set()

    try:
        pages = list(context.pages)
    except Exception:
        pages = []

    for index, page in enumerate(pages, start=1):
        url = _safe_page_url(page)
        if not url:
            continue
        try:
            title = page.title()
        except Exception:
            title = f"Open hidden tab {index}"

        _add_review_item(
            items,
            seen,
            url=url,
            title=title or f"Open hidden tab {index}",
            company="Review",
            status="open_hidden_tab",
        )

    return items


def collect_review_items(jobs=None, application_tabs=None, context=None) -> list[dict]:
    """Collect URLs that should be reopened visibly after a hidden run.

    Important: headless tabs cannot be brought forward. To review leftovers, we
    reopen their URLs in a new visible persistent browser. This function is
    intentionally broad: if a job was not confirmed submitted, it should be
    reopenable for inspection instead of silently disappearing.
    """
    items: list[dict] = []
    seen: set[str] = set()

    # Fail closed: only verified, explicitly eligible application states enter review.
    # 'REVIEW_OPEN_ALL_WORKED' must NEVER override a screening rejection.
    allowed_review_statuses = {
        "handshake_ready_manual", "handshake_submit_uncertain",
        "handshake_screening_required", "screening_required",
        "external_other", "external_greenhouse", "external_unknown",
    }
    for job in jobs or []:
        status = str(getattr(job, "application_type", "") or "").lower()
        if status not in allowed_review_statuses:
            continue
        url = _job_review_url(job, status=status)
        _add_review_item(
            items, seen, url=url,
            title=getattr(job, "title", "Unknown job"),
            company=getattr(job, "company", "Unknown company"),
            status=status,
        )

    # Only keep application pages associated with an eligible, discovered job.
    # Never blindly reopen every Playwright context tab: that resurrects skips.
    eligible_urls = {
        _job_review_url(job, status=str(getattr(job, "application_type", "") or ""))
        for job in jobs or []
        if str(getattr(job, "application_type", "") or "").lower()
        in allowed_review_statuses
    }
    eligible_jobs = {id(job) for job in jobs or [] if
        str(getattr(job, "application_type", "") or "").lower()
        in allowed_review_statuses}
    for application in application_tabs or []:
        job = application.get("job")
        status = str(application.get("status", "") or "").lower()
        if not job or id(job) not in eligible_jobs:
            continue
        if status.startswith("skip") or status in {"unpaid", "ineligible", "rejected", "unknown", "failed"}:
            continue
        page = application.get("page")
        fallback_url = application.get("url", "")
        url = _safe_page_url(page, fallback=fallback_url) if page else fallback_url
        if not url:
            url = _job_review_url(job)
        _add_review_item(items, seen, url=url,
            title=getattr(job, "title", "Unknown job"),
            company=getattr(job, "company", "Unknown company"), status=status)

    # Do not collect arbitrary context pages. In particular, rejected Handshake
    # detail tabs and generic search results must not appear in the review set.

    # Last resort: even if no individual job URL was recoverable, pop open the
    # Handshake search/results page so the user is not left with only terminal
    # text after a background run.
    if not items:
        fallback_url = os.getenv("HANDSHAKE_START_URL", "").strip()
        if fallback_url:
            _add_review_item(
                items,
                seen,
                url=fallback_url,
                title="Handshake search/results",
                company="Handshake",
                status="review_fallback",
            )

    return items

def _status_explanation(status: str) -> str:
    status = str(status or "unknown")
    explanations = {
        "handshake_submitted": "Confirmed submitted by Handshake confirmation detection.",
        "submitted": "Confirmed submitted by application/thank-you page detection.",
        "filled": "Filled, but final submission needs review unless the page itself shows submitted.",
        "handshake_submit_uncertain": "Submit was clicked, but confirmation was not detected. Review manually.",
        "handshake_screening_required": "Needs a missing screening answer or email reply before continuing.",
        "handshake_ready_manual": "Ready for manual review/submit.",
        "external_other": "External employer site captured; not processed in fast batch mode.",
        "external_unknown": "External employer site captured; not processed in fast batch mode.",
        "external_greenhouse": "Greenhouse external application candidate.",
        "resolved_external": "Reached furthest safe external step; final submit is still manual.",
        "unknown": "Application flow was not recognized. Review manually.",
        "failed": "The bot failed or could not safely continue.",
        "open_hidden_tab": "A tab was open in the hidden/background browser at finish.",
        "review_fallback": "Fallback search/results page opened because no individual application URLs were recoverable.",
    }
    return explanations.get(status, "Review manually.")


def _report_row(status: str, company: str, title: str, url: str) -> dict:
    return {
        "status": str(status or "unknown"),
        "company": str(company or "Unknown company"),
        "title": str(title or "Unknown job"),
        "url": str(url or ""),
        "explanation": _status_explanation(status),
    }


def build_run_report(jobs=None, application_tabs=None, popup_message: str = "") -> str:
    """Write a local HTML/JSON audit report and return a file:// URL."""
    data_dir = ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    seen_keys: set[tuple[str, str, str]] = set()

    for job in jobs or []:
        status = getattr(job, "application_type", "unknown") or "unknown"
        url = _job_review_url(job, status=status)
        row = _report_row(
            status=status,
            company=getattr(job, "company", "Unknown company"),
            title=getattr(job, "title", "Unknown job"),
            url=url,
        )
        key = (row["status"], row["title"], row["url"])
        if key not in seen_keys:
            seen_keys.add(key)
            rows.append(row)

    for application in application_tabs or []:
        job = application.get("job")
        status = application.get("status", "needs_review")
        page = application.get("page")
        url = application.get("url", "")
        if page:
            url = _safe_page_url(page, fallback=url)
        if not url and job:
            url = _job_review_url(job, status=status)
        row = _report_row(
            status=status,
            company=getattr(job, "company", application.get("company", "Unknown company")) if job else application.get("company", "Unknown company"),
            title=getattr(job, "title", application.get("title", "Unknown job")) if job else application.get("title", "Unknown job"),
            url=url,
        )
        key = (row["status"], row["title"], row["url"])
        if key not in seen_keys:
            seen_keys.add(key)
            rows.append(row)

    counts = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1

    report_json = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary": popup_message,
        "counts": counts,
        "applications": rows,
    }
    json_path = data_dir / "last_run_review.json"
    json_path.write_text(json.dumps(report_json, indent=2), encoding="utf-8")

    def esc(v: str) -> str:
        return html.escape(str(v or ""), quote=True)

    count_lines = "".join(f"<li><b>{esc(k)}</b>: {v}</li>" for k, v in sorted(counts.items()))
    table_rows = []
    for i, row in enumerate(rows, start=1):
        url = row["url"]
        link = f'<a href="{esc(url)}">Open</a>' if url else ""
        table_rows.append(
            "<tr>"
            f"<td>{i}</td>"
            f"<td><code>{esc(row['status'])}</code></td>"
            f"<td>{esc(row['company'])}</td>"
            f"<td>{esc(row['title'])}</td>"
            f"<td>{esc(row['explanation'])}</td>"
            f"<td>{link}</td>"
            "</tr>"
        )

    html_doc = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Resume Filler Run Review</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif; margin: 28px; line-height: 1.35; }}
    h1 {{ margin-bottom: 0; }}
    .muted {{ color: #666; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 18px; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; vertical-align: top; }}
    th {{ background: #f5f5f5; text-align: left; }}
    code {{ white-space: nowrap; }}
  </style>
</head>
<body>
  <h1>Resume Filler Run Review</h1>
  <p class="muted">Generated {esc(report_json['generated_at'])}</p>
  <p>{esc(popup_message).replace(chr(10), '<br>')}</p>
  <h2>Status counts</h2>
  <ul>{count_lines or '<li>No applications recorded.</li>'}</ul>
  <h2>Applications worked on / discovered</h2>
  <table>
    <thead><tr><th>#</th><th>Status</th><th>Company</th><th>Role</th><th>What it means</th><th>Link</th></tr></thead>
    <tbody>{''.join(table_rows) or '<tr><td colspan="6">No applications recorded.</td></tr>'}</tbody>
  </table>
</body>
</html>
"""
    html_path = data_dir / "last_run_review.html"
    html_path.write_text(html_doc, encoding="utf-8")
    return html_path.as_uri()

def open_visible_review_browser(p, review_items: list[dict]):
    if not review_items:
        return None

    print("\n" + "=" * 68)
    print("OPENING VISIBLE REVIEW BROWSER")
    print("=" * 68)
    print(f"\nOpening {len(review_items)} review tab(s).")

    # Give Chrome a moment to release the persistent-profile lock after the
    # hidden context closes.
    time.sleep(1.0)

    review_context = launch_browser_context(p, headless=False, background=False)
    first_page = first_or_new_page(review_context)

    for index, item in enumerate(review_items, start=1):
        page = first_page if index == 1 else review_context.new_page()
        url = item["url"]
        status = item["status"]
        company = item["company"]
        title = item["title"]

        print(f"  Review tab {index}: [{status}] {company} — {title}")
        print(f"      {url}")

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        except Exception as exc:
            print(f"      ⚠ Could not open review URL: {exc}")
            continue

        try:
            page.wait_for_load_state("networkidle", timeout=8_000)
        except Exception:
            pass

    try:
        first_page.bring_to_front()
    except Exception:
        pass

    print("\n✓ Visible review browser is open.")
    return review_context


def finish_run(
    p,
    context,
    *,
    jobs=None,
    application_tabs=None,
    popup_message: str = "This ran!",
    terminal_message: str = "Press ENTER to close...",
) -> None:
    """Finish a run, optionally reopening review tabs visibly."""
    run_hidden = HEADLESS or BACKGROUND_BROWSER
    report_url = build_run_report(jobs=jobs, application_tabs=application_tabs, popup_message=popup_message)
    review_items = []
    seen_review_urls = set()
    _add_review_item(
        review_items,
        seen_review_urls,
        url=report_url,
        title="Resume Filler run review",
        company="Local report",
        status="run_report",
    )
    for item in collect_review_items(jobs=jobs, application_tabs=application_tabs, context=context):
        _add_review_item(
            review_items,
            seen_review_urls,
            url=item.get("url", ""),
            title=item.get("title", "Unknown job"),
            company=item.get("company", "Unknown company"),
            status=item.get("status", "needs_review"),
        )
    review_items = review_items[: max(1, REVIEW_MAX_TABS + 1)]

    if run_hidden and REVIEW_BROWSER_ON_FINISH and review_items:
        print("\nHidden/background run finished. Reopening unresolved applications visibly...")
        try:
            context.close()
        except Exception:
            pass

        review_context = open_visible_review_browser(p, review_items)
        completion_popup(
            f"{popup_message}\n\nOpened {len(review_items)} review tab(s) in a visible browser."
        )
        input("\nReview tabs are open. Press ENTER only when you're finished reviewing them...")
        if review_context:
            try:
                review_context.close()
            except Exception:
                pass
        return

    completion_popup(popup_message)
    input(f"\n{terminal_message}")
    try:
        context.close()
    except Exception:
        pass

# ============================================================
# MAIN
# ============================================================

def main() -> None:
    print_header()

    print("\nMODE: Handshake discovery + AI-first web apply agent")

    print(
        "\nThis version will:"
        "\n  1. Open Handshake"
        "\n  2. Let you configure the search"
        f"\n  3. Auto-scroll Handshake and inspect up to {DISCOVERY_MAX_JOBS} discovered jobs"
        "\n  4. Auto-submit safe native Handshake applications if enabled"
        "\n  5. Use fast batch filtering for slow/bad external ATS sites"
        "\n  6. Hand selected external employer/ATS pages to the observe → reason → act agent"
        "\n  7. Stop when the batch target is reached"
    )

    print(
        "\nIt will NOT:"
        "\n  • Bypass CAPTCHA or human verification"
        "\n  • Click final submit on unsupported external ATS forms"
        "\n  • Invent missing documents such as cover letters or work projects"
    )

    print(
        "\nBatch settings:"
        f"\n  APPLICATION_TARGET={APPLICATION_TARGET}"
        f"\n  DISCOVERY_MAX_JOBS={DISCOVERY_MAX_JOBS}"
        f"\n  FAST_BATCH_MODE={FAST_BATCH_MODE}"
        f"\n  COUNT_RESOLVED_EXTERNAL_AS_DONE={COUNT_RESOLVED_EXTERNAL_AS_DONE}"
        f"\n  BACKGROUND_BROWSER={BACKGROUND_BROWSER}"
        f"\n  BACKGROUND_HEADLESS={BACKGROUND_HEADLESS}"
        f"\n  BACKGROUND_WINDOW_OFFSCREEN={BACKGROUND_WINDOW_OFFSCREEN}"
        f"\n  HEADLESS={HEADLESS}"
        f"\n  SLOW_MO_MS={SLOW_MO_MS}"
        f"\n  COMPLETION_POPUP={COMPLETION_POPUP}"
        f"\n  REVIEW_BROWSER_ON_FINISH={REVIEW_BROWSER_ON_FINISH}"
        f"\n  REVIEW_OPEN_ALL_WORKED={REVIEW_OPEN_ALL_WORKED}"
        f"\n  REVIEW_OPEN_SUBMITTED={REVIEW_OPEN_SUBMITTED}"
        f"\n  REVIEW_MAX_TABS={REVIEW_MAX_TABS}"
        f"\n  AUTO_HANDSHAKE_SEARCH={AUTO_HANDSHAKE_SEARCH}"
        f"\n  HANDSHAKE_QUERY={HANDSHAKE_QUERY or '(blank/current search)'}"
        f"\n  HANDSHAKE_START_URL={os.getenv('HANDSHAKE_START_URL', '').strip() or '(not set)'}"
        f"\n  HANDSHAKE_DRAFT_ONLY={env_flag('HANDSHAKE_DRAFT_ONLY', False)}"
        f"\n  AI_FILL_QUESTIONNAIRES={env_flag('AI_FILL_QUESTIONNAIRES', False)}"
        f"\n  AI_GENERATE_OTHER_DOCUMENTS={env_flag('AI_GENERATE_OTHER_DOCUMENTS', False)}"
        f"\n  HANDSHAKE_SKIP_UNPAID={env_flag('HANDSHAKE_SKIP_UNPAID', False)}"
        f"\n  HANDSHAKE_FILTER_PAID={HANDSHAKE_FILTER_PAID}"
        f"\n  SKIP_COMPANIES={', '.join(sorted(load_skip_companies())) or '(none)'}"
    )

    BROWSER_DATA.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        start_url = os.getenv("HANDSHAKE_START_URL", "").strip()

        # Hybrid background mode. With AUTO_HANDSHAKE_SEARCH enabled, skip the
        # visible setup window entirely: the hidden/off-screen browser will go
        # to Jobs, click the search field, and type HANDSHAKE_QUERY itself.
        # If you disable AUTO_HANDSHAKE_SEARCH, the old visible setup step is
        # still available for login/custom filters.
        if BACKGROUND_BROWSER and not start_url and AUTO_HANDSHAKE_SEARCH:
            start_url = HANDSHAKE_SEARCH_URL or "https://app.joinhandshake.com/job-search"
            os.environ["HANDSHAKE_START_URL"] = start_url
            print(
                "\nBACKGROUND_BROWSER auto-search:"
                "\n  Skipping manual setup window."
                f"\n  The bot will open Jobs and search: {HANDSHAKE_QUERY or '(current/default search)'}"
                "\n  It will run off-screen/minimized and reopen review tabs at the end."
            )
        elif BACKGROUND_BROWSER and not start_url:
            print(
                "\nBACKGROUND_BROWSER setup:"
                "\n  A visible setup window will open once."
                "\n  Configure Handshake search there, then press ENTER in Terminal."
                "\n  After that, the actual batch will run hidden."
            )
            setup_context = launch_browser_context(p, headless=False, background=False)
            setup_page = first_or_new_page(setup_context)
            open_handshake_for_batch(setup_page)
            start_url = setup_page.url
            os.environ["HANDSHAKE_START_URL"] = start_url
            print(f"\nCaptured Handshake search URL for hidden run: {start_url}")
            setup_context.close()
            print("Starting hidden background browser for the batch...")

        run_headless = HEADLESS or (BACKGROUND_BROWSER and BACKGROUND_HEADLESS)
        context = launch_browser_context(p, headless=run_headless, background=(BACKGROUND_BROWSER and not run_headless))
        handshake_page = first_or_new_page(context)

        open_handshake_for_batch(handshake_page)

        try:
            jobs = discover_handshake_jobs(
                handshake_page,
                max_jobs=DISCOVERY_MAX_JOBS,
                stop_after_submissions=APPLICATION_TARGET,
            )
        except TypeError:
            # Backward-compatible fallback if src.handshake.py has not been updated yet.
            jobs = discover_handshake_jobs(handshake_page, max_jobs=DISCOVERY_MAX_JOBS)
        print_discovery_summary(jobs)

        handshake_submitted_count = count_handshake_submitted(jobs)
        remaining_target = max(0, APPLICATION_TARGET - handshake_submitted_count)

        application_jobs = get_external_application_jobs(
            jobs,
            remaining_target=remaining_target if remaining_target > 0 else 0,
        )

        greenhouse_count = len([j for j in application_jobs if j.application_type == "external_greenhouse"])
        other_count = len(application_jobs) - greenhouse_count

        print(
            f"\nBatch target: {APPLICATION_TARGET}"
            f"\nHandshake already auto-submitted: {handshake_submitted_count}"
            f"\nRemaining target after Handshake submits: {remaining_target}"
            f"\nExternal/Greenhouse jobs selected for this batch: {len(application_jobs)}"
            f"\n  Greenhouse: {greenhouse_count}"
            f"\n  Other employer/ATS sites for web agent: {other_count}"
        )

        if remaining_target <= 0:
            print(f"\n✓ Batch target already reached by Handshake: {handshake_submitted_count}/{APPLICATION_TARGET}")
            print("\nReview targets will reopen visibly at the end if BACKGROUND_BROWSER/REVIEW_BROWSER_ON_FINISH is enabled.")
            finish_run(
                p,
                context,
                jobs=jobs,
                popup_message=f"This ran!\n\nBatch target reached by Handshake: {handshake_submitted_count}/{APPLICATION_TARGET}.",
                terminal_message="Press ENTER to close...",
            )
            return

        if not application_jobs:
            print("\nNo selected external/Greenhouse applications remain after filtering.")
            print("\nReview targets will reopen visibly at the end if BACKGROUND_BROWSER/REVIEW_BROWSER_ON_FINISH is enabled.")
            finish_run(
                p,
                context,
                jobs=jobs,
                popup_message=(
                    f"This ran!\n\nHandshake auto-submitted: {handshake_submitted_count}/{APPLICATION_TARGET}.\n"
                    "No selected external/Greenhouse applications remain."
                ),
                terminal_message="Press ENTER to close...",
            )
            return

        answer = input("\nOpen/fill/resolve selected external/Greenhouse jobs now? [Y/n]: ").strip().lower()

        if answer not in {"", "y", "yes"}:
            print("\nAutofill cancelled.")
            finish_run(
                p,
                context,
                jobs=jobs,
                popup_message="This ran!\n\nAutofill was cancelled before external/Greenhouse processing.",
                terminal_message="Press ENTER to close...",
            )
            return

        results = {
            "submitted": 0,
            "filled": 0,
            "resolved_external": 0,
            "unsupported": 0,
            "failed": 0,
        }

        application_tabs = []
        total = len(application_jobs)

        for index, job in enumerate(application_jobs, start=1):
            current_completed = completed_count(handshake_submitted_count, results)
            if current_completed >= APPLICATION_TARGET:
                print(f"\n✓ Batch target reached: {current_completed}/{APPLICATION_TARGET}")
                break

            page = context.new_page()
            application_tabs.append({
                "number": index,
                "url": job.application_url,
                "page": page,
                "status": "loading",
                "job": job,
            })

            try:
                result = process_application(
                    page=page,
                    job=job,
                    number=index,
                    total=total,
                )
            except Exception as exc:
                print(f"\n✗ Application processing crashed but batch will continue: {exc}")
                result = "failed"

            application_tabs[-1]["status"] = result

            if result in results:
                results[result] += 1
            else:
                results["failed"] += 1

            current_completed = completed_count(handshake_submitted_count, results)
            print(f"\nBatch progress: {current_completed}/{APPLICATION_TARGET}")

            if current_completed >= APPLICATION_TARGET:
                print(f"\n✓ Batch target reached: {current_completed}/{APPLICATION_TARGET}")
                break

        final_completed = completed_count(handshake_submitted_count, results)

        print("\n" + "=" * 68)
        print("APPLICATION TABS PREPARED")
        print("=" * 68)

        print(f"\nHandshake auto-submitted: {handshake_submitted_count}")
        print(f"Submitted by web flow:    {results['submitted']}")
        print(f"Filled:                   {results['filled']}")
        print(f"Resolved external:        {results['resolved_external']}")
        print(f"Unsupported:              {results['unsupported']}")
        print(f"Failed:                   {results['failed']}")
        print(f"Batch progress:           {final_completed}/{APPLICATION_TARGET}")

        print("\nOPEN APPLICATIONS:")

        for application in application_tabs:
            number = application["number"]
            status = application["status"]
            page = application["page"]
            job = application["job"]

            try:
                title = page.title()
            except Exception:
                title = "Unknown"

            print(f"  Tab {number}: [{status.upper()}] {job.company} — {job.title}")
            print(f"           Page: {title}")

        for application in application_tabs:
            if application["status"] in {"filled", "resolved_external"}:
                try:
                    application["page"].bring_to_front()
                except Exception:
                    pass
                break

        print("\n" + "=" * 68)
        print("READY FOR YOUR REVIEW")
        print("=" * 68)
        print("\nA local review report and all worked-on/reviewable applications will reopen at the end.")

        finish_run(
            p,
            context,
            jobs=jobs,
            application_tabs=application_tabs,
            popup_message=(
                f"This ran!\n\nBatch progress: {final_completed}/{APPLICATION_TARGET}.\n"
                f"Handshake submitted: {handshake_submitted_count}.\n"
                f"Web submitted: {results['submitted']}.\n"
                f"Filled: {results['filled']}.\n"
                f"Resolved external: {results['resolved_external']}.\n"
                f"Failed: {results['failed']}."
            ),
            terminal_message="Press ENTER only when you're finished with all applications...",
        )


if __name__ == "__main__":
    main()
