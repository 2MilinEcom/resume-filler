import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
PROFILE = ROOT / "browser-data"
ACCOUNTS = ROOT / "data" / "site_accounts.json"

url = "https://career2.successfactors.eu/careers?company=cargill"

creds = {}
if ACCOUNTS.exists():
    data = json.loads(ACCOUNTS.read_text())
    creds = data.get("successfactors:cargill", {})

print("=" * 70)
print("CARGILL / SUCCESSFACTORS MANUAL LOGIN")
print("=" * 70)
print("URL:", url)
print("Email:", creds.get("email", "not found"))
print("Password:", creds.get("password", "not found"))
print()
print("A browser window will open. Sign in manually if needed.")
print("Complete any email verification / activation / consent screen.")
print("Then press ENTER here to close, or Ctrl+C to leave it open.")
print("=" * 70)

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE),
        headless=False,
        viewport={"width": 1440, "height": 1000},
        args=["--start-maximized"],
    )

    page = context.new_page()
    page.goto(url, wait_until="domcontentloaded", timeout=60_000)

    try:
        page.wait_for_load_state("networkidle", timeout=10_000)
    except Exception:
        pass

    print("Opened:", page.url)
    try:
        print("Title:", page.title())
    except Exception:
        pass

    input("\nPress ENTER when finished...")
    context.close()
