from __future__ import annotations

import os
import sys
from pathlib import Path

# Force agent on before importing project modules that may read env/config.
os.environ["APPLICATION_AGENT_ENABLED"] = "true"
os.environ.setdefault("APPLICATION_AGENT_MODEL", "gpt-5-mini")

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

import src.greenhouse as greenhouse


ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / ".env"
BROWSER_DATA = ROOT / "browser-data"


def _disable_email_fallback_for_local_test() -> None:
    """
    Local Greenhouse agent tests should not wait for email.
    Monkey-patch all email fallback entry points inside src.greenhouse.
    """
    def skip_email_fallback(page):
        print("\n[local test] Skipping Greenhouse email fallback.")
        return None

    def skip_ask_by_email(*args, **kwargs):
        print("[local test] Skipping ask-by-email.")
        return None

    greenhouse.email_unanswered_required_greenhouse_questions = skip_email_fallback
    greenhouse.ask_question_by_email = skip_ask_by_email
    greenhouse.ask_application_question = None


def main() -> None:
    load_dotenv(ENV_PATH)
    os.environ["APPLICATION_AGENT_ENABLED"] = "true"
    _disable_email_fallback_for_local_test()

    if len(sys.argv) >= 2:
        url = sys.argv[1].strip()
    else:
        url = input("Paste Greenhouse URL: ").strip()

    if not url:
        print("No URL provided.")
        return

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_DATA),
            headless=False,
            channel="chrome",
        )

        page = context.new_page()

        print("\nOpening Greenhouse test URL:")
        print(url)

        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)

        print(f"\nTitle: {page.title()}")
        print(f"URL:   {page.url}")

        greenhouse.fill_greenhouse_application(page)

        print("\nGreenhouse local agent test complete.")
        print("Submit button was not touched.")
        input("\nPress ENTER to close browser...")

        context.close()


if __name__ == "__main__":
    main()
