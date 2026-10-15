from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from src.externship_config import ROOT, get_bool_env, get_int_env
from src.externship_contact_finder import clean_html_text, extract_candidate_links, fetch_url
from src.externship_models import Lead

CACHE_PATH = ROOT / "data" / "externship_website_profiles.json"

SERVICE_KEYWORDS: list[tuple[str, list[str]]] = [
    ("primary care", ["primary care", "family medicine", "internal medicine", "preventive care", "annual physical", "wellness exam"]),
    ("urgent care", ["urgent care", "walk-in", "same-day", "same day", "immediate care", "minor injury", "illness", "x-ray"]),
    ("community health", ["community health", "neighborhood health", "underserved", "safety net", "low-income", "low income", "uninsured", "underinsured", "medicaid", "medi-cal", "health equity", "sliding scale"]),
    ("free clinic", ["free clinic", "free medical", "volunteer", "charitable", "no-cost", "no cost", "donation"]),
    ("pediatrics", ["pediatric", "pediatrics", "children", "child", "families", "adolescent"]),
    ("women's health", ["women's health", "women health", "ob/gyn", "obgyn", "gynecology", "prenatal", "reproductive health", "family planning"]),
    ("occupational medicine", ["occupational medicine", "occupational health", "work injury", "workers compensation", "employment physical", "medical exams", "drug testing", "dot physical"]),
    ("dermatology", ["dermatology", "skin", "acne", "rashes"]),
    ("orthopedics", ["orthopedic", "orthopedics", "sports medicine", "joint", "bone"]),
    ("imaging/outpatient services", ["imaging", "radiology", "outpatient", "diagnostic", "ultrasound", "mri", "ct scan"]),
    ("behavioral health", ["behavioral health", "mental health", "counseling", "substance use"]),
    ("multilingual care", ["multilingual", "spanish", "language access", "translation", "interpreter", "culturally", "immigrant"]),
]

ORG_TYPE_KEYWORDS: list[tuple[str, list[str]]] = [
    ("nonprofit clinic", ["nonprofit", "non-profit", "mission", "serve", "community"]),
    ("federally qualified health center", ["federally qualified", "fqhc", "community health center"]),
    ("private practice", ["private practice", "physician-owned", "medical group"]),
    ("outpatient clinic", ["outpatient", "clinic", "ambulatory"]),
]

TASKS_BY_SERVICE: dict[str, str] = {
    "urgent care": "patient check-in, intake, rooming, vitals, walk-in flow, front-desk coordination, back-office support, and helping the team keep visits moving",
    "primary care": "patient intake, rooming, vitals, preventive-care workflow, referrals, scheduling, EHR/admin support, and patient communication",
    "community health": "patient intake, rooming, vitals, front/back-office clinic flow, patient communication, and support for patients who may need extra help navigating care",
    "free clinic": "intake, rooming, vitals, volunteer clinic workflow, patient communication, and practical back-office support",
    "pediatrics": "family communication, rooming, vitals, front-desk coordination, and pediatric clinic flow",
    "women's health": "patient intake, rooming, scheduling, front/back-office workflow, and respectful patient communication",
    "occupational medicine": "check-in, screening workflow, exam preparation, vitals, documentation support, and occupational-health clinic flow",
    "imaging/outpatient services": "patient check-in, outpatient coordination, documentation support, patient communication, referrals, and appointment flow",
    "dermatology": "patient rooming, intake, documentation support, appointment flow, and specialty-clinic operations",
    "orthopedics": "patient intake, appointment flow, rooming, documentation support, and specialty-clinic operations",
}

INTEREST_BY_SERVICE: dict[str, str] = {
    "urgent care": "I am interested in urgent care because it would teach me to stay organized and useful in a fast-paced clinic where patients need timely help.",
    "primary care": "I am interested in primary care because it would let me learn steady clinic workflow, patient communication, and how a care team supports patients over time.",
    "community health": "I am especially interested in community clinics because I want experience serving low-income, uninsured, underinsured, or underserved patients in a practical, patient-facing way.",
    "free clinic": "I am also open to volunteer-based clinical experience if that is the best way to earn trust, learn the workflow, and become useful to the team.",
    "pediatrics": "I would be excited to learn in a pediatric setting because it requires clear communication, patience, and strong front/back-office coordination.",
    "women's health": "I would be grateful to learn in a women's health setting and support respectful, organized clinic workflows wherever an extern can help.",
    "occupational medicine": "I am interested in occupational medicine because it involves structured exams, screenings, documentation, and reliable clinic operations.",
    "imaging/outpatient services": "I am interested in outpatient clinic support because it would help me learn patient coordination, scheduling, documentation, and referral-based care flow.",
    "dermatology": "I am interested in specialty clinics because they would help me learn focused patient intake, documentation, and rooming workflows.",
    "orthopedics": "I am interested in specialty clinics because they would help me learn focused patient intake, documentation, and rooming workflows.",
}


@dataclass
class WebsiteProfile:
    clinic_name: str
    source_url: str = ""
    fetched: bool = False
    services: list[str] | None = None
    org_types: list[str] | None = None
    title: str = ""
    evidence: list[str] | None = None
    pages_checked: list[str] | None = None

    def as_dict(self) -> dict:
        data = asdict(self)
        data["services"] = self.services or []
        data["org_types"] = self.org_types or []
        data["evidence"] = self.evidence or []
        data["pages_checked"] = self.pages_checked or []
        return data


def _load_cache() -> dict[str, dict]:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(cache: dict[str, dict]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")


def _cache_key(lead: Lead) -> str:
    primary = lead.website or lead.contact_page or lead.source_url or lead.google_place_id or lead.clinic_name
    return re.sub(r"\s+", " ", f"{lead.clinic_name}|{primary}").strip().lower()


def _urls_for_lead(lead: Lead) -> list[str]:
    urls: list[str] = []
    for raw in [lead.website, lead.contact_page, lead.careers_page, lead.source_url]:
        url = (raw or "").strip()
        if url.startswith(("http://", "https://")) and url not in urls:
            urls.append(url)
    for raw in lead.pages_checked or []:
        url = raw.split(" (")[0].strip()
        if url.startswith(("http://", "https://")) and url not in urls:
            urls.append(url)
    return urls[: max(1, get_int_env("EXTERNSHIP_TAILOR_MAX_PAGES", 6))]


def _extract_title(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html or "", flags=re.I | re.S)
    if not m:
        return ""
    return re.sub(r"\s+", " ", clean_html_text(m.group(1))).strip()[:160]


def _sentence_snippets(text: str, terms: list[str], limit: int = 3) -> list[str]:
    snippets: list[str] = []
    parts = re.split(r"(?<=[.!?])\s+", text or "")
    for sentence in parts:
        s = sentence.strip()
        if len(s) < 35 or len(s) > 260:
            continue
        lower = s.lower()
        if any(term in lower for term in terms):
            if any(bad in lower for bad in ["cookie", "copyright", "privacy policy", "terms of use", "javascript", "all rights reserved", "log in"]):
                continue
            snippets.append(s)
        if len(snippets) >= limit:
            break
    return snippets


def _matches_from_text(text: str, lead: Lead) -> tuple[list[str], list[str], list[str]]:
    hay = " ".join([
        text or "",
        lead.clinic_name or "",
        lead.specialty or "",
        lead.tags or "",
        lead.source_note or "",
        lead.notes or "",
        lead.npi_taxonomies or "",
    ]).lower()
    services: list[str] = []
    for label, terms in SERVICE_KEYWORDS:
        if any(term in hay for term in terms) and label not in services:
            services.append(label)
    orgs: list[str] = []
    for label, terms in ORG_TYPE_KEYWORDS:
        if any(term in hay for term in terms) and label not in orgs:
            orgs.append(label)
    evidence_terms = [t for _, terms in SERVICE_KEYWORDS + ORG_TYPE_KEYWORDS for t in terms]
    evidence = _sentence_snippets(text, evidence_terms, limit=4)
    return services[:5], orgs[:3], evidence


def _same_host(a: str, b: str) -> bool:
    pa = urlparse(a)
    pb = urlparse(b)
    if not pa.netloc or not pb.netloc:
        return False
    return pa.netloc.replace("www.", "") == pb.netloc.replace("www.", "")


def website_profile_for_lead(lead: Lead, *, force_refresh: bool = False) -> WebsiteProfile:
    if not get_bool_env("EXTERNSHIP_TAILOR_FROM_WEBSITE", True):
        services, orgs, evidence = _matches_from_text("", lead)
        return WebsiteProfile(lead.clinic_name, fetched=False, services=services, org_types=orgs, evidence=evidence)

    cache = _load_cache()
    key = _cache_key(lead)
    if not force_refresh and key in cache:
        item = cache[key]
        return WebsiteProfile(
            clinic_name=item.get("clinic_name", lead.clinic_name),
            source_url=item.get("source_url", ""),
            fetched=bool(item.get("fetched")),
            services=list(item.get("services") or []),
            org_types=list(item.get("org_types") or []),
            title=item.get("title", ""),
            evidence=list(item.get("evidence") or []),
            pages_checked=list(item.get("pages_checked") or []),
        )

    pages_checked: list[str] = []
    combined_text = ""
    title = ""
    source_url = ""
    urls = _urls_for_lead(lead)
    max_pages = max(1, get_int_env("EXTERNSHIP_TAILOR_MAX_PAGES", 6))

    idx = 0
    while idx < len(urls) and len(pages_checked) < max_pages:
        url = urls[idx]
        idx += 1
        html, status = fetch_url(url, timeout=10)
        pages_checked.append(f"{url} ({status})")
        if status == "ok" and html:
            if not source_url:
                source_url = url
            if not title:
                title = _extract_title(html)
            text = clean_html_text(html)
            combined_text += " " + text[:12000]
            for extra in extract_candidate_links(url, html, limit=8):
                if extra in urls or not _same_host(url, extra):
                    continue
                lower = extra.lower()
                if any(term in lower for term in ["about", "services", "program", "patient", "care", "contact", "extern", "volunteer", "career", "work", "mission"]):
                    urls.append(extra)

    services, orgs, evidence = _matches_from_text(combined_text, lead)
    profile = WebsiteProfile(
        clinic_name=lead.clinic_name,
        source_url=source_url,
        fetched=bool(combined_text.strip()),
        services=services,
        org_types=orgs,
        title=title,
        evidence=evidence,
        pages_checked=pages_checked,
    )
    cache[key] = profile.as_dict()
    _save_cache(cache)
    return profile


def _primary_service(services: list[str]) -> str:
    for key in [
        "community health",
        "free clinic",
        "urgent care",
        "occupational medicine",
        "pediatrics",
        "women's health",
        "primary care",
        "imaging/outpatient services",
        "dermatology",
        "orthopedics",
    ]:
        if key in services:
            return key
    return services[0] if services else ""


def _human_list(items: list[str]) -> str:
    cleaned = [x for x in items if x]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f"{cleaned[0]} and {cleaned[1]}"
    return ", ".join(cleaned[:-1]) + f", and {cleaned[-1]}"


def tailoring_lines_for_lead(lead: Lead, *, force_refresh: bool = False) -> dict[str, str]:
    # Prefer persisted fields when available, unless forced.
    if not force_refresh and lead.tailored_interest and lead.tailored_tasks:
        noticed = lead.tailored_noticed or (
            f"I looked through the clinic information I found and noticed that {lead.clinic_name} appears connected to {lead.site_services}."
            if lead.site_services else
            f"I looked through the information I found for {lead.clinic_name}."
        )
        return {
            "noticed": noticed,
            "interest": lead.tailored_interest,
            "tasks": lead.tailored_tasks,
            "source_note": lead.website_evidence or lead.tailoring_source or "",
            "services": lead.site_services,
            "org_types": lead.site_org_types,
            "title": lead.website_profile_title,
            "source_url": lead.tailoring_source,
        }

    profile = website_profile_for_lead(lead, force_refresh=force_refresh)
    clinic = lead.clinic_name or "your clinic"
    services = profile.services or []
    orgs = profile.org_types or []
    source_word = "your website" if profile.fetched else "the clinic information I found"

    if services:
        service_text = _human_list(services[:3])
        noticed = f"I looked through {source_word} and noticed that {clinic} appears connected to {service_text}."
    elif lead.specialty:
        noticed = f"I looked through {source_word} and saw that {clinic} is connected to {lead.specialty}."
    else:
        noticed = f"I looked through {source_word} and saw that {clinic} is a local care setting where I could learn real clinic workflow."

    primary_service = _primary_service(services)
    interest = INTEREST_BY_SERVICE.get(primary_service) or (
        "I am interested in learning in a real patient-facing clinic environment where I can become useful with front-office and back-office tasks."
    )
    tasks = TASKS_BY_SERVICE.get(primary_service) or (
        "patient intake, rooming, vitals, scheduling/front-desk support, EHR/admin help, patient communication, and general front/back-office clinic workflow"
    )

    if "multilingual care" in services:
        interest += " I also noticed an emphasis on language access or culturally responsive care, which stood out to me because communication is a big part of the healthcare experience I want."
    if "community health" in services and "low-income" not in interest.lower():
        interest += " I am also motivated by clinics that serve low-income or underserved communities."

    evidence = ""
    if profile.evidence:
        evidence = "Website signals used: " + " / ".join(profile.evidence[:2])
    elif profile.source_url:
        evidence = f"Tailoring source: {profile.source_url}"

    return {
        "noticed": noticed,
        "interest": interest,
        "tasks": tasks,
        "source_note": evidence,
        "services": _human_list(services[:4]) if services else "",
        "org_types": _human_list(orgs[:3]) if orgs else "",
        "title": profile.title,
        "source_url": profile.source_url,
    }


def apply_tailoring_to_lead(lead: Lead, *, force_refresh: bool = False) -> Lead:
    lines = tailoring_lines_for_lead(lead, force_refresh=force_refresh)
    lead.site_services = lines.get("services", "")
    lead.site_org_types = lines.get("org_types", "")
    lead.tailored_noticed = lines.get("noticed", "")
    lead.tailored_interest = lines.get("interest", "")
    lead.tailored_tasks = lines.get("tasks", "")
    lead.tailoring_source = lines.get("source_url", "")
    lead.website_evidence = lines.get("source_note", "")
    lead.website_profile_title = lines.get("title", "")
    lead.website_profile_fetched_at = datetime.now().replace(microsecond=0).isoformat()
    if lines.get("services") and lines.get("services") not in (lead.tags or ""):
        lead.tags = (lead.tags + " | tailored: " + lines["services"]).strip(" |")
    return lead


def tailor_leads(leads: list[Lead], *, top: int | None = None, force_refresh: bool = False) -> list[Lead]:
    selected = leads[:top] if top else leads
    total = len(selected)
    for i, lead in enumerate(selected, start=1):
        print(f"[{i}/{total}] Tailoring email copy from website: {lead.clinic_name}")
        try:
            apply_tailoring_to_lead(lead, force_refresh=force_refresh)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            lead.notes = (lead.notes + f" | tailoring_error:{exc}").strip(" |")
            print(f"  ! tailoring failed: {exc}")
    return leads
