Review Tabs On Finish Fix
=========================

This patch changes BACKGROUND_BROWSER mode so hidden/headless tabs are not just summarized.

When the batch finishes:
- the hidden Playwright browser closes
- the same logged-in browser profile reopens visibly
- unresolved/manual-review applications reopen as visible tabs
- confirmed Handshake submissions are not reopened by default

Environment flags:
- REVIEW_BROWSER_ON_FINISH=true   default; opens unresolved tabs visibly
- REVIEW_MAX_TABS=40              max review tabs to reopen
- REVIEW_OPEN_SUBMITTED=false     keep submitted jobs closed by default

Recommended command:

APPLICATION_TARGET=50 \
DISCOVERY_MAX_JOBS=120 \
FAST_BATCH_MODE=true \
BACKGROUND_BROWSER=true \
REVIEW_BROWSER_ON_FINISH=true \
python main.py

Notes:
- Headless tabs cannot be physically moved into a visible Chrome window.
- This patch records their URLs, closes the hidden browser, and reopens review tabs visibly.
- If a site requires a live modal state, the reopened tab may need one click to return to the application form.
