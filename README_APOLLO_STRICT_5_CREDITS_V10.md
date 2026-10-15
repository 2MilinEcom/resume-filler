# Apollo Strict Hiring Owners v10

This patch adds a stricter Apollo hiring-owner mode for Sample externship outreach.

Default `apollo-hiring-preview` and `apollo-hiring-enrich` now exclude generic medical directors/clinical leaders unless you explicitly add `--allow-clinical-leaders`.

Allowed by default:

- hiring_team
- clinic_decision_maker
- operations_leader
- training_or_placement_coordinator

Not allowed by default:

- clinical_leader
- possible_manager
- provider_low_priority
- weak

Use this for a 5-credit test:

```bash
python externship_outreach.py apollo-hiring-preview --max-clinics 12 --contacts-per-clinic 1 --require-hiring-signal --force-scan
open data/externship_apollo_report.csv

python externship_outreach.py apollo-hiring-enrich --max-clinics 5 --max-credits 5 --contacts-per-clinic 1 --require-hiring-signal --force-scan --open
```

Phones, personal emails, and waterfall enrichment stay off by environment defaults.
