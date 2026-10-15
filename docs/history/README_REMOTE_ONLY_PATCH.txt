RESUME FILLER - STRICT FULLY REMOTE PATCH
========================================
Install from your RESUME FILLER folder. Back up existing main.py before extracting.

This patch changes ONLY:
  main.py                     (based on your uploaded current main.py)
  src/remote_only_guard.py    (new)

What it does:
* Searches "Remote Marketing Internship" by default.
* Checks each Handshake job posting before opening its Apply flow.
* Rejects hybrid, mandatory onsite days, required in-person events/travel, and ambiguous jobs.
* Allows fully remote roles restricted to a state such as California, provided no office visits are required.
* Retains existing Paid Handshake filter (enable HANDSHAKE_FILTER_PAID=true and HANDSHAKE_SKIP_UNPAID=true).
* Enforces NO automatic native Handshake submission as a backup to HANDSHAKE_DRAFT_ONLY=true.
* IMPORTANT: Greenhouse automated form filling is paused by default, as your legacy Greenhouse module contains submission-to-verification flows; Greenhouse job URLs are left for manual review. Do not turn this off until that module is audited.
* Does not edit your existing src/handshake.py or browser profile.

EXACT MAC COMMANDS (assuming folder is on Desktop and ZIP is in Downloads):

  cd "$HOME/Desktop/RESUME FILLER"
  cp main.py "main_BACKUP_BEFORE_REMOTE_ONLY_$(date +%Y%m%d_%H%M%S).py"
  unzip -o "$HOME/Downloads/RESUME_FILLER_REMOTE_ONLY_PATCH.zip" -d .
  source .venv/bin/activate
  APPLICATION_TARGET=5 DISCOVERY_MAX_JOBS=50 HANDSHAKE_QUERY="Remote Marketing Internship" HANDSHAKE_FILTER_PAID=true HANDSHAKE_SKIP_UNPAID=true HANDSHAKE_DRAFT_ONLY=true NO_AUTO_SUBMIT=true REMOTE_GUARD_GREENHOUSE_REVIEW_ONLY=true REVIEW_BROWSER_ON_FINISH=true REVIEW_OPEN_ALL_WORKED=true FAST_BATCH_MODE=true BACKGROUND_BROWSER=true python main.py

When the five-job test is satisfactory, replace APPLICATION_TARGET=5 with 100 and DISCOVERY_MAX_JOBS=50 with 400. 100 is a target, not a promise: the bot will reject unsuitable jobs rather than pad the batch with hybrid jobs.

Caveats:
- Handshake's DOM changes. If the script cannot isolate an explicit remote work arrangement, it SKIPS rather than risks an onsite/hybrid application.
- Some internships use vague travel requirements; always review jobs yourself. This is static-code-tested, not live-tested against your Handshake account.
- Reopened job tabs may NOT preserve entered form state. Review before manually submitting.
- If the marketing resume isn't selected by your current profile, update the existing project profile separately.
- Never place credentials.json, .env or browser-data in shared ZIPs.
