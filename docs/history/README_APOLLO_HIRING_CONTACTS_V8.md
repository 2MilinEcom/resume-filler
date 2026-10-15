# Apollo Hiring-Contact Targeting v8

This patch changes Apollo from "find any contact email" into "find a likely person tied to hiring, clinic management, operations, HR/recruiting, or externship placement."

It adds:

- `hiring-scan` — scans clinic/careers pages for Medical Assistant / clinic-support openings, careers pages, or externship/student-placement signals.
- `apollo-hiring-preview` — no paid enrichment; shows likely HR/recruiter/clinic-manager/operations/placement people.
- `apollo-hiring-enrich` — email-only enrichment for selected hiring/decision-maker contacts. Phones, personal emails, and waterfall remain off by default.
- Dashboard fields for hiring signals, Apollo contact fit, and why the person was selected.

Important: Apollo can find likely decision-makers and work emails, but it cannot prove that one specific person personally owns an active Medical Assistant requisition unless there is a public hiring signal. This patch separates:

1. Active/careers/externship hiring signals from the clinic website.
2. A likely hiring owner or site decision-maker from Apollo.
3. Lower-confidence general contacts.

## Install

```bash
cd "/Users/shopify/Desktop/RESUME FILLER"
source .venv/bin/activate

cp externship_outreach.py "externship_outreach_BACKUP_APOLLO_HIRING_V8_$(date +%Y%m%d_%H%M%S).py" 2>/dev/null || true
cp -R src "src_BACKUP_APOLLO_HIRING_V8_$(date +%Y%m%d_%H%M%S)"

unzip -o ~/Downloads/externship_apollo_hiring_contacts_v8.zip -d .

python -m py_compile externship_outreach.py src/externship_*.py
```

## Recommended workflow

### 1) Scan for actual hiring signals first

```bash
python externship_outreach.py hiring-scan --top 60 --force-refresh --open
open data/externship_hiring_signals.csv
```

Look for:

- `active_ma_opening` — strongest: a Medical Assistant / clinical assistant / front/back office role was found.
- `careers_page_found` — careers/job page found, but no clear MA role in scanned pages.
- `externship_signal` — externship/student-placement/training signal found.
- `no_signal` — still worth calling, but not proven to be hiring now.

### 2) Preview likely hiring owners without spending credits

Strictest mode:

```bash
python externship_outreach.py apollo-hiring-preview --max-clinics 20 --contacts-per-clinic 1 --require-hiring-signal
open data/externship_apollo_report.csv
```

If this is too restrictive, preview broader site-level decision-makers:

```bash
python externship_outreach.py apollo-hiring-preview --max-clinics 20 --contacts-per-clinic 1
open data/externship_apollo_report.csv
```

The useful fields are:

- `contact_fit`
- `hiring_reason`
- `candidate_title`
- `hiring_signal_status`
- `hiring_signal_url`

Good fits include:

- `hiring_team`
- `clinic_decision_maker`
- `operations_leader`
- `training_or_placement_coordinator`
- `clinical_leader`

### 3) Enrich a small batch only

```bash
python externship_outreach.py apollo-hiring-enrich --max-clinics 10 --max-credits 10 --contacts-per-clinic 1 --require-hiring-signal --open
```

If too few contacts are found, use:

```bash
python externship_outreach.py apollo-hiring-enrich --max-clinics 20 --max-credits 20 --contacts-per-clinic 1 --open
```

### 4) Regenerate site + Gmail drafts

```bash
python externship_outreach.py tailor --top 60 --force-refresh --open
python externship_outreach.py gmail-drafts --top 60
open data/externship_send_queue.csv
```

Do not send until each row is manually reviewed and `approved_to_send` is set to `YES`.

## Cost safety

Keep these `.env` defaults:

```env
APOLLO_MAX_CREDITS_PER_RUN=25
APOLLO_MAX_CONTACTS_PER_CLINIC=1
APOLLO_ENRICH_EMAILS=true
APOLLO_ENRICH_PHONES=false
APOLLO_USE_WATERFALL=false
APOLLO_PERSONAL_EMAILS=false
APOLLO_REQUIRE_HIRING_CONTACT=true
APOLLO_REQUIRE_HIRING_SIGNAL=false
```

Phone/mobile lookup is intentionally off. Use clinic main phones from Google/website and only use Apollo email enrichment first.
