# Google Places + NPI Externship Outreach Upgrade

This patch upgrades the Sample externship outreach system with:

- Google Places API (New) discovery for fresh nearby clinic leads
- Geocoding for Berkeley/Oakland/SF/Walnut Creek search centers
- NPI Registry matching for provider/organization context
- Website crawler enrichment for public emails, phones, contact/team/careers pages
- Updated dashboard columns for distance, Google Maps links, NPI matches, discovered emails/phones

It remains **drafts only**. It does not send emails, call clinics, scrape LinkedIn, or submit contact forms.

## Install

From your project root:

```bash
cd "/Users/shopify/Desktop/RESUME FILLER"
source .venv/bin/activate

# Optional safety backup
cp externship_outreach.py "externship_outreach_BACKUP_$(date +%Y%m%d_%H%M%S).py" 2>/dev/null || true
cp -R src "src_BACKUP_GOOGLE_NPI_$(date +%Y%m%d_%H%M%S)"

unzip -o ~/Downloads/externship_google_npi_upgrade.zip -d .

python -m py_compile externship_outreach.py src/externship_*.py
```

## Confirm .env

Your `.env` should include:

```env
GOOGLE_MAPS_API_KEY=YOUR_KEY_HERE
EXTERNSHIP_DEFAULT_RADIUS_MILES=50
EXTERNSHIP_MAX_LEADS_PER_RUN=25
```

## Run the new discovery pipeline

Recommended first run:

```bash
python externship_outreach.py discover --radius-miles 50 --max-leads 25 --include-seed
python externship_outreach.py drafts --top 25
python externship_outreach.py report --open
```

Or one command:

```bash
python externship_outreach.py run --discover --radius-miles 50 --max-leads 25 --top 25 --open
```

## Faster / cheaper variants

Only Google Places, no website crawl or NPI:

```bash
python externship_outreach.py discover --radius-miles 50 --max-leads 25 --skip-npi --skip-website-enrich --include-seed
```

Only run NPI on existing leads:

```bash
python externship_outreach.py npi --max-leads 25
```

Only regenerate drafts/report from existing data:

```bash
python externship_outreach.py drafts --top 25
python externship_outreach.py report --open
```

## Outputs

- `data/externship_leads.csv`
- `data/externship_leads.json`
- `data/externship_review.html`
- `data/externship_review.json`
- `drafts/externship/*.txt`
- `drafts/externship/*.eml`

## Notes

Google Places Text Search returns a maximum set per request, so this tool runs multiple conservative search queries across several Bay Area centers. The target cap defaults to 25 leads per run to control cost and review workload.

NPI Registry does not require an API key. It is used only for matching real provider/organization records and does not replace clinic outreach verification.
