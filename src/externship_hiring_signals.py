from __future__ import annotations

import csv
import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

from src.externship_config import ROOT, get_int_env
from src.externship_contact_finder import clean_html_text, extract_candidate_links, fetch_url
from src.externship_models import Lead

CACHE_PATH = ROOT / "data" / "externship_hiring_signals.json"

JOB_TITLE_TERMS = [
    "medical assistant",
    "certified medical assistant",
    "cma",
    "registered medical assistant",
    "rma",
    "medical receptionist",
    "front office medical assistant",
    "back office medical assistant",
    "clinical assistant",
    "patient care assistant",
    "patient services representative",
    "patient service representative",
    "patient care coordinator",
    "clinic assistant",
    "health center assistant",
    "externship",
    "extern",
]

HIRING_CONTEXT_TERMS = [
    "hiring",
    "job",
    "jobs",
    "career",
    "careers",
    "opening",
    "openings",
    "position",
    "positions",
    "apply",
    "employment",
    "join our team",
    "recruiting",
    "talent",
]

CAREERS_LINK_TERMS = [
    "career",
    "careers",
    "jobs",
    "job-openings",
    "job_openings",
    "employment",
    "join-our-team",
    "join our team",
    "work-with-us",
    "work with us",
    "opportunities",
    "open positions",
    "openings",
    "greenhouse",
    "lever.co",
    "workday",
    "adp",
    "icims",
    "paylocity",
    "bamboohr",
    "ashbyhq",
]

GUESS_PATHS = [
    "/careers",
    "/career",
    "/jobs",
    "/job-openings",
    "/employment",
    "/join-our-team",
    "/join-us",
    "/work-with-us",
    "/opportunities",
]

BAD_PAGE_TERMS = [
    "privacy policy",
    "terms of use",
    "cookie policy",
    "javascript is disabled",
    "enable javascript",
]

@dataclass
class HiringSignal:
    clinic_name: str
    status: str = "no_signal"  # active_ma_opening, careers_page_found, externship_signal, no_signal, blocked/error
    title: str = ""
    url: str = ""
    summary: str = ""
    evidence: str = ""
    checked_at: str = ""
    pages_checked: list[str] | None = None

    def to_dict(self) -> dict:
        data = asdict(self)
        data["pages_checked"] = self.pages_checked or []
        return data


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _domain(url: str) -> str:
    try:
        host = urlparse(url if "://" in url else "https://" + url).netloc.lower()
    except Exception:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def _base_url(url: str) -> str:
    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url
    try:
        p = urlparse(url)
        if not p.netloc:
            return ""
        return f"{p.scheme}://{p.netloc}"
    except Exception:
        return ""


def _same_or_known_job_host(base: str, candidate: str) -> bool:
    c = (candidate or "").lower()
    bdom = _domain(base)
    cdom = _domain(candidate)
    if bdom and cdom and (bdom == cdom or cdom.endswith("." + bdom)):
        return True
    return any(host in c for host in ["greenhouse.io", "lever.co", "workdayjobs.com", "myworkdayjobs.com", "icims.com", "paylocity.com", "bamboohr.com", "ashbyhq.com", "adp.com", "smartrecruiters.com"])


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
    return re.sub(r"\s+", " ", f"{lead.clinic_name}|{lead.website or lead.careers_page or lead.source_url}").strip().lower()


def _candidate_urls(lead: Lead) -> list[str]:
    urls: list[str] = []
    for raw in [lead.careers_page, lead.website, lead.contact_page, lead.source_url]:
        url = (raw or "").strip()
        if url.startswith(("http://", "https://")) and url not in urls:
            urls.append(url)
    for raw in lead.pages_checked or []:
        url = raw.split(" (")[0].strip()
        if url.startswith(("http://", "https://")) and url not in urls:
            urls.append(url)
    # Guess common careers paths from the main website.
    base = _base_url(lead.website or lead.contact_page or lead.source_url or "")
    if base:
        for path in GUESS_PATHS:
            guessed = base.rstrip("/") + path
            if guessed not in urls:
                urls.append(guessed)
    return urls


def _is_careers_like(url: str, label: str = "") -> bool:
    hay = f"{url} {label}".lower()
    return any(term in hay for term in CAREERS_LINK_TERMS)


def _extract_more_career_links(base_url: str, html: str, limit: int = 12) -> list[str]:
    found: list[str] = []
    # First use the existing extractor, then add job-board links it might not pick up.
    for link in extract_candidate_links(base_url, html, limit=limit):
        if _is_careers_like(link) and link not in found:
            found.append(link)
    for match in re.finditer(r"<a\s+[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", html or "", flags=re.I | re.S):
        href = match.group(1).strip()
        label = clean_html_text(match.group(2))
        absolute = urljoin(base_url, href)
        if not absolute.startswith(("http://", "https://")):
            continue
        if not _same_or_known_job_host(base_url, absolute):
            continue
        if _is_careers_like(absolute, label) and absolute not in found:
            found.append(absolute)
        if len(found) >= limit:
            break
    return found


def _near_hiring_context(text: str, term: str, window: int = 180) -> bool:
    hay = (text or "").lower()
    term = term.lower()
    start = 0
    while True:
        idx = hay.find(term, start)
        if idx < 0:
            return False
        chunk = hay[max(0, idx - window): idx + len(term) + window]
        if any(ctx in chunk for ctx in HIRING_CONTEXT_TERMS):
            return True
        start = idx + len(term)


def _title_from_text(text: str) -> str:
    compact = re.sub(r"\s+", " ", text or " ").strip()
    patterns = [
        r"(?i)(medical assistant[^|•\n\r]{0,90})",
        r"(?i)((?:front|back) office medical assistant[^|•\n\r]{0,90})",
        r"(?i)(certified medical assistant[^|•\n\r]{0,90})",
        r"(?i)(patient care coordinator[^|•\n\r]{0,90})",
        r"(?i)(medical receptionist[^|•\n\r]{0,90})",
        r"(?i)(clinic assistant[^|•\n\r]{0,90})",
        r"(?i)(medical assistant extern[^|•\n\r]{0,90})",
    ]
    for pat in patterns:
        m = re.search(pat, compact)
        if m:
            title = re.sub(r"\s+", " ", m.group(1)).strip(" -:|•")
            return title[:140]
    return ""


def _sentence_with_terms(text: str, terms: list[str], limit: int = 240) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", text or "")
    for sentence in sentences:
        s = re.sub(r"\s+", " ", sentence).strip()
        if len(s) < 20:
            continue
        lower = s.lower()
        if any(bad in lower for bad in BAD_PAGE_TERMS):
            continue
        if any(term in lower for term in terms):
            return s[:limit]
    return ""


def hiring_signal_for_lead(lead: Lead, *, force_refresh: bool = False) -> HiringSignal:
    cache = _load_cache()
    key = _cache_key(lead)
    if not force_refresh and key in cache:
        item = cache[key]
        return HiringSignal(
            clinic_name=item.get("clinic_name", lead.clinic_name),
            status=item.get("status", "no_signal"),
            title=item.get("title", ""),
            url=item.get("url", ""),
            summary=item.get("summary", ""),
            evidence=item.get("evidence", ""),
            checked_at=item.get("checked_at", ""),
            pages_checked=item.get("pages_checked", []),
        )

    max_pages = max(3, get_int_env("EXTERNSHIP_HIRING_SCAN_MAX_PAGES", 10))
    pages_checked: list[str] = []
    seen: set[str] = set()
    queue = _candidate_urls(lead)
    careers_page_seen = ""
    externship_seen = ""
    errors: list[str] = []

    while queue and len(pages_checked) < max_pages:
        url = queue.pop(0)
        if not url or url in seen:
            continue
        seen.add(url)
        html, status = fetch_url(url, timeout=12)
        pages_checked.append(f"{url} ({status})")
        if status != "ok" or not html:
            errors.append(status)
            continue
        text = clean_html_text(html)
        lower = text.lower()
        if any(term in lower for term in ["externship", "extern", "student placement", "clinical training"]):
            externship_seen = externship_seen or url
        if _is_careers_like(url) or any(term in lower for term in ["career", "jobs", "open positions", "current openings", "join our team"]):
            careers_page_seen = careers_page_seen or url
        # Active medical assistant / clinic-support job signal.
        for term in JOB_TITLE_TERMS:
            if term in lower and _near_hiring_context(text, term):
                title = _title_from_text(text) or term.title()
                evidence = _sentence_with_terms(text, [term] + HIRING_CONTEXT_TERMS)
                sig = HiringSignal(
                    clinic_name=lead.clinic_name,
                    status="active_ma_opening",
                    title=title,
                    url=url,
                    summary="Found a likely active medical-assistant/clinic-support hiring signal on the clinic or careers site.",
                    evidence=evidence,
                    checked_at=_now(),
                    pages_checked=pages_checked,
                )
                cache[key] = sig.to_dict()
                _save_cache(cache)
                return sig
        # Add career links discovered on official site.
        for link in _extract_more_career_links(url, html, limit=8):
            if link not in seen and link not in queue:
                queue.append(link)
        time.sleep(0.15)

    if externship_seen:
        sig = HiringSignal(
            clinic_name=lead.clinic_name,
            status="externship_signal",
            title="Externship / student-placement signal",
            url=externship_seen,
            summary="Found externship, student-placement, or clinical-training language, but not a clear active medical-assistant job posting.",
            evidence="",
            checked_at=_now(),
            pages_checked=pages_checked,
        )
    elif careers_page_seen:
        sig = HiringSignal(
            clinic_name=lead.clinic_name,
            status="careers_page_found",
            title="Careers page found",
            url=careers_page_seen,
            summary="Found a careers/jobs path, but no clear medical-assistant-specific opening in the scanned pages.",
            evidence="",
            checked_at=_now(),
            pages_checked=pages_checked,
        )
    else:
        # Distinguish real "no signal" from fetch/SSL failure. v8 could turn every
        # clinic into no_signal when macOS cert verification failed, which then made
        # --require-hiring-signal filter out all Apollo targets.
        error_text = "; ".join(errors[:5])
        fetch_failed = bool(errors) and len(errors) >= max(1, len(pages_checked))
        if fetch_failed and any(token in error_text.lower() for token in ["ssl", "certificate", "url_error", "timeout", "connection"]):
            status = "fetch_error"
            summary = "Could not verify hiring pages because the public website fetch failed; this is not evidence that the clinic is not hiring."
        else:
            status = "no_signal" if pages_checked else "blocked_or_no_website"
            summary = "No active medical-assistant hiring signal found in the scanned pages."
        sig = HiringSignal(
            clinic_name=lead.clinic_name,
            status=status,
            title="",
            url="",
            summary=summary,
            evidence=error_text,
            checked_at=_now(),
            pages_checked=pages_checked,
        )
    # Cache true signals and true no_signal results. Do not cache transient network
    # fetch_error rows; reruns should be able to recover automatically.
    if sig.status != "fetch_error":
        cache[key] = sig.to_dict()
        _save_cache(cache)
    return sig


def apply_hiring_signal(lead: Lead, signal: HiringSignal) -> Lead:
    lead.hiring_signal_status = signal.status
    lead.hiring_signal_title = signal.title
    lead.hiring_signal_url = signal.url
    lead.hiring_signal_summary = signal.summary
    lead.hiring_signal_evidence = signal.evidence
    lead.hiring_signal_checked_at = signal.checked_at
    if signal.url and not lead.careers_page and signal.status in {"active_ma_opening", "careers_page_found", "externship_signal"}:
        lead.careers_page = signal.url
    if signal.pages_checked:
        merged = list(lead.pages_checked or [])
        for page in signal.pages_checked:
            if page not in merged:
                merged.append(page)
        lead.pages_checked = merged[-60:]
    if signal.status == "active_ma_opening":
        lead.apollo_contact_strategy = "Target recruiter/talent acquisition first, then clinic/practice/office manager for this active MA opening."
    elif signal.status in {"careers_page_found", "externship_signal"}:
        lead.apollo_contact_strategy = "Target HR/recruiting plus clinic/practice/office manager; verify role by call/email."
    else:
        lead.apollo_contact_strategy = "No active hiring signal found yet; treat Apollo contacts as decision-maker leads, not confirmed hiring owners."
    return lead


def scan_hiring_signals(leads: list[Lead], *, top: int | None = None, force_refresh: bool = False, report_csv: Path | None = None) -> list[Lead]:
    selected = leads[:top] if top else leads
    rows: list[dict[str, str]] = []
    for i, lead in enumerate(selected, 1):
        print(f"[{i}/{len(selected)}] Hiring scan: {lead.clinic_name}")
        try:
            signal = hiring_signal_for_lead(lead, force_refresh=force_refresh)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            signal = HiringSignal(
                clinic_name=lead.clinic_name,
                status="scan_error",
                summary=str(exc)[:300],
                checked_at=_now(),
                pages_checked=[],
            )
        apply_hiring_signal(lead, signal)
        rows.append({
            "clinic_name": lead.clinic_name,
            "status": lead.hiring_signal_status,
            "title": lead.hiring_signal_title,
            "url": lead.hiring_signal_url,
            "summary": lead.hiring_signal_summary,
            "evidence": lead.hiring_signal_evidence,
        })
    if report_csv:
        report_csv.parent.mkdir(parents=True, exist_ok=True)
        with report_csv.open("w", newline="", encoding="utf-8") as f:
            fields = ["clinic_name", "status", "title", "url", "summary", "evidence"]
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
    return leads
