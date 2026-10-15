from __future__ import annotations

import csv
import re
from datetime import datetime
from pathlib import Path

from src.externship_config import ACADEMY_EXCLUDE_TERMS, EXCLUDE_ACADEMY_LEADS
from src.externship_models import Lead
from src.externship_io import load_leads_csv, save_leads_csv, save_leads_json


def _haystack(lead: Lead) -> str:
    values = [
        lead.clinic_name,
        lead.specialty,
        lead.city,
        lead.address,
        lead.website,
        lead.contact_page,
        lead.careers_page,
        lead.source_url,
        lead.source_note,
        lead.tags,
        lead.notes,
        lead.npi_provider_names,
        lead.npi_taxonomies,
    ]
    return " ".join(str(v or "") for v in values).lower()


def academy_exclusion_reason(lead: Lead) -> str:
    """Return a reason if this lead looks like a paid school/training/academy, otherwise empty."""
    if not EXCLUDE_ACADEMY_LEADS:
        return ""
    hay = _haystack(lead)
    for term in ACADEMY_EXCLUDE_TERMS:
        if not term:
            continue
        # Word-boundary for single words; substring for multi-word phrases and URLs.
        if " " in term:
            if term in hay:
                return f"academy/school filter matched: {term}"
        else:
            if re.search(rf"\b{re.escape(term)}\b", hay):
                return f"academy/school filter matched: {term}"
    # Strong URL/domain heuristic.
    if ".edu" in hay and not any(safe in hay for safe in ["free clinic", "community health", "health center"]):
        return "academy/school filter matched: .edu domain"
    return ""


def mark_excluded_leads(leads: list[Lead]) -> list[Lead]:
    for lead in leads:
        reason = academy_exclusion_reason(lead)
        if reason:
            lead.excluded_reason = reason
            if lead.status in {"", "new"}:
                lead.status = "excluded"
        elif lead.excluded_reason and lead.status == "excluded":
            # Leave manual exclusions alone, but clear old academy flags if env changed.
            if "academy/school filter matched" in lead.excluded_reason:
                lead.excluded_reason = ""
                lead.status = "new"
    return leads


def active_leads(leads: list[Lead]) -> list[Lead]:
    return [lead for lead in mark_excluded_leads(leads) if not lead.excluded_reason and lead.status != "excluded"]


def excluded_leads(leads: list[Lead]) -> list[Lead]:
    return [lead for lead in mark_excluded_leads(leads) if lead.excluded_reason or lead.status == "excluded"]


def write_exclusion_report(leads: list[Lead], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = excluded_leads(leads)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["clinic_name", "city", "website", "reason", "notes"])
        writer.writeheader()
        for lead in rows:
            writer.writerow({
                "clinic_name": lead.clinic_name,
                "city": lead.city,
                "website": lead.website,
                "reason": lead.excluded_reason,
                "notes": lead.notes,
            })


def filter_leads_file(leads_csv: Path, leads_json: Path | None = None) -> tuple[int, int, Path | None]:
    leads = load_leads_csv(leads_csv)
    if not leads:
        return 0, 0, None
    backup = leads_csv.with_name(f"{leads_csv.stem}_before_academy_filter_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
    backup.write_text(leads_csv.read_text(encoding="utf-8"), encoding="utf-8")
    marked = mark_excluded_leads(leads)
    kept = [lead for lead in marked if not lead.excluded_reason and lead.status != "excluded"]
    save_leads_csv(leads_csv, kept)
    if leads_json is not None:
        save_leads_json(leads_json, kept)
    return len(leads), len(kept), backup
