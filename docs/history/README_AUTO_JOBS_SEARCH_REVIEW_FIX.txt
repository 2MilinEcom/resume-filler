AUTO JOBS SEARCH + REVIEW ALL WORKED TABS FIX

What this patch changes:

1. The bot can open Handshake Jobs and enter the search query automatically.
   Defaults:
     AUTO_HANDSHAKE_SEARCH=true
     HANDSHAKE_QUERY="Software Engineering Internship"

2. BACKGROUND_BROWSER=true no longer needs a visible setup window by default.
   The bot runs an off-screen/minimized browser, goes to Jobs, searches, scans,
   fills/submits, then reopens a visible review browser at the end.

3. The final review browser opens:
   - local run report tab: data/last_run_review.html
   - every discovered/worked application/job tab when REVIEW_OPEN_ALL_WORKED=true
   - submitted, submit-uncertain, external, unknown, and failed jobs

4. The run report explains what each status means:
   handshake_submitted = confirmed native Handshake submit
   submitted = confirmed Greenhouse/web thank-you submit
   handshake_submit_uncertain = submit clicked but confirmation not detected
   filled = filled but not final-confirmed
   external_other = captured external job skipped in fast mode
   unknown/failed = review manually

Recommended run:

cd "/Users/shopify/Desktop/RESUME FILLER"
source .venv/bin/activate
unzip -o ~/Downloads/auto_jobs_search_review_fix.zip -d .
python -m py_compile main.py

APPLICATION_TARGET=50 \
DISCOVERY_MAX_JOBS=120 \
FAST_BATCH_MODE=true \
BACKGROUND_BROWSER=true \
REVIEW_BROWSER_ON_FINISH=true \
REVIEW_OPEN_ALL_WORKED=true \
REVIEW_MAX_TABS=80 \
HANDSHAKE_QUERY="Software Engineering Internship" \
python main.py

To change the search:

HANDSHAKE_QUERY="Software Engineer Intern" python main.py

To restore old manual setup:

AUTO_HANDSHAKE_SEARCH=false BACKGROUND_BROWSER=true python main.py
