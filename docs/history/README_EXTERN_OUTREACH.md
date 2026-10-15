# Sample Medical Externship Outreach System

This is a separate outreach CRM from Sample's job-application filler. It uses Sample's profile and never auto-sends emails or auto-calls clinics.

## What it does

- Keeps a clinic lead list in `data/externship_leads.csv`.
- Uses only public clinic/business contact info.
- Enriches leads by visiting public websites/contact/career pages and extracting public emails and main phone numbers.
- Generates email drafts as `.txt` and `.eml` files in `drafts/externship/`.
- Generates call scripts for manual cold calling.
- Generates an HTML review dashboard at `data/externship_review.html`.
- Creates a follow-up tracker CSV at `data/externship_tracker.csv`.

## What it does NOT do

- It does not send emails.
- It does not call anyone.
- It does not submit contact forms.
- It does not use private personal phone numbers or patient information.
- It does not pretend to be Sample; every draft is written as Sample and must be reviewed before use.

## Install

From your `RESUME FILLER` project root:

```bash
cd "/Users/shopify/Desktop/RESUME FILLER"
source .venv/bin/activate
unzip -o ~/Downloads/externship_outreach_system.zip -d .
python -m py_compile externship_outreach.py src/externship_*.py
```

## Run everything

```bash
python externship_outreach.py run --open
```

This will create / update:

```text
data/externship_leads.csv
data/externship_leads.json
data/externship_tracker.csv
data/externship_review.html
data/externship_review.json
drafts/externship/*.txt
drafts/externship/*.eml
```

## Run faster without website enrichment

```bash
python externship_outreach.py run --skip-enrich --open
```

## Add a lead manually

```bash
python externship_outreach.py add-lead \
  --name "Example Clinic" \
  --city "Oakland" \
  --website "https://exampleclinic.com" \
  --phone "5105551212" \
  --email "office@exampleclinic.com" \
  --specialty "primary care clinic" \
  --tags "primary care,medical assistant,oakland"
```

## Daily workflow

1. Open `data/externship_review.html`.
2. Send or copy/paste the top-ranked email drafts after manual review.
3. Call the clinics using the generated call scripts.
4. Update `data/externship_tracker.csv` with outcomes.
5. Run:

```bash
python externship_outreach.py followups
```

## Best practical cadence

- Day 0: email + call.
- Day 2: follow-up email.
- Day 4: call again.
- Day 7: final polite follow-up.
- Then mark no response unless they ask to follow up later.
