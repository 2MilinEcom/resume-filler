from __future__ import annotations

import re
import ssl
import time
from html import unescape
from urllib.parse import urljoin, urlparse

import certifi
import requests
from requests.exceptions import RequestException, SSLError

from src.externship_models import Lead

EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
PHONE_RE = re.compile(r"(?:\+?1[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}")
BAD_EMAIL_TERMS = {
    "example.com",
    "email.com",
    "domain.com",
    "sentry.io",
    "wixpress.com",
    "wordpress.com",
    "schema.org",
}
GOOD_LINK_TERMS = ["contact", "career", "jobs", "volunteer", "externship", "internship", "student", "team", "about"]


def normalize_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"{digits[0:3]}{digits[3:6]}{digits[6:10]}"
    return digits


def clean_html_text(html: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36 ExternshipOutreachBot/1.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _is_html_response(content_type: str) -> bool:
    ctype = (content_type or "").lower()
    return (
        "text" in ctype
        or "html" in ctype
        or ctype.startswith("application/xhtml")
        or ctype.startswith("application/xml")
        or ctype == ""
    )


def fetch_url(url: str, timeout: int = 12) -> tuple[str, str]:
    """Fetch a public clinic/job page robustly.

    v8 used Python's stdlib TLS store, which can fail on macOS virtualenvs with:
    [SSL: CERTIFICATE_VERIFY_FAILED] unable to get local issuer certificate.
    v9 uses requests + certifi first, then a public-page-only unverified fallback so
    the hiring scan does not mislabel every clinic as no_signal. No credentials or
    private pages are fetched by this tool.
    """
    if not url or not url.startswith(("http://", "https://")):
        return "", "invalid_url"

    def _read(resp: requests.Response, status_suffix: str = "ok") -> tuple[str, str]:
        if resp.status_code >= 400:
            return "", f"http_{resp.status_code}"
        ctype = resp.headers.get("Content-Type", "")
        if not _is_html_response(ctype):
            return "", f"non_html:{ctype}"
        # Respect a firm cap so one bad page cannot blow up the scan.
        raw = resp.content[:800_000]
        enc = resp.encoding or resp.apparent_encoding or "utf-8"
        return raw.decode(enc, errors="replace"), status_suffix

    try:
        resp = requests.get(
            url,
            headers=HEADERS,
            timeout=timeout,
            allow_redirects=True,
            verify=certifi.where(),
        )
        return _read(resp, "ok")
    except SSLError as exc:
        # Public website fallback only. This avoids throwing away all hiring signals
        # when a clinic or job board has an incomplete certificate chain.
        try:
            resp = requests.get(
                url,
                headers=HEADERS,
                timeout=timeout,
                allow_redirects=True,
                verify=False,
            )
            html, status = _read(resp, "ok_ssl_unverified")
            if html:
                return html, status
            return html, status + f":{str(exc)[:120]}"
        except RequestException as exc2:
            return "", f"url_error_ssl:{str(exc2)[:180]}"
    except RequestException as exc:
        return "", f"url_error:{str(exc)[:180]}"
    except Exception as exc:
        return "", f"error:{type(exc).__name__}:{str(exc)[:180]}"


def extract_emails(text_or_html: str) -> list[str]:
    found = []
    for email in EMAIL_RE.findall(text_or_html or ""):
        email = email.strip(".,;:()[]{}<>").lower()
        if any(term in email for term in BAD_EMAIL_TERMS):
            continue
        if email.startswith(("noreply@", "no-reply@", "donotreply@")):
            continue
        if email not in found:
            found.append(email)
    return found


def extract_phones(text_or_html: str) -> list[str]:
    found = []
    for phone in PHONE_RE.findall(text_or_html or ""):
        clean = normalize_phone(phone)
        if len(clean) == 10 and clean not in found:
            found.append(clean)
    return found


def extract_candidate_links(base_url: str, html: str, limit: int = 12) -> list[str]:
    links: list[str] = []
    for match in re.finditer(r"<a\s+[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", html or "", flags=re.I | re.S):
        href = unescape(match.group(1)).strip()
        label = clean_html_text(match.group(2)).lower()
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"}:
            continue
        hay = f"{absolute.lower()} {label}"
        if not any(term in hay for term in GOOD_LINK_TERMS):
            continue
        if absolute not in links:
            links.append(absolute)
        if len(links) >= limit:
            break
    return links


def infer_contact_person_from_text(text: str) -> tuple[str, str]:
    # Conservative: only match explicit manager/coordinator patterns near names.
    patterns = [
        r"([A-Z][a-z]+\s+[A-Z][a-z]+)[,\s\-–—]+(?:our\s+)?(clinic manager|office manager|practice manager|volunteer coordinator|externship coordinator|program coordinator|director of [A-Za-z\s]+)",
        r"(clinic manager|office manager|practice manager|volunteer coordinator|externship coordinator|program coordinator|director of [A-Za-z\s]+)[,\s\-–—]+([A-Z][a-z]+\s+[A-Z][a-z]+)",
    ]
    for pat in patterns:
        m = re.search(pat, text or "")
        if not m:
            continue
        a, b = m.group(1).strip(), m.group(2).strip()
        if "manager" in a.lower() or "coordinator" in a.lower() or "director" in a.lower():
            return b, a
        return a, b
    return "", ""


def score_lead(lead: Lead) -> int:
    if getattr(lead, "excluded_reason", "") or getattr(lead, "status", "") == "excluded":
        return -999
    score = 0
    hay = " ".join([lead.clinic_name, lead.specialty, lead.tags, lead.source_note, lead.website, lead.contact_page, lead.notes]).lower()
    if "externship" in hay:
        score += 40
    if "medical assistant" in hay or "ma " in hay:
        score += 30
    if "community health" in hay or "clinic" in hay:
        score += 12
    if "volunteer" in hay:
        score += 8
    if lead.contact_email:
        score += 15
    if lead.main_phone:
        score += 10
    if lead.contact_name:
        score += 10
    if lead.npi_matched == "yes":
        score += 8
    if lead.google_place_id:
        score += 6
    try:
        if lead.distance_miles and float(lead.distance_miles) <= 35:
            score += 5
    except Exception:
        pass
    if "academy" in hay or "career services" in hay or "admissions" in hay or "tuition" in hay:
        score -= 80
    if "school coordinator required" in hay:
        score -= 25
    if "not accepting" in hay or "closed" in hay:
        score -= 20
    return score


def enrich_lead(lead: Lead, *, sleep_seconds: float = 0.25) -> Lead:
    urls = []
    for url in [lead.website, lead.contact_page, lead.careers_page, lead.source_url]:
        if url and url.startswith(("http://", "https://")) and url not in urls:
            urls.append(url)
    pages_checked = list(lead.pages_checked or [])
    emails = set(lead.emails_found or [])
    phones = set(lead.phones_found or [])
    found_links: list[str] = []
    notes = []

    for url in urls[:4]:
        html, status = fetch_url(url)
        pages_checked.append(f"{url} ({status})")
        if status == "ok" and html:
            emails.update(extract_emails(html))
            phones.update(extract_phones(html))
            text = clean_html_text(html)
            if not lead.contact_name or not lead.contact_title:
                name, title = infer_contact_person_from_text(text)
                if name and not lead.contact_name:
                    lead.contact_name = name
                if title and not lead.contact_title:
                    lead.contact_title = title
            for link in extract_candidate_links(url, html):
                if link not in urls and link not in found_links:
                    found_links.append(link)
        time.sleep(sleep_seconds)

    # Check a few likely internal pages discovered from official pages.
    for url in found_links[:8]:
        html, status = fetch_url(url)
        pages_checked.append(f"{url} ({status})")
        if status == "ok" and html:
            emails.update(extract_emails(html))
            phones.update(extract_phones(html))
        time.sleep(sleep_seconds)

    # Do not overwrite stronger public contact with random extracted email unless missing.
    emails = {e for e in emails if e and "@" in e}
    phones = {p for p in phones if len(p) == 10}
    if not lead.contact_email and emails:
        lead.contact_email = sorted(emails)[0]
    if not lead.main_phone and phones:
        lead.main_phone = sorted(phones)[0]
    lead.emails_found = sorted(emails)
    lead.phones_found = sorted(phones)
    lead.pages_checked = pages_checked[-30:]
    if notes:
        lead.notes = (lead.notes + " | " + " | ".join(notes)).strip(" |")
    return lead


def enrich_leads(leads: list[Lead], *, max_leads: int | None = None) -> list[Lead]:
    selected = leads[:max_leads] if max_leads else leads
    for i, lead in enumerate(selected, start=1):
        print(f"[{i}/{len(selected)}] Enriching: {lead.clinic_name}")
        try:
            enrich_lead(lead)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            lead.notes = (lead.notes + f" | enrich_error:{exc}").strip(" |")
    return leads
