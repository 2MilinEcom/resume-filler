# Tailored Email + Website Draft Dashboard v6

This patch upgrades the externship outreach system so emails are written in first-person Sample voice and are tailored from each clinic's website/lead data.

## What changed

- First-person Sample cold emails by default.
- More clinic-specific subject lines.
- Website/service tailoring: primary care, urgent care, community health, free clinic, pediatrics, women's health, occupational medicine, imaging/outpatient, dermatology, orthopedics, multilingual/community-care signals.
- Draft copy references the clinic's apparent services and the practical clinic tasks Sample wants to learn: intake, rooming, vitals, scheduling, front/back-office workflow, EHR/admin support, patient communication, and related workflow.
- `data/externship_review.html` now includes a clean "Tailored Draft Emails by Clinic Website" section with the full initial email and follow-up email per clinic.
- Report cards show the website/source, services used, evidence used, and copy buttons.
- Gmail drafts use the same tailored bodies shown on the site.
- Gmail drafts include `Reply-To: applicant@example.com` even if the authenticated Gmail is Sample's account.

## Install

```bash
cd "/Users/shopify/Desktop/RESUME FILLER"
source .venv/bin/activate

cp externship_outreach.py "externship_outreach_BACKUP_TAILORED_V6_$(date +%Y%m%d_%H%M%S).py" 2>/dev/null || true
cp -R src "src_BACKUP_TAILORED_V6_$(date +%Y%m%d_%H%M%S)"

unzip -o ~/Downloads/externship_tailored_email_site_v6.zip -d .

python -m py_compile externship_outreach.py src/externship_*.py
```

## Rebuild tailored website and local drafts

```bash
python externship_outreach.py tailor --top 60 --force-refresh --open
python externship_outreach.py drafts --top 60
python externship_outreach.py report --open
```

Open:

```bash
open data/externship_review.html
```

Scroll to **Tailored Draft Emails by Clinic Website**.

## Replace old Gmail drafts with tailored drafts

First delete old unsent queued drafts:

```bash
python externship_outreach.py gmail-clear-drafts
python externship_outreach.py gmail-clear-drafts --confirm-delete
```

Then create new Gmail drafts:

```bash
python externship_outreach.py gmail-drafts --top 40
```

Review drafts in Gmail. Do not send until you manually approve rows in:

```bash
open data/externship_send_queue.csv
```

Sending still requires approval:

```bash
python externship_outreach.py send-approved
python externship_outreach.py send-approved --confirm-send --limit 15
```

## Notes

- If you send from Sample's Gmail, the email body is first-person Sample and the Reply-To is Sample's Berkeley email. For the cleanest sender identity, authenticate Gmail as Sample instead.
- The website-tailoring cache is stored at `data/externship_website_profiles.json`.
- Use `--force-refresh` when you want to refetch clinic websites.
- The system still does not auto-call, auto-submit contact forms, or send anything unless approved.
