RESUME FILLER: FAIL-CLOSED PAID REMOTE MARKETING PATCH (OCT 2026)

Changes:
- Stops reopening all jobs marked skipped_eligibility or skipped_duplicate at review.
- Stops importing every open hidden browser page into the final review browser.
- Only named, screened, eligible jobs are allowed past application gate.
- Extracts employer name from Handshake title when structured selector fails.
- Deduplicates listings by canonical Handshake job ID within a Python run.
- Ignores recommendation cards and employer profile when determining compensation.
- Keeps native Handshake auto-submit disabled; retains previous Greenhouse review-only behavior.
- Fails closed on unknown/unverifiable pay and remote work.

LIMITATIONS:
- Web pay research via Bing RSS can fail with URLError; unknown salary means SKIP.
- Cross-process dedup (across 5 independent python main.py runs) is NOT implemented.
- 100 confirmed eligible unique internships is NOT guaranteed.
- The bot must open Handshake job-detail pages to inspect them; no skipped job
  should be reopened in the final review browser.
- Current Handshake DOM changes may require changes to selectors.
- The code was syntax-checked and local tests passed, NOT tested on a live account.
- Never trust the bot's verification without inspecting accepted jobs yourself.

INSTALL (Terminal, Mac):
cd "$HOME/Desktop/RESUME FILLER"
BACKUP="$HOME/Desktop/RESUME_FILLER_BACKUP_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP/src"
cp main.py "$BACKUP/main.py"
for f in remote_only_guard.py paid_remote_guard.py verified_paid_guard.py; do
  if [ -f "src/$f" ]; then cp "src/$f" "$BACKUP/src/$f"; fi
done
printf '%s\n' "$BACKUP" > "$HOME/Desktop/RESUME_FILLER_LAST_BACKUP.txt"
unzip -o "$HOME/Downloads/RESUME_FILLER_FAIL_CLOSED_FIX.zip" -d .
source .venv/bin/activate
python -m py_compile main.py src/paid_remote_guard.py src/verified_paid_guard.py src/remote_only_guard.py
python test_workflow_fix.py

RUN SMALL TEST:
APPLICATION_TARGET=5 DISCOVERY_MAX_JOBS=80 HANDSHAKE_QUERY="Remote Marketing Internship" HANDSHAKE_FILTER_PAID=true HANDSHAKE_SKIP_UNPAID=true HANDSHAKE_DRAFT_ONLY=true NO_AUTO_SUBMIT=true REMOTE_GUARD_GREENHOUSE_REVIEW_ONLY=true FAST_BATCH_MODE=true BACKGROUND_BROWSER=true REVIEW_BROWSER_ON_FINISH=true REVIEW_OPEN_ALL_WORKED=false python main.py

UNDO / ROLLBACK (restores exactly the backed up files):
cd "$HOME/Desktop/RESUME FILLER"
BACKUP="$(cat "$HOME/Desktop/RESUME_FILLER_LAST_BACKUP.txt")"
cp "$BACKUP/main.py" main.py
for f in remote_only_guard.py paid_remote_guard.py verified_paid_guard.py; do
  if [ -f "$BACKUP/src/$f" ]; then
    cp "$BACKUP/src/$f" "src/$f"
  else
    rm -f "src/$f"
  fi
done
rm -f test_workflow_fix.py README_FIX_AND_UNDO.txt
python -m py_compile main.py

No browser logins, account data, resumes, tokens, or secrets included.
