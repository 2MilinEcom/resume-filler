Review Tabs Reopen Visible Fix

This fixes background completion review behavior.

Problem:
- A headless/background Playwright window cannot be brought to the front.
- The previous review patch only opened a visible browser if it found review items.
- Some Handshake runs ended with no selected external jobs, so no visible browser opened.

Fix:
- Captures all hidden context tabs before closing the headless browser.
- Reopens non-submitted/uncertain/unknown jobs in a visible browser.
- If job URLs cannot be recovered, reopens the Handshake search/results URL as a fallback.
- Keeps completed/submitted jobs closed unless REVIEW_OPEN_SUBMITTED=true.

Run with:
APPLICATION_TARGET=50 \
DISCOVERY_MAX_JOBS=120 \
FAST_BATCH_MODE=true \
BACKGROUND_BROWSER=true \
REVIEW_BROWSER_ON_FINISH=true \
python main.py
