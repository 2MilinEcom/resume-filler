RESUME FILLER - VERIFIED NATIVE HANDSHAKE SUBMISSION PATCH

What this actually does:
- Searches six marketing queries, aiming for a combined 100 confirmed native
  Handshake submissions. Counts confirmed unique Handshake IDs in
  data/auto_submitted_handshake_jobs.json to prevent submitting them twice.
- Requires explicit positive evidence of PAID compensation and FULLY REMOTE.
  If compensation research fails, the job is rejected.
- Does not submit in-person/hybrid jobs or unknown employers.
- Selects documents/SampleApplicant_Market_Resume.pdf; refuses to run if missing.
- Uses PROFILE as sole source of factual identity/graduation details.
- Counts only confirmed submissions, not filled forms or external page visits.
- Never submits external/Greenhouse applications: their current agents are not
  verified safe for automatic unattended submission, and can require manual
  attestation, account authentication, or unknown answers. They remain blocked.
- Skips CAPTCHA and human verification; never attempts to bypass them.

Known limitations:
- Local tests only; actual Handshake selectors/DOM, research availability,
  questionnaire completeness, and submission outcomes are NOT live-tested.
- Verified compensation research can fail (URLError); such jobs are skipped.
- A job description can change when a new application page is opened.
- The script may find far fewer than 100 eligible postings.
- Any job already applied to before this patch is not necessarily present in
  data/auto_submitted_handshake_jobs.json. Do not rerun against past submissions
  without checking the Handshake applications list.
- No fully automated external ATS submissions in this version.

INSTALL (Terminal, bash/zsh):
cd "$HOME/Desktop/RESUME FILLER"
BACKUP="$HOME/Desktop/RESUME_FILLER_AUTOSUBMIT_BACKUP_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP/src"
for f in main.py src/application_agent.py src/handshake.py src/paid_remote_guard.py; do
  if [ -f "$f" ]; then mkdir -p "$BACKUP/$(dirname "$f")"; cp "$f" "$BACKUP/$f"; fi
done
printf '%s\n' "$BACKUP" > "$HOME/Desktop/RESUME_FILLER_AUTOSUBMIT_BACKUP_LOCATION.txt"
unzip -o "$HOME/Downloads/RESUME_FILLER_AUTO_SUBMIT_NATIVE_PATCH.zip" -d .
source .venv/bin/activate
python -m compileall -q main.py src

RUN (START WITH ONE SUBMISSION TEST):
AUTO_SUBMIT_VERIFIED=true HANDSHAKE_DRAFT_ONLY=false NO_AUTO_SUBMIT=false \
  REMOTE_GUARD_GREENHOUSE_REVIEW_ONLY=true APPLICATION_TARGET=1 \
  DISCOVERY_MAX_JOBS=50 HANDSHAKE_QUERY="Remote Marketing Internship" \
  REVIEW_BROWSER_ON_FINISH=false BACKGROUND_BROWSER=true python main.py

FULL SIX-QUERY RUN (after testing):
bash run_marketing_batch.sh

UNDO:
cd "$HOME/Desktop/RESUME FILLER"
BACKUP="$(cat "$HOME/Desktop/RESUME_FILLER_AUTOSUBMIT_BACKUP_LOCATION.txt")"
for f in main.py src/application_agent.py src/handshake.py src/paid_remote_guard.py; do
  if [ -f "$BACKUP/$f" ]; then cp "$BACKUP/$f" "$f"; fi
done
rm -f run_marketing_batch.sh README_AUTO_SUBMIT_PATCH.txt
# Note: undoing code does NOT undo any job applications already submitted.
# Retain data/auto_submitted_handshake_jobs.json to avoid repeat submissions.
