# Handshake Draft-Only Questionnaire Patch

This patch adds a safe review-only mode for native Handshake applications.

## New environment flags

```bash
HANDSHAKE_DRAFT_ONLY=true
AI_FILL_QUESTIONNAIRES=true
AI_GENERATE_OTHER_DOCUMENTS=true
HANDSHAKE_SKIP_UNPAID=true
```

What it does:

- Fills known Handshake fields as before.
- Uses the short-answer agent for visible text fields.
- When Handshake asks for `Attach other required documents` / `Questionnaire`, it can generate a review-only PDF in `documents/generated_questionnaires/` and attach it.
- It stops before clicking `Submit Application`.
- `HANDSHAKE_SKIP_UNPAID=true` skips postings that visibly say unpaid.

Recommended command:

```bash
cd "/Users/shopify/Desktop/RESUME FILLER"
source .venv/bin/activate

APPLICATION_TARGET=50 \
DISCOVERY_MAX_JOBS=200 \
FAST_BATCH_MODE=true \
BACKGROUND_BROWSER=true \
REVIEW_BROWSER_ON_FINISH=true \
REVIEW_OPEN_ALL_WORKED=true \
REVIEW_MAX_TABS=80 \
HANDSHAKE_QUERY="Paid Remote Marketing Internship" \
HANDSHAKE_DRAFT_ONLY=true \
AI_FILL_QUESTIONNAIRES=true \
AI_GENERATE_OTHER_DOCUMENTS=true \
HANDSHAKE_SKIP_UNPAID=true \
python main.py
```

Review every generated questionnaire PDF and every Handshake tab before manually submitting.
