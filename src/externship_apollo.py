from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from .externship_config import (
    APOLLO_API_KEY,
    APOLLO_BASE_URL,
    APOLLO_CONTACT_EMAIL_STATUS,
    APOLLO_ENRICH_EMAILS,
    APOLLO_ENRICH_PHONES,
    APOLLO_HIRING_TARGET_TITLES,
    APOLLO_MAX_CONTACTS_PER_CLINIC,
    APOLLO_MAX_CREDITS_PER_RUN,
    APOLLO_PERSONAL_EMAILS,
    APOLLO_REQUIRE_HIRING_CONTACT,
    APOLLO_REQUIRE_HIRING_SIGNAL,
    APOLLO_REQUEST_TIMEOUT,
    APOLLO_SEARCH_PER_CLINIC,
    APOLLO_USE_WATERFALL,
)
from .externship_models import Lead

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PERSONAL_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "ymail.com", "hotmail.com", "outlook.com",
    "live.com", "icloud.com", "me.com", "mac.com", "aol.com", "proton.me", "protonmail.com",
}

HIRING_TEAM_TERMS = [
    "talent acquisition", "recruiter", "recruiting", "human resources", "hr manager", "people operations", "hiring manager",
]
CLINIC_DECISION_TERMS = [
    "clinic manager", "practice manager", "medical office manager", "office manager", "site manager", "health center manager",
    "center manager", "practice administrator", "clinic administrator", "administrator",
]
OPERATIONS_TERMS = [
    "clinical operations", "operations manager", "operations director", "director of operations", "regional manager",
]
COORDINATOR_TERMS = [
    "externship coordinator", "student placement", "student coordinator", "training coordinator", "clinical training", "program coordinator",
]
CLINICAL_LEADER_TERMS = [
    "medical director", "clinical director", "chief medical officer", "nursing director", "director of nursing",
]
BAD_TITLE_TERMS = [
    "sales", "account executive", "account manager", "marketing", "finance", "engineer", "software", "product", "data", "designer",
    "board member", "investor", "advisor", "consultant", "patient", "member services", "billing", "insurance",
]
LOW_PRIORITY_PROVIDER_TERMS = [
    "physician", "doctor", "md", "m.d.", "nurse practitioner", "pa-c", "therapist", "dentist", "optometrist",
]

STRONG_HIRING_SIGNAL_STATUSES = {"active_ma_opening", "careers_page_found", "externship_signal"}


@dataclass
class ApolloCandidate:
    lead_key: str
    clinic_name: str
    domain: str
    apollo_id: str = ""
    first_name: str = ""
    last_name: str = ""
    name: str = ""
    title: str = ""
    organization_name: str = ""
    linkedin_url: str = ""
    email: str = ""
    email_status: str = ""
    source: str = "apollo_search"
    score: int = 0
    contact_fit: str = ""
    hiring_reason: str = ""

    def full_name(self) -> str:
        if self.name:
            return self.name
        return " ".join(x for x in [self.first_name, self.last_name] if x).strip()

    def to_detail(self) -> dict[str, Any]:
        detail: dict[str, Any] = {}
        if self.apollo_id:
            detail["id"] = self.apollo_id
        if self.first_name:
            detail["first_name"] = self.first_name
        if self.last_name:
            detail["last_name"] = self.last_name
        if self.name and not (self.first_name or self.last_name):
            detail["name"] = self.name
        if self.domain:
            detail["domain"] = self.domain
        if self.organization_name:
            detail["organization_name"] = self.organization_name
        if self.linkedin_url:
            detail["linkedin_url"] = self.linkedin_url
        if self.title:
            detail["title"] = self.title
        return detail


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _clean_domain(raw: str) -> str:
    if not raw:
        return ""
    value = raw.strip()
    if "@" in value and not value.startswith("http"):
        value = value.split("@", 1)[-1]
    if "://" not in value:
        value = "https://" + value
    try:
        parsed = urlparse(value)
        host = parsed.netloc or parsed.path.split("/", 1)[0]
    except Exception:
        host = value
    host = host.lower().strip().strip(".")
    if host.startswith("www."):
        host = host[4:]
    if host in {"maps.google.com", "google.com", "goo.gl"}:
        return ""
    return host


def domain_for_lead(lead: Lead) -> str:
    for value in [lead.website, lead.contact_page, lead.careers_page, lead.source_url]:
        domain = _clean_domain(value)
        if domain:
            return domain
    if lead.contact_email:
        return _clean_domain(lead.contact_email)
    return ""


def _lead_key(lead: Lead) -> str:
    domain = domain_for_lead(lead)
    base = domain or f"{lead.clinic_name}|{lead.city}"
    return base.lower()


def _headers() -> dict[str, str]:
    key = APOLLO_API_KEY.strip()
    if not key:
        raise RuntimeError("Missing APOLLO_API_KEY in .env")
    return {
        "accept": "application/json",
        "content-type": "application/json",
        "cache-control": "no-cache",
        "x-api-key": key,
    }


def _request(method: str, path: str, *, params: dict[str, Any] | None = None, json_body: dict[str, Any] | None = None) -> dict[str, Any]:
    url = APOLLO_BASE_URL.rstrip("/") + path
    response = requests.request(
        method,
        url,
        headers=_headers(),
        params=params or None,
        json=json_body or None,
        timeout=APOLLO_REQUEST_TIMEOUT,
    )
    try:
        payload = response.json()
    except Exception:
        payload = {"raw_text": response.text[:4000]}
    if response.status_code >= 400:
        message = payload.get("error") or payload.get("message") or payload.get("raw_text") or response.text[:1000]
        raise RuntimeError(f"Apollo API {response.status_code} {path}: {message}")
    return payload


def apollo_health() -> dict[str, Any]:
    return _request("GET", "/api/v1/auth/health")


def _people_from_search_response(data: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ["people", "contacts", "results", "matches"]:
        value = data.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
    return []


def _extract_org_name(person: dict[str, Any]) -> str:
    org = person.get("organization") or person.get("account") or {}
    if isinstance(org, dict):
        return str(org.get("name") or org.get("organization_name") or "").strip()
    return str(person.get("organization_name") or person.get("company") or "").strip()


def _has_any(title: str, terms: list[str]) -> bool:
    t = (title or "").lower()
    return any(term in t for term in terms)


def classify_contact_fit(title: str) -> tuple[str, str, int]:
    lower = (title or "").lower()
    if _has_any(lower, BAD_TITLE_TERMS):
        return "weak", "Title looks unrelated to hiring/clinic operations.", -35
    if _has_any(lower, HIRING_TEAM_TERMS):
        return "hiring_team", "Recruiting/HR/talent title; most likely to know open MA roles.", 70
    if _has_any(lower, CLINIC_DECISION_TERMS):
        return "clinic_decision_maker", "Clinic/practice/office manager title; likely site-level decision-maker for externships and MA hiring.", 62
    if _has_any(lower, OPERATIONS_TERMS):
        return "operations_leader", "Operations leadership title; likely can route hiring/externship request.", 50
    if _has_any(lower, COORDINATOR_TERMS):
        return "training_or_placement_coordinator", "Training/student/externship coordinator title; good fit for externship placement.", 48
    if _has_any(lower, CLINICAL_LEADER_TERMS):
        return "clinical_leader", "Clinical leader/medical director title; may approve or route clinical placement but may not own hiring.", 38
    if _has_any(lower, LOW_PRIORITY_PROVIDER_TERMS):
        return "provider_low_priority", "Provider profile; less likely to own hiring unless paired with director/manager title.", 5
    if "manager" in lower or "director" in lower or "administrator" in lower:
        return "possible_manager", "Generic manager/director title; possible routing contact but not clearly MA-hiring specific.", 25
    return "weak", "No clear hiring, HR, clinic management, operations, or placement title.", 0


HIGH_RELEVANCE_HIRING_FITS = {
    "hiring_team",
    "clinic_decision_maker",
    "operations_leader",
    "training_or_placement_coordinator",
}

BROAD_HIRING_FITS = HIGH_RELEVANCE_HIRING_FITS | {
    "clinical_leader",
    "possible_manager",
}


def is_hiring_candidate(candidate: ApolloCandidate, *, strict_hiring_owners: bool = False) -> bool:
    fit = candidate.contact_fit or classify_contact_fit(candidate.title)[0]
    allowed = HIGH_RELEVANCE_HIRING_FITS if strict_hiring_owners else BROAD_HIRING_FITS
    return fit in allowed


def score_candidate(candidate: ApolloCandidate, lead: Lead) -> int:
    title = candidate.title.lower()
    org = candidate.organization_name.lower()
    fit, reason, fit_score = classify_contact_fit(candidate.title)
    score = fit_score
    if candidate.full_name():
        score += 8
    if candidate.title:
        score += 10
    if candidate.linkedin_url:
        score += 2
    if lead.clinic_name and lead.clinic_name.lower().split()[0] in org:
        score += 8
    if getattr(lead, "hiring_signal_status", "") == "active_ma_opening":
        score += 30
    elif getattr(lead, "hiring_signal_status", "") in {"careers_page_found", "externship_signal"}:
        score += 12
    if any(term in title for term in BAD_TITLE_TERMS):
        score -= 30
    candidate.contact_fit = fit
    candidate.hiring_reason = reason
    return score


def _candidate_from_person(person: dict[str, Any], lead: Lead, domain: str) -> ApolloCandidate:
    first = str(person.get("first_name") or "").strip()
    last = str(person.get("last_name") or "").strip()
    name = str(person.get("name") or "").strip()
    if not name:
        name = " ".join(x for x in [first, last] if x).strip()
    cand = ApolloCandidate(
        lead_key=_lead_key(lead),
        clinic_name=lead.clinic_name,
        domain=domain,
        apollo_id=str(person.get("id") or person.get("person_id") or "").strip(),
        first_name=first,
        last_name=last,
        name=name,
        title=str(person.get("title") or person.get("headline") or "").strip(),
        organization_name=_extract_org_name(person) or lead.clinic_name,
        linkedin_url=str(person.get("linkedin_url") or person.get("linkedin_profile_url") or "").strip(),
        email=str(person.get("email") or "").strip(),
        email_status=str(person.get("email_status") or person.get("contact_email_status") or "").strip(),
        source="apollo_search",
    )
    cand.score = score_candidate(cand, lead)
    return cand


def _search_payload_for_lead(lead: Lead, domain: str, per_page: int, *, hiring_contacts_only: bool = True) -> dict[str, Any]:
    titles = APOLLO_HIRING_TARGET_TITLES if hiring_contacts_only else APOLLO_HIRING_TARGET_TITLES
    payload = {
        "q_organization_domains_list": [domain],
        "person_titles": titles,
        "person_seniorities": ["manager", "director", "head", "vp", "owner", "founder", "c_suite"],
        "contact_email_status": APOLLO_CONTACT_EMAIL_STATUS,
        "include_similar_titles": True,
        "page": 1,
        "per_page": max(1, min(per_page, 25)),
    }
    # Apollo search APIs vary slightly by account/features; keep payload conservative.
    return payload


def search_people_for_lead(
    lead: Lead,
    *,
    per_page: int = APOLLO_SEARCH_PER_CLINIC,
    hiring_contacts_only: bool = True,
) -> tuple[list[ApolloCandidate], dict[str, Any]]:
    domain = domain_for_lead(lead)
    if not domain:
        return [], {"status": "skipped_no_domain"}
    payload = _search_payload_for_lead(lead, domain, per_page, hiring_contacts_only=hiring_contacts_only)
    data = _request("POST", "/api/v1/mixed_people/api_search", json_body=payload)
    people = _people_from_search_response(data)
    candidates = [_candidate_from_person(p, lead, domain) for p in people]
    if hiring_contacts_only:
        candidates = [c for c in candidates if is_hiring_candidate(c)]
    candidates = sorted(candidates, key=lambda c: c.score, reverse=True)
    return candidates, data


def _is_allowed_email(email: str) -> bool:
    if not email or not EMAIL_RE.match(email):
        return False
    domain = email.rsplit("@", 1)[-1].lower()
    if not APOLLO_PERSONAL_EMAILS and domain in PERSONAL_EMAIL_DOMAINS:
        return False
    return True


def _extract_match_email(match: dict[str, Any]) -> str:
    for key in ["email", "work_email", "primary_email"]:
        value = str(match.get(key) or "").strip()
        if _is_allowed_email(value):
            return value
    emails = match.get("emails") or match.get("email_addresses") or []
    if isinstance(emails, list):
        for item in emails:
            if isinstance(item, dict):
                value = str(item.get("email") or item.get("value") or "").strip()
            else:
                value = str(item or "").strip()
            if _is_allowed_email(value):
                return value
    return ""


def _candidate_from_match(match: dict[str, Any], original: ApolloCandidate) -> ApolloCandidate:
    first = str(match.get("first_name") or original.first_name or "").strip()
    last = str(match.get("last_name") or original.last_name or "").strip()
    name = str(match.get("name") or original.name or "").strip()
    if not name:
        name = " ".join(x for x in [first, last] if x).strip()
    title = str(match.get("title") or original.title or "").strip()
    email = _extract_match_email(match)
    status = str(match.get("email_status") or match.get("contact_email_status") or original.email_status or "").strip()
    org = _extract_org_name(match) or original.organization_name
    candidate = ApolloCandidate(
        lead_key=original.lead_key,
        clinic_name=original.clinic_name,
        domain=original.domain,
        apollo_id=str(match.get("id") or match.get("person_id") or original.apollo_id or "").strip(),
        first_name=first,
        last_name=last,
        name=name,
        title=title,
        organization_name=org,
        linkedin_url=str(match.get("linkedin_url") or match.get("linkedin_profile_url") or original.linkedin_url or "").strip(),
        email=email,
        email_status=status,
        source="apollo_bulk_match",
    )
    # Preserve fit/reason from search if title was unchanged.
    fit, reason, _ = classify_contact_fit(candidate.title)
    candidate.contact_fit = fit or original.contact_fit
    candidate.hiring_reason = reason or original.hiring_reason
    candidate.score = original.score
    if candidate.title and candidate.title != original.title:
        candidate.score = score_candidate(candidate, Lead(clinic_name=original.clinic_name, website=original.domain))
    return candidate


def _chunked(items: list[Any], size: int) -> list[list[Any]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def bulk_enrich_candidates(candidates: list[ApolloCandidate]) -> tuple[list[ApolloCandidate], dict[str, Any]]:
    enriched: list[ApolloCandidate] = []
    totals = {
        "total_requested_enrichments": 0,
        "unique_enriched_records": 0,
        "missing_records": 0,
        "credits_consumed": 0,
        "raw_batches": [],
    }
    if not candidates:
        return enriched, totals
    params = {
        "reveal_personal_emails": str(bool(APOLLO_PERSONAL_EMAILS)).lower(),
        "reveal_phone_number": str(bool(APOLLO_ENRICH_PHONES)).lower(),
        "run_waterfall_email": str(bool(APOLLO_USE_WATERFALL and APOLLO_ENRICH_EMAILS)).lower(),
        "run_waterfall_phone": str(bool(APOLLO_USE_WATERFALL and APOLLO_ENRICH_PHONES)).lower(),
    }
    if not APOLLO_ENRICH_PHONES:
        params["reveal_phone_number"] = "false"
        params["run_waterfall_phone"] = "false"
    if not APOLLO_USE_WATERFALL:
        params["run_waterfall_email"] = "false"
        params["run_waterfall_phone"] = "false"
    for chunk in _chunked(candidates, 10):
        details = [c.to_detail() for c in chunk if c.to_detail()]
        if not details:
            continue
        data = _request("POST", "/api/v1/people/bulk_match", params=params, json_body={"details": details})
        totals["raw_batches"].append(data)
        for key in ["total_requested_enrichments", "unique_enriched_records", "missing_records"]:
            try:
                totals[key] += int(data.get(key) or 0)
            except Exception:
                pass
        try:
            totals["credits_consumed"] += float(data.get("credits_consumed") or 0)
        except Exception:
            pass
        matches = data.get("matches") or []
        if not isinstance(matches, list):
            matches = []
        for i, match in enumerate(matches[: len(chunk)]):
            if not isinstance(match, dict):
                continue
            cand = _candidate_from_match(match, chunk[i])
            if cand.email:
                enriched.append(cand)
    enriched = sorted(enriched, key=lambda c: c.score, reverse=True)
    return enriched, totals


def _append_source(existing: str, source: str) -> str:
    parts = [x.strip() for x in (existing or "").split(";") if x.strip()]
    if source not in parts:
        parts.append(source)
    return "; ".join(parts)


def apply_candidate_to_lead(lead: Lead, candidate: ApolloCandidate, *, credits: float = 0.0, notes: str = "") -> Lead:
    if candidate.full_name() and not lead.contact_name:
        lead.contact_name = candidate.full_name()
    if candidate.title and not lead.contact_title:
        lead.contact_title = candidate.title
    if candidate.email:
        if not lead.contact_email:
            lead.contact_email = candidate.email
        elif candidate.email.lower() != lead.contact_email.lower() and not lead.secondary_email:
            lead.secondary_email = candidate.email
    lead.apollo_domain = candidate.domain
    lead.apollo_contact_name = candidate.full_name()
    lead.apollo_contact_title = candidate.title
    lead.apollo_contact_email = candidate.email
    lead.apollo_email_status = candidate.email_status
    lead.apollo_contact_fit = candidate.contact_fit
    lead.apollo_hiring_reason = candidate.hiring_reason
    lead.apollo_last_run = _now()
    lead.apollo_credits_consumed = str(credits)
    lead.apollo_notes = notes
    lead.enrichment_sources = _append_source(lead.enrichment_sources, "apollo_hiring")
    source_note = f"Apollo hiring contact: {candidate.full_name()}"
    if candidate.title:
        source_note += f" ({candidate.title})"
    if candidate.email:
        source_note += f" <{candidate.email}>"
    if candidate.contact_fit:
        source_note += f" [{candidate.contact_fit}]"
    if source_note not in (lead.notes or ""):
        lead.notes = ((lead.notes + " | ") if lead.notes else "") + source_note
    return lead


def _row_for_candidate(lead: Lead, cand: ApolloCandidate, status: str = "candidate") -> dict[str, Any]:
    return {
        "clinic_name": lead.clinic_name,
        "domain": cand.domain,
        "status": status,
        "hiring_signal_status": getattr(lead, "hiring_signal_status", ""),
        "hiring_signal_title": getattr(lead, "hiring_signal_title", ""),
        "hiring_signal_url": getattr(lead, "hiring_signal_url", ""),
        "candidate_name": cand.full_name(),
        "candidate_title": cand.title,
        "candidate_email": cand.email,
        "email_status": cand.email_status,
        "organization_name": cand.organization_name,
        "candidate_score": cand.score,
        "contact_fit": cand.contact_fit,
        "hiring_reason": cand.hiring_reason,
        "linkedin_url": cand.linkedin_url,
        "strict_hiring_owner": "YES" if cand.contact_fit in HIGH_RELEVANCE_HIRING_FITS else "NO",
    }


def apollo_enrich_leads(
    leads: list[Lead],
    *,
    missing_email_only: bool = True,
    max_clinics: int = 25,
    max_credits: int = APOLLO_MAX_CREDITS_PER_RUN,
    contacts_per_clinic: int = APOLLO_MAX_CONTACTS_PER_CLINIC,
    search_only: bool = False,
    hiring_contacts_only: bool = APOLLO_REQUIRE_HIRING_CONTACT,
    require_hiring_signal: bool = APOLLO_REQUIRE_HIRING_SIGNAL,
    report_csv: Path | None = None,
    report_json: Path | None = None,
    strict_hiring_owners: bool = False,
) -> tuple[list[Lead], dict[str, Any]]:
    if not APOLLO_API_KEY:
        raise RuntimeError("Missing APOLLO_API_KEY in .env")
    contacts_per_clinic = max(1, contacts_per_clinic)
    max_clinics = max(1, max_clinics)
    max_credits = max(1, max_credits)

    selected: list[Lead] = []
    for lead in leads:
        if lead.excluded_reason:
            continue
        if missing_email_only and (lead.contact_email or "").strip():
            continue
        if require_hiring_signal and getattr(lead, "hiring_signal_status", "") not in STRONG_HIRING_SIGNAL_STATUSES:
            continue
        selected.append(lead)
        if len(selected) >= max_clinics:
            break

    summary: dict[str, Any] = {
        "selected_clinics": len(selected),
        "searched_clinics": 0,
        "candidates_found": 0,
        "hiring_candidates_found": 0,
        "enrichment_requested": 0,
        "emails_found": 0,
        "credits_consumed": 0,
        "skipped": [],
        "rows": [],
        "search_only": search_only,
        "hiring_contacts_only": hiring_contacts_only,
        "require_hiring_signal": require_hiring_signal,
        "strict_hiring_owners": strict_hiring_owners,
        "allowed_contact_fits": ";".join(sorted(HIGH_RELEVANCE_HIRING_FITS if strict_hiring_owners else BROAD_HIRING_FITS)),
    }
    by_key = {_lead_key(lead): lead for lead in leads}
    candidates_to_enrich: list[ApolloCandidate] = []

    if not selected:
        status = "no_clinics_selected"
        note = "No clinics were selected for Apollo search."
        if require_hiring_signal:
            note = "No clinics had active_ma_opening/careers_page_found/externship_signal. Re-run hiring-scan after the v9 SSL fix, or omit --require-hiring-signal for a broader hiring-owner search."
        summary["rows"].append({
            "clinic_name": "(none)",
            "domain": "",
            "status": status,
            "hiring_signal_status": "required" if require_hiring_signal else "not_required",
            "hiring_reason": note,
        })
        _write_apollo_reports(summary, report_csv, report_json)
        return leads, summary

    for lead in selected:
        domain = domain_for_lead(lead)
        if not domain:
            summary["skipped"].append({"clinic_name": lead.clinic_name, "reason": "no_domain"})
            continue
        signal = getattr(lead, "hiring_signal_status", "") or "not_scanned"
        print(f"Apollo hiring-contact search: {lead.clinic_name} ({domain}) | hiring_signal={signal}")
        try:
            candidates, raw = search_people_for_lead(
                lead,
                per_page=APOLLO_SEARCH_PER_CLINIC,
                hiring_contacts_only=hiring_contacts_only,
            )
        except Exception as exc:
            summary["skipped"].append({"clinic_name": lead.clinic_name, "reason": str(exc)})
            lead.apollo_last_run = _now()
            lead.apollo_notes = str(exc)[:300]
            continue
        summary["searched_clinics"] += 1
        summary["candidates_found"] += len(candidates)
        strong = [c for c in candidates if is_hiring_candidate(c, strict_hiring_owners=strict_hiring_owners)] if hiring_contacts_only else candidates
        summary["hiring_candidates_found"] += len(strong)
        lead.apollo_domain = domain
        lead.apollo_candidates_found = str(len(strong))
        lead.apollo_last_run = _now()
        if not strong:
            if strict_hiring_owners:
                lead.apollo_notes = "Apollo returned no strict HR/recruiter/clinic/practice/office/operations/training-placement candidates."
            else:
                lead.apollo_notes = "Apollo returned no strong HR/recruiter/clinic-manager/operations/placement candidates."
            summary["rows"].append({
                "clinic_name": lead.clinic_name,
                "domain": domain,
                "status": "no_strong_hiring_contact",
                "hiring_signal_status": getattr(lead, "hiring_signal_status", ""),
                "hiring_signal_title": getattr(lead, "hiring_signal_title", ""),
                "hiring_signal_url": getattr(lead, "hiring_signal_url", ""),
            })
            continue
        top = strong[:contacts_per_clinic]
        for cand in top:
            summary["rows"].append(_row_for_candidate(lead, cand, status="candidate_selected_for_possible_enrichment"))
        candidates_to_enrich.extend(top)

    # Conservative cap: email-only standard enrichment usually consumes about one credit per enriched person.
    if len(candidates_to_enrich) > max_credits:
        candidates_to_enrich = candidates_to_enrich[:max_credits]
    summary["enrichment_requested"] = len(candidates_to_enrich)

    if search_only or not candidates_to_enrich:
        _write_apollo_reports(summary, report_csv, report_json)
        return leads, summary

    print(f"Apollo bulk enrichment: requesting {len(candidates_to_enrich)} hiring/personnel contact(s), phones/waterfall disabled.")
    enriched, totals = bulk_enrich_candidates(candidates_to_enrich)
    summary["credits_consumed"] = totals.get("credits_consumed", 0)
    summary["bulk_totals"] = {k: v for k, v in totals.items() if k != "raw_batches"}
    summary["emails_found"] = len([c for c in enriched if c.email])

    best_by_key: dict[str, ApolloCandidate] = {}
    for cand in enriched:
        if not cand.email:
            continue
        if hiring_contacts_only and not is_hiring_candidate(cand, strict_hiring_owners=strict_hiring_owners):
            continue
        current = best_by_key.get(cand.lead_key)
        if not current or cand.score > current.score:
            best_by_key[cand.lead_key] = cand

    for key, cand in best_by_key.items():
        lead = by_key.get(key)
        if not lead:
            continue
        apply_candidate_to_lead(
            lead,
            cand,
            credits=summary["credits_consumed"],
            notes="Apollo hiring-contact email-only enrichment; phone, personal email, and waterfall disabled.",
        )
        summary["rows"].append(_row_for_candidate(lead, cand, status="email_found_hiring_contact"))

    _write_apollo_reports(summary, report_csv, report_json)
    return leads, summary


def _write_apollo_reports(summary: dict[str, Any], report_csv: Path | None, report_json: Path | None) -> None:
    if report_json:
        report_json.parent.mkdir(parents=True, exist_ok=True)
        report_json.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    if report_csv:
        report_csv.parent.mkdir(parents=True, exist_ok=True)
        rows = summary.get("rows") or []
        fields = [
            "clinic_name",
            "domain",
            "status",
            "hiring_signal_status",
            "hiring_signal_title",
            "hiring_signal_url",
            "candidate_name",
            "candidate_title",
            "candidate_email",
            "email_status",
            "organization_name",
            "candidate_score",
            "contact_fit",
            "hiring_reason",
            "linkedin_url",
        ]
        with report_csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow({field: row.get(field, "") for field in fields})
