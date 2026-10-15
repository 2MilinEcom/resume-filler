from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable

from src.externship_models import Lead, FIELDNAMES


def ensure_dirs(root: Path) -> None:
    for sub in ["data", "drafts/externship", "reports"]:
        (root / sub).mkdir(parents=True, exist_ok=True)


def load_leads_csv(path: Path) -> list[Lead]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [Lead.from_dict(row) for row in reader]


def save_leads_csv(path: Path, leads: Iterable[Lead]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        for lead in leads:
            writer.writerow(lead.to_dict())


def save_leads_json(path: Path, leads: Iterable[Lead]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [lead.to_dict() for lead in leads]
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def merge_leads(existing: list[Lead], incoming: list[Lead]) -> list[Lead]:
    by_key: dict[str, Lead] = {}

    def key_for(lead: Lead) -> str:
        for value in [lead.google_place_id, lead.website, lead.contact_page, lead.contact_email, f"{lead.clinic_name}|{lead.address}", lead.clinic_name]:
            value = str(value or "").strip().lower()
            if value:
                return value
        return lead.clinic_name.lower()

    for lead in existing + incoming:
        key = key_for(lead)
        old = by_key.get(key)
        if old is None:
            by_key[key] = lead
            continue
        for field in FIELDNAMES:
            if field in {"emails_found", "phones_found", "pages_checked"}:
                merged = sorted(set(getattr(old, field) or []) | set(getattr(lead, field) or []))
                setattr(old, field, merged)
            elif not getattr(old, field) and getattr(lead, field):
                setattr(old, field, getattr(lead, field))
            elif field in {"notes", "source_note", "tags", "enrichment_sources"}:
                a = str(getattr(old, field) or "")
                b = str(getattr(lead, field) or "")
                if b and b not in a:
                    setattr(old, field, (a + " | " + b).strip(" |"))
    return list(by_key.values())
