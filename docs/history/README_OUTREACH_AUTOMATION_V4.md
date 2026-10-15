# Sample externship outreach automation v4

This upgrade adds:

- Academy/school/training filter so paid schools and career-service placement programs are removed from active leads.
- Gmail draft creation for leads with public emails.
- Manual approval queue before anything is sent.
- Approved batch sending with an explicit `--confirm-send` flag.
- Follow-up draft generation.
- Manual call queue CSV/HTML.

Nothing sends by default. The safe workflow is: discover leads -> create local drafts/report -> create Gmail drafts -> review in Gmail -> mark approved rows -> send approved.

## Install

```bash
cd "/Users/shopify/Desktop/RESUME FILLER"
source .venv/bin/activate

python -m pip install -r requirements_externship_gmail.txt

cp externship_outreach.py "externship_outreach_BACKUP_V4_$(date +%Y%m%d_%H%M%S).py" 2>/dev/null || true
cp -R src "src_BACKUP_EXTERN_V4_$(date +%Y%m%d_%H%M%S)"

unzip -o ~/Downloads/externship_outreach_automation_v4.zip -d .
python -m py_compile externship_outreach.py src/externship_*.py
```

## Remove academy/school/training leads from the current CSV

```bash
python externship_outreach.py filter
python externship_outreach.py report --open
```

Excluded leads are listed in:

```text
data/externship_excluded_leads.csv
```

## Run 40 clinic leads without academies

```bash
python externship_outreach.py run --discover --radius-miles 50 --max-leads 40 --top 40 --open
```

## Create Gmail drafts only

First create OAuth desktop credentials in Google Cloud for Gmail API and save the downloaded file as:

```text
credentials.json
```

Then run:

```bash
python externship_outreach.py gmail-test
python externship_outreach.py gmail-drafts --top 40
```

This creates Gmail drafts, does not send, and writes:

```text
data/externship_send_queue.csv
```

## Send only approved drafts

Open `data/externship_send_queue.csv`, change `approved_to_send` from `NO` to `YES` for the exact rows Sample approved.

Dry run:

```bash
python externship_outreach.py send-approved
```

Actually send the approved Gmail drafts:

```bash
python externship_outreach.py send-approved --confirm-send --limit 15
```

## Follow-up drafts

Create follow-up #1 drafts for due leads:

```bash
python externship_outreach.py prepare-followups --followup-number 1 --days-since 4 --top 40
```

Create follow-up drafts for all active leads, even if send dates were not recorded:

```bash
python externship_outreach.py prepare-followups --followup-number 1 --all --top 40
```

## Manual call queue

```bash
python externship_outreach.py call-queue --top 40 --open
```

Outputs:

```text
data/externship_call_queue.csv
data/externship_call_queue.html
```

## Settings

Optional `.env` values:

```env
EXTERNSHIP_EXCLUDE_ACADEMY_LEADS=true
EXTERNSHIP_ACADEMY_EXCLUDE_TERMS=academy,school,college,university,career services,training institute,admissions,tuition,campus,medical academy
EXTERNSHIP_FOLLOWUP_1_DAYS=4
EXTERNSHIP_FOLLOWUP_2_DAYS=7
EXTERNSHIP_DAILY_SEND_LIMIT=25
GMAIL_CREDENTIALS_PATH=/Users/shopify/Desktop/RESUME FILLER/credentials.json
GMAIL_TOKEN_PATH=/Users/shopify/Desktop/RESUME FILLER/data/gmail_token.json
```
