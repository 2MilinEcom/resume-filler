from __future__ import annotations

import csv
import html
from pathlib import Path

from src.externship_contact_finder import score_lead
from src.externship_email_writer import choose_recipient
from src.externship_filters import active_leads
from src.externship_models import Lead

CALL_FIELDS = [
    "rank",
    "clinic_name",
    "city",
    "phone",
    "contact_name",
    "contact_title",
    "contact_email",
    "website",
    "score",
    "call_status",
    "notes",
    "script_hint",
]


def phone_for(lead: Lead) -> str:
    return lead.main_phone or (lead.phones_found[0] if lead.phones_found else "")


def script_hint(lead: Lead) -> str:
    return (
        f"Hi, my name is Sample Applicant. I am calling to ask whether {lead.clinic_name or 'your clinic'} "
        "is open to hosting a medical assistant extern or considering an entry-level clinic assistant. "
        "Who would be the best office manager, practice manager, or clinical supervisor to send my resume to?"
    )


def build_call_queue(leads: list[Lead], *, top: int | None = None) -> list[dict[str, str]]:
    selected = [lead for lead in active_leads(leads) if phone_for(lead)]
    selected = sorted(selected, key=score_lead, reverse=True)
    if top:
        selected = selected[:top]
    rows: list[dict[str, str]] = []
    for i, lead in enumerate(selected, start=1):
        rows.append({
            "rank": str(i),
            "clinic_name": lead.clinic_name,
            "city": lead.city,
            "phone": phone_for(lead),
            "contact_name": lead.contact_name,
            "contact_title": lead.contact_title,
            "contact_email": choose_recipient(lead),
            "website": lead.website or lead.contact_page,
            "score": str(score_lead(lead)),
            "call_status": lead.call_status,
            "notes": lead.notes,
            "script_hint": script_hint(lead),
        })
    return rows


def write_call_queue(leads: list[Lead], csv_path: Path, html_path: Path, *, top: int | None = None) -> tuple[Path, Path, int]:
    rows = build_call_queue(leads, top=top)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CALL_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    trs = []
    for row in rows:
        phone = html.escape(row["phone"])
        trs.append(f"""
<tr>
  <td>{html.escape(row['rank'])}</td>
  <td><b>{html.escape(row['clinic_name'])}</b><br><span>{html.escape(row['city'])}</span></td>
  <td><a href="tel:{phone}">{phone}</a></td>
  <td>{html.escape(row['contact_name'])}<br><span>{html.escape(row['contact_title'])}</span><br>{html.escape(row['contact_email'])}</td>
  <td>{html.escape(row['score'])}</td>
  <td>{html.escape(row['script_hint'])}</td>
  <td>no answer / voicemail / send resume / not accepting / follow up</td>
</tr>
""")
    html_path.write_text(f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Sample Externship Call Queue</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif; margin: 24px; color: #111827; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
th, td {{ border: 1px solid #e5e7eb; padding: 8px; vertical-align: top; }}
th {{ background: #111827; color: white; position: sticky; top: 0; }}
tr:nth-child(even) {{ background: #fafafa; }}
span {{ color: #6b7280; font-size: 12px; }}
</style>
</head>
<body>
<h1>Sample Externship Call Queue</h1>
<p>Manual calls only. Use this to call, log outcomes, and ask for the correct manager/email.</p>
<table>
<thead><tr><th>#</th><th>Clinic</th><th>Phone</th><th>Contact</th><th>Score</th><th>Script</th><th>Outcome</th></tr></thead>
<tbody>
{''.join(trs)}
</tbody>
</table>
</body>
</html>""", encoding="utf-8")
    return csv_path, html_path, len(rows)
