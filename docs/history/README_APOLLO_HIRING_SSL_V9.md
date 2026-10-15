# Externship Apollo Hiring Contacts v9

This patch fixes the v8 hiring-signal failure where every clinic was marked `no_signal` because the website crawler hit macOS/Python SSL certificate errors.

## What changed

- `src/externship_contact_finder.py` now fetches public clinic/careers pages with `requests` + `certifi`.
- If a public clinic site has a broken/incomplete certificate chain, it falls back to an unverified public-page fetch so the scanner can still read public job/careers pages.
- `src/externship_hiring_signals.py` now labels network failures as `fetch_error` instead of treating them as proof of `no_signal`.
- `src/externship_apollo.py` now writes a useful report row when `--require-hiring-signal` selects zero clinics instead of leaving the CSV visually empty.

## Install

```bash
cd "/Users/shopify/Desktop/RESUME FILLER"
source .venv/bin/activate

python -m pip install requests certifi

cp externship_outreach.py "externship_outreach_BACKUP_APOLLO_SSL_V9_$(date +%Y%m%d_%H%M%S).py" 2>/dev/null || true
cp -R src "src_BACKUP_APOLLO_SSL_V9_$(date +%Y%m%d_%H%M%S)"

unzip -o ~/Downloads/externship_apollo_hiring_ssl_v9.zip -d .

python -m py_compile externship_outreach.py src/externship_*.py
```

## Recommended next run

```bash
rm -f data/externship_hiring_signals.json

python externship_outreach.py hiring-scan --top 60 --force-refresh --open
open data/externship_hiring_signals.csv

python externship_outreach.py apollo-hiring-preview --max-clinics 20 --contacts-per-clinic 1 --require-hiring-signal --force-scan
open data/externship_apollo_report.csv
```

If the `--require-hiring-signal` preview is still too narrow, run:

```bash
python externship_outreach.py apollo-hiring-preview --max-clinics 20 --contacts-per-clinic 1
open data/externship_apollo_report.csv
```

Then enrich a small paid/email-only batch:

```bash
python externship_outreach.py apollo-hiring-enrich --max-clinics 10 --max-credits 10 --contacts-per-clinic 1 --open
```
