from __future__ import annotations

import csv
from datetime import datetime, timedelta
from pathlib import Path

TRACKER_FIELDS = [
    "clinic_name", "status", "last_action", "last_action_date", "next_followup_date",
    "contact_name", "contact_email", "main_phone", "notes"
]


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def followup_date(days: int = 2) -> str:
    return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")


def initialize_tracker(path: Path, leads) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=TRACKER_FIELDS)
        writer.writeheader()
        for lead in leads:
            writer.writerow({
                "clinic_name": lead.clinic_name,
                "status": "new",
                "last_action": "",
                "last_action_date": "",
                "next_followup_date": "",
                "contact_name": lead.contact_name,
                "contact_email": lead.contact_email,
                "main_phone": lead.main_phone,
                "notes": "",
            })


def print_followups_due(path: Path) -> None:
    if not path.exists():
        print("No tracker yet.")
        return
    with path.open("r", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    due = []
    today_s = today()
    for row in rows:
        nfd = row.get("next_followup_date", "")
        if nfd and nfd <= today_s and row.get("status") not in {"accepted", "rejected", "not_accepting"}:
            due.append(row)
    if not due:
        print("No follow-ups due today.")
        return
    print("FOLLOW-UPS DUE")
    print("-" * 68)
    for row in due:
        print(f"{row.get('clinic_name')} | {row.get('contact_email')} | {row.get('main_phone')} | {row.get('notes')}")
