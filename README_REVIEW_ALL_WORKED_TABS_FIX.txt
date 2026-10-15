Review all worked-on tabs fix
=============================

This patch changes background mode and review behavior:

1. BACKGROUND_BROWSER no longer uses true headless mode by default.
   Handshake often exposes 0 job cards or a "Just a moment" page in true
   headless mode. The bot now runs in a headed off-screen/minimized browser so
   it should behave like normal Chrome without stealing focus.

2. At the end, a visible review browser opens a local run report first.
   Report path: data/last_run_review.html
   JSON path:   data/last_run_review.json

3. The review browser opens all jobs/applications the bot worked on or
   discovered, including confirmed submitted jobs, submit-uncertain jobs,
   unknown jobs, and external/manual-review jobs.

4. Submission status is made clearer:
   - handshake_submitted = confirmation detected by Handshake
   - submitted = web/Greenhouse thank-you or submitted page detected
   - handshake_submit_uncertain = submit clicked but confirmation not detected
   - filled = filled but final submit not confirmed

Run with:

APPLICATION_TARGET=50 \
DISCOVERY_MAX_JOBS=120 \
FAST_BATCH_MODE=true \
BACKGROUND_BROWSER=true \
REVIEW_BROWSER_ON_FINISH=true \
REVIEW_OPEN_ALL_WORKED=true \
python main.py

Set BACKGROUND_HEADLESS=true only if you explicitly want true headless mode.
