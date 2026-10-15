from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

import src.greenhouse as greenhouse
from src.application_agent import run_application_agent_analysis


ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / ".env"
BROWSER_DATA = ROOT / "browser-data"


def disable_email_fallback_for_local_test() -> None:
    # Force the application agent on for this local test.
    os.environ["APPLICATION_AGENT_ENABLED"] = "true"
    os.environ["APPLICATION_AGENT_APPLY_SUGGESTIONS"] = "true"

    # Force Greenhouse module to use the current agent implementation.
    greenhouse.run_application_agent_analysis = run_application_agent_analysis

    # Completely disable Greenhouse email fallback for this local test.
    greenhouse.ask_application_question = None

    def skip_email_fallback(page):
        print("\n===== GREENHOUSE EMAIL FALLBACK SKIPPED FOR LOCAL TEST =====")
        return None

    def skip_question_by_email(page, question, options=None):
        print(f"   Skipping email question during local test: {question}")
        return None

    greenhouse.email_unanswered_required_greenhouse_questions = skip_email_fallback
    greenhouse.ask_question_by_email = skip_question_by_email


def main() -> None:
    load_dotenv(ENV_PATH)
    disable_email_fallback_for_local_test()

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

        print("\nGreenhouse local agent-fill test complete.")
        print("Greenhouse test completed. If GREENHOUSE_SUBMIT_TO_VERIFICATION=true, submit may have been clicked only after email-code confirmation.")
        input("\nReview the browser. Press ENTER to close browser...")

        context.close()


if __name__ == "__main__":
    main()
