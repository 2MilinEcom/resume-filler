# Externship Google/NPI Upgrade v3

Fixes Google discovery when local Python fails HTTPS/SSL through urllib.

Changes:
- Uses `requests` when available for Google API calls.
- Uses certifi CA certificates for urllib fallback.
- Adds built-in Bay Area center coordinates so discovery does not depend on Geocoding for Berkeley/Oakland/SF/Walnut Creek/Hayward/San Leandro.
- Writes `data/externship_google_debug.json` even when diagnostics fail.

Recommended after install:

```bash
python -m pip install requests certifi
python externship_outreach.py test-google
python externship_outreach.py run --discover --radius-miles 50 --max-leads 25 --top 25 --open
```
