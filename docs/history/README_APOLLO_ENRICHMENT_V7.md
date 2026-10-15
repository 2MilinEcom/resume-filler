# Apollo Enrichment v7

This patch adds capped Apollo contact enrichment to Sample's externship outreach system.

## What it does

- Uses Apollo People Search to find likely clinic contacts (0-credit search).
- Looks for titles like clinic manager, practice manager, office manager, operations manager, HR, training coordinator, externship coordinator, and medical director.
- Uses Apollo Bulk People Enrichment only for the selected best contacts.
- Updates `data/externship_leads.csv` with `contact_name`, `contact_title`, and `contact_email` when a work email is found.
- Rebuilds the local dashboard so Apollo-found contacts show on the site.
- Keeps phone, personal-email, and waterfall enrichment disabled by default.

## Required .env values

```env
APOLLO_API_KEY=your_key_here
APOLLO_MAX_CREDITS_PER_RUN=25
APOLLO_MAX_CONTACTS_PER_CLINIC=1
APOLLO_ENRICH_EMAILS=true
APOLLO_ENRICH_PHONES=false
APOLLO_USE_WATERFALL=false
APOLLO_PERSONAL_EMAILS=false
```

## Install

```bash
cd "/Users/shopify/Desktop/RESUME FILLER"
source .venv/bin/activate

cp externship_outreach.py "externship_outreach_BACKUP_APOLLO_V7_$(date +%Y%m%d_%H%M%S).py" 2>/dev/null || true
cp -R src "src_BACKUP_APOLLO_V7_$(date +%Y%m%d_%H%M%S)"

unzip -o ~/Downloads/externship_apollo_enrichment_v7.zip -d .

python -m py_compile externship_outreach.py src/externship_*.py
```

## First test

```bash
python externship_outreach.py apollo-test
```

This only checks the key. It does not spend enrichment credits.

## Preview likely contacts without paid enrichment

```bash
python externship_outreach.py apollo-preview --max-clinics 10 --max-credits 10 --contacts-per-clinic 1
open data/externship_apollo_report.csv
```

## Run a small paid email-only enrichment test

```bash
python externship_outreach.py apollo-enrich --max-clinics 10 --max-credits 10 --contacts-per-clinic 1 --open
```

Then check:

```bash
open data/externship_apollo_report.csv
open data/externship_leads.csv
open data/externship_review.html
```

## Create Gmail drafts for newly found emails

```bash
python externship_outreach.py tailor --top 60 --force-refresh --open
python externship_outreach.py gmail-drafts --top 60
open data/externship_send_queue.csv
```

Do not send until you review Gmail Drafts and mark rows `approved_to_send=YES`.

## Cost guardrails

- `apollo-preview` uses People Search only and does not request enrichment.
- `apollo-enrich` caps requested people using `--max-credits`; the script treats this as an estimated email-only credit cap.
- Phones are disabled. Do not enable `APOLLO_ENRICH_PHONES` unless you are ready for higher credit use and webhook/polling work.
- Personal emails are disabled.
- Waterfall enrichment is disabled.
