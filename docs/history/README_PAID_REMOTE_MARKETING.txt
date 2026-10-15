RESUME FILLER: VERIFIED-PAID + FULLY-REMOTE MARKETING INTERNSHIPS

INSTALL from Mac Terminal:

cd "$HOME/Desktop/RESUME FILLER"
cp main.py "main_BACKUP_BEFORE_PAID_REMOTE_$(date +%Y%m%d_%H%M%S).py"
mkdir -p src
unzip -o "$HOME/Downloads/RESUME_FILLER_VERIFIED_PAID_REMOTE_MARKETING.zip" -d .
source .venv/bin/activate
python -m py_compile main.py src/paid_remote_guard.py src/verified_paid_guard.py src/remote_only_guard.py

FIRST RUN (5 applications maximum):

APPLICATION_TARGET=5 DISCOVERY_MAX_JOBS=80 HANDSHAKE_QUERY="Remote Marketing Internship" HANDSHAKE_FILTER_PAID=true HANDSHAKE_SKIP_UNPAID=true HANDSHAKE_DRAFT_ONLY=true NO_AUTO_SUBMIT=true REMOTE_GUARD_GREENHOUSE_REVIEW_ONLY=true FAST_BATCH_MODE=true BACKGROUND_BROWSER=true REVIEW_BROWSER_ON_FINISH=true REVIEW_OPEN_ALL_WORKED=true python main.py

LATER (up to 100 eligible jobs):

APPLICATION_TARGET=100 DISCOVERY_MAX_JOBS=400 HANDSHAKE_QUERY="Remote Marketing Internship" HANDSHAKE_FILTER_PAID=true HANDSHAKE_SKIP_UNPAID=true HANDSHAKE_DRAFT_ONLY=true NO_AUTO_SUBMIT=true REMOTE_GUARD_GREENHOUSE_REVIEW_ONLY=true FAST_BATCH_MODE=true BACKGROUND_BROWSER=true REVIEW_BROWSER_ON_FINISH=true REVIEW_OPEN_ALL_WORKED=true python main.py

HOW THIS PATCH WORKS
- During Handshake job discovery the bot opens a JOB DETAIL page to inspect title, remote requirements and pay before ever following the APPLY link or opening an external application tab.
- Marketing internship + clearly remote + verified pay are all mandatory. State-specific remote restrictions are permitted. Mandatory office attendance, hybrid jobs and onsite trips are disqualifying.
- Checks compensation in Handshake job posting. If missing, searches the public web for the exact employer and job title, visits matching candidate pages, and accepts only explicit compensation on a matching page. No finding / blocked search / contradictory or ambiguous evidence => skip.
- This uses publicly available Bing RSS search and is BEST EFFORT. Providers can block automated access; when blocked, the job is skipped. The search is not an authoritative payroll verification service, and scraped page text may be wrong. Review all accepted listings manually.
- The preexisting remote-only patch prevented Handshake native submission. This patch keeps that guard and leaves Greenhouse for manual review (not automatically filled) because the legacy module may submit.
- No credentials, API keys, resumes, tracking history or browser profile are included.
- This patch only touches main.py and adds three src/*.py files. It does NOT update your resume selection or rewrite your external ATS logic.

IMPORTANT: Many jobs will be skipped because salary is unpublished or web research is inconclusive. The requested count is a maximum, not a guaranteed number.
Test against 5 jobs before scaling. Do not run old main.py without backing it up first.
