# Google + NPI Externship Outreach Upgrade v2

This patch fixes the case where the first Google/NPI upgrade still stayed at 14 starter leads.

What changed:

- Adds `python externship_outreach.py test-google` to test whether your `.env` key can actually call Geocoding + Places API New.
- Makes Google discovery more aggressive:
  - text search with explicit location in the query
  - nearby search fallback for `doctor`, `hospital`, `dentist`, and `physiotherapist`
  - better terminal logging
  - `data/externship_google_debug.json` with the exact Google API status/error snippets
- If Google returns 0 fresh leads, the script now says so directly and tells you to run `test-google`.

Install:

```bash
cd "/Users/shopify/Desktop/RESUME FILLER"
source .venv/bin/activate

cp externship_outreach.py "externship_outreach_BACKUP_V2_$(date +%Y%m%d_%H%M%S).py" 2>/dev/null || true
cp src/externship_google_places.py "src/externship_google_places_BACKUP_V2_$(date +%Y%m%d_%H%M%S).py" 2>/dev/null || true

unzip -o ~/Downloads/externship_google_npi_upgrade_v2.zip -d .

python -m py_compile externship_outreach.py src/externship_*.py
```

First test the Google key:

```bash
python externship_outreach.py test-google
```

Expected: it should print `key loaded: True`, `geocode Berkeley: ok`, and a few primary-care clinic leads.

Then run discovery:

```bash
python externship_outreach.py run --discover --radius-miles 50 --max-leads 25 --top 25 --open
```

If it still stores only 14 leads, paste the output from:

```bash
python externship_outreach.py test-google
cat data/externship_google_debug.json
```

Do not paste API keys.
