from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any


@dataclass
class Lead:
    clinic_name: str
    specialty: str = ""
    city: str = ""
    address: str = ""
    website: str = ""
    contact_page: str = ""
    careers_page: str = ""
    main_phone: str = ""
    contact_name: str = ""
    contact_title: str = ""
    contact_email: str = ""
    secondary_email: str = ""
    source_url: str = ""
    source_note: str = ""
    priority: str = "medium"
    status: str = "new"
    last_contact_date: str = ""
    next_followup_date: str = ""
    notes: str = ""
    tags: str = ""
    emails_found: list[str] = field(default_factory=list)
    phones_found: list[str] = field(default_factory=list)
    pages_checked: list[str] = field(default_factory=list)

    # API-discovery/enrichment fields.
    google_place_id: str = ""
    google_maps_url: str = ""
    latitude: str = ""
    longitude: str = ""
    distance_miles: str = ""
    discovery_source: str = ""
    npi_matched: str = ""
    npi_provider_names: str = ""
    npi_taxonomies: str = ""
    npi_endpoint: str = ""
    enrichment_sources: str = ""

    # Website tailoring fields. These make every draft/site card more specific.
    site_services: str = ""
    site_org_types: str = ""
    tailored_noticed: str = ""
    tailored_interest: str = ""
    tailored_tasks: str = ""
    tailoring_source: str = ""
    website_evidence: str = ""
    website_profile_title: str = ""
    website_profile_fetched_at: str = ""

    # Apollo contact enrichment fields.
    apollo_domain: str = ""
    apollo_candidates_found: str = ""
    apollo_contact_name: str = ""
    apollo_contact_title: str = ""
    apollo_contact_email: str = ""
    apollo_email_status: str = ""
    apollo_credits_consumed: str = ""
    apollo_last_run: str = ""
    apollo_notes: str = ""
    apollo_contact_fit: str = ""  # hiring_team / clinic_decision_maker / operations_leader / weak
    apollo_hiring_reason: str = ""
    apollo_contact_strategy: str = ""

    # Hiring-signal fields: these separate real active hiring signals from generic contact enrichment.
    hiring_signal_status: str = ""  # active_ma_opening / careers_page_found / externship_signal / no_signal
    hiring_signal_title: str = ""
    hiring_signal_url: str = ""
    hiring_signal_summary: str = ""
    hiring_signal_evidence: str = ""
    hiring_signal_checked_at: str = ""

    # Outreach automation fields. These are safe bookkeeping fields only.
    outreach_grade: str = ""  # A/B/C/manual prioritization.
    excluded_reason: str = ""  # Non-empty means do not draft/send/call.
    gmail_draft_id: str = ""
    gmail_draft_created_at: str = ""
    gmail_message_id: str = ""
    first_email_sent_at: str = ""
    followup_1_draft_id: str = ""
    followup_1_sent_at: str = ""
    followup_2_draft_id: str = ""
    followup_2_sent_at: str = ""
    call_status: str = ""
    last_call_date: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["emails_found"] = "; ".join(self.emails_found)
        data["phones_found"] = "; ".join(self.phones_found)
        data["pages_checked"] = "; ".join(self.pages_checked)
        return data

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> "Lead":
        values = dict(row or {})
        for key in ["emails_found", "phones_found", "pages_checked"]:
            raw = values.get(key, "")
            if isinstance(raw, str):
                values[key] = [x.strip() for x in raw.split(";") if x.strip()]
            elif not isinstance(raw, list):
                values[key] = []
        cleaned = {}
        for k in cls.__dataclass_fields__:
            value = values.get(k, "")
            if value is None:
                value = [] if k in {"emails_found", "phones_found", "pages_checked"} else ""
            cleaned[k] = value
        return cls(**cleaned)


FIELDNAMES = list(Lead.__dataclass_fields__.keys())
