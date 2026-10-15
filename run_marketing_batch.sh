#!/bin/bash
set -uo pipefail
cd "$(dirname "$0")"
source .venv/bin/activate
export AUTO_SUBMIT_VERIFIED=true
export HANDSHAKE_DRAFT_ONLY=false
export NO_AUTO_SUBMIT=false
export HANDSHAKE_REVIEW_ONLY=false
export REMOTE_GUARD_GREENHOUSE_REVIEW_ONLY=true
export HANDSHAKE_FILTER_PAID=true
export HANDSHAKE_SKIP_UNPAID=true
export HANDSHAKE_REQUIRE_PAID=true
export REVIEW_BROWSER_ON_FINISH=false
export REVIEW_OPEN_SUBMITTED=false
export COUNT_RESOLVED_EXTERNAL_AS_DONE=false
export FAST_BATCH_MODE=false
export BACKGROUND_BROWSER=true
TOTAL_TARGET=100
export DISCOVERY_MAX_JOBS=100
QUERIES=(
  'Remote Marketing Internship'
  'Remote Digital Marketing Intern'
  'Remote Social Media Intern'
  'Remote Content Marketing Intern'
  'Remote PR Communications Intern'
  'Remote Growth Marketing Intern'
)
echo '100 is the combined target for confirmed native Handshake submissions.'
for query in "${QUERIES[@]}"; do
  total=$(python -c 'import json,pathlib; p=pathlib.Path("data/auto_submitted_handshake_jobs.json"); print(len(json.loads(p.read_text())) if p.is_file() else 0)' 2>/dev/null || echo 0)
  if [ "$total" -ge "$TOTAL_TARGET" ]; then
    echo "Reached total: $total confirmed native Handshake submissions"
    break
  fi
  export APPLICATION_TARGET=$((TOTAL_TARGET - total))
  export HANDSHAKE_QUERY="$query"
  echo "Starting: $query"
  python main.py || echo "Batch failed for: $query"
done
