# Externship Outreach Email Copy V5

This patch improves the Gmail draft copy and review workflow.

## What changed

- Stronger subject line: `Medical externship inquiry - Sample Applicant`
- Better cold email body: clearer ask, more clinic-specific fit, more direct resume-review request
- Auto sender voice:
  - If Gmail is Sample's email, drafts use first-person Sample voice.
  - If Gmail is another account, drafts use coordinator/helper voice instead of pretending to be Sample.
- Adds `body_preview` to `data/externship_send_queue.csv`
- Adds an HTML preview page before creating Gmail drafts
- Adds a command to delete queued unsent Gmail drafts so old weak drafts can be regenerated cleanly

## Install

```bash
cd "/Users/shopify/Desktop/RESUME FILLER"
source .venv/bin/activate

cp externship_outreach.py "externship_outreach_BACKUP_EMAIL_V5_$(date +%Y%m%d_%H%M%S).py" 2>/dev/null || true
cp -R src "src_BACKUP_EMAIL_V5_$(date +%Y%m%d_%H%M%S)"

unzip -o ~/Downloads/externship_email_copy_v5.zip -d .

python -m py_compile externship_outreach.py src/externship_*.py
```

## Recommended cleanup and preview

If you already created weak Gmail drafts, first dry-run delete them:

```bash
python externship_outreach.py gmail-clear-drafts
```

Then actually delete queued unsent drafts:

```bash
python externship_outreach.py gmail-clear-drafts --confirm-delete
```

Preview the new emails. Since the Gmail account shown earlier was `applicant@example.com`, preview the helper/coordinator version:

```bash
python externship_outreach.py email-preview --top 40 --sender-email applicant@example.com --open
```

If Sample authenticates Gmail instead, preview first-person Sample voice:

```bash
python externship_outreach.py email-preview --top 40 --sender-email applicant@example.com --open
```

## Regenerate Gmail drafts

```bash
python externship_outreach.py gmail-drafts --top 40
```

Open the queue:

```bash
open data/externship_send_queue.csv
```

Do not send until you review the Gmail drafts and manually change `approved_to_send` to `YES` for specific rows.

Dry-run sending:

```bash
python externship_outreach.py send-approved
```

Actual approved sending, limited to 15:

```bash
python externship_outreach.py send-approved --confirm-send --limit 15
```

## Optional .env controls

```env
EXTERNSHIP_EMAIL_SENDER_MODE=auto
EXTERNSHIP_HELPER_NAME=Sample Applicant
EXTERNSHIP_HELPER_LINE=Coordinating outreach for Sample Applicant
```

`EXTERNSHIP_EMAIL_SENDER_MODE` can be `auto`, `candidate`, or `helper`.
