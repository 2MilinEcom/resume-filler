from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace

from playwright.sync_api import sync_playwright

from main import process_application


ROOT = Path(__file__).resolve().parent
BROWSER_DATA = ROOT / "browser-data"


def main() -> None:
    parser = argparse.ArgumentParser(description="Feed one job/employer/ATS URL directly into the AI-first web apply agent.")
    parser.add_argument("url", nargs="?", help="Employer career URL, search URL, job URL, ATS URL, or Greenhouse URL.")
    parser.add_argument("--title", default="", help="Exact target job title.")
    parser.add_argument("--company", default="", help="Company name.")
    args = parser.parse_args()

    url = args.url or input("Paste job/application URL: ").strip()
    title = args.title or input("Target job title: ").strip() or "Manual job link"
    company = args.company or input("Company: ").strip() or "Manual company"

    if not url:
        raise SystemExit("No URL provided.")

    BROWSER_DATA.mkdir(parents=True, exist_ok=True)

    fake_job = SimpleNamespace(
        application_url=url,
        title=title,
        company=company,
        application_type="external_other",
    )

    print("=" * 68)
    print("MANUAL LINK MODE — AI-FIRST WEB APPLY AGENT")
    print("=" * 68)
    print(f"Company: {company}")
    print(f"Title:   {title}")
    print(f"URL:     {url}")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_DATA),
            headless=False,
            slow_mo=75,
            viewport={"width": 1440, "height": 1000},
        )

        page = context.new_page()

        result = process_application(
            page=page,
            job=fake_job,
            number=1,
            total=1,
        )

        print("\n" + "=" * 68)
        print("MANUAL LINK RESULT")
        print("=" * 68)
        print(f"Result: {result}")
        review_page = page
        try:
            if page.is_closed():
                open_pages = [p for p in context.pages if not p.is_closed()]
                if open_pages:
                    review_page = open_pages[-1]
        except Exception:
            pass

        try:
            print(f"Current URL: {review_page.url}")
        except Exception:
            print("Current URL: <page closed>")

        try:
            print(f"Page title: {review_page.title()}")
        except Exception:
            pass

        print("\nBrowser will stay open for review.")
        input("Press ENTER when finished...")
        context.close()


if __name__ == "__main__":
    main()
