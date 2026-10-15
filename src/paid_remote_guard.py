"""Install paid AND remote eligibility before Handshake's apply actions.

Only job detail pages are opened during discovery; external application tabs
are never opened for rejected/unknown-pay jobs.
"""
from __future__ import annotations
from .remote_only_guard import classify_remote, _posting_text
from .verified_paid_guard import verify_paid
from urllib.parse import urlparse
import re
import json
from pathlib import Path
_HISTORY_PATH = Path(__file__).resolve().parent.parent / "data" / "auto_submitted_handshake_jobs.json"

def _confirmed_ids():
    try:
        value=json.loads(_HISTORY_PATH.read_text())
        return set(value) if isinstance(value,list) else set()
    except (FileNotFoundError, ValueError, OSError):
        return set()

def _record_confirmed(key):
    ids=_confirmed_ids()
    ids.add(str(key))
    _HISTORY_PATH.parent.mkdir(parents=True,exist_ok=True)
    tmp=_HISTORY_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(sorted(ids),indent=2))
    tmp.replace(_HISTORY_PATH)

_SEEN_HANDSHAKE_JOBS = set()
_ELIGIBLE_PAGE_IDS = set()

def _enabled(name):
    import os
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _may_submit(page):
    # Native applications require explicit opt-in AND a page-level eligibility
    # decision from this same run. Other code cannot bypass this by flipping a flag.
    if not _enabled("AUTO_SUBMIT_VERIFIED"):
        return False
    if any(_enabled(name) for name in ("NO_AUTO_SUBMIT", "HANDSHAKE_DRAFT_ONLY", "HANDSHAKE_REVIEW_ONLY")):
        return False
    if id(page) not in _ELIGIBLE_PAGE_IDS:
        return False
    # Fail closed on mandatory onsite language revealed later in screening forms.
    try:
        text = page.locator("body").inner_text(timeout=2500).lower()
        if re.search(r'(?:required|must|expected|mandatory).{0,110}(?:in.person|onsite|on.site|office|commut|travel)', text):
            return False
        if re.search(r'(?:office|in.person|onsite|on.site).{0,110}(?:required|must|expected|mandatory)', text):
            return False
    except Exception:
        return False
    return True




def install_verified_paid_remote_guard():
    import src.handshake as hs
    if getattr(hs, '_PAID_REMOTE_GUARD_INSTALLED', False):
        return
    original = hs.inspect_job
    original_native_submit = hs.submit_handshake_native_application

    def inspect(page, job_url, number, total, tab_number):
        _ELIGIBLE_PAGE_IDS.discard(id(page))
        title = 'Unknown job'
        company = 'Unknown company'
        reason = 'unable to verify eligibility'
        # A canonical listing ID is stable even when searchId/tracking varies.
        match = re.search(r'/jobs/(\d+)', str(job_url))
        key = match.group(1) if match else str(job_url).split('?')[0]
        if key in _SEEN_HANDSHAKE_JOBS or key in _confirmed_ids():
            print(f'  SKIP duplicate Handshake job: {key}')
            return hs.HandshakeJob(title='Duplicate job', company='Unknown company',
                handshake_url=job_url, application_type='skipped_duplicate', tab_number=tab_number)
        _SEEN_HANDSHAKE_JOBS.add(key)
        try:
            page.goto(job_url, wait_until='domcontentloaded', timeout=45000)
            page.wait_for_timeout(900)
            title = hs.get_job_title(page)
            company = hs.get_company_name(page)
            if not company or company.strip().lower() == 'unknown company':
                # Handshake commonly titles its detail pages as:
                # "Role | Employer | Handshake". Only trust that explicit format.
                try:
                    parts = [part.strip() for part in page.title().split('|')]
                    if len(parts) >= 3 and parts[-1].lower().find('handshake') >= 0:
                        candidate = parts[-2]
                        if candidate and candidate.lower() not in {'jobs', 'handshake'}:
                            company = candidate
                except Exception:
                    pass
            body = _posting_text(page)
            if not body or not company or company.strip().lower() == 'unknown company':
                reason = 'company or exact job description not identified'
                raise ValueError(reason)
            marketing_terms = ('marketing', 'social media', 'content creator', 'brand', 'growth marketing', 'communications', 'seo', 'advertising')
            internship_terms = ('intern', 'internship')
            if not any(term in title.lower() for term in marketing_terms) or not any(term in title.lower() for term in internship_terms):
                reason = 'not a marketing internship'
                raise ValueError(reason)
            remote = classify_remote(title, body)
            if not remote.allowed:
                reason = 'not fully remote: ' + remote.reason
            else:
                paid = verify_paid(title, company, body)
                if paid.allowed:
                    print(f'  VERIFIED PAID + REMOTE: {company} — {title} ({paid.source or "job details"})')
                    _ELIGIBLE_PAGE_IDS.add(id(page))
                    try:
                        result = original(page, job_url, number, total, tab_number)
                        if getattr(result, "application_type", "") == "handshake_submitted":
                            _record_confirmed(key)
                        return result
                    finally:
                        _ELIGIBLE_PAGE_IDS.discard(id(page))
                reason = 'not verified paid: ' + paid.reason
        except Exception as exc:
            if not isinstance(exc, ValueError):
                reason = f'could not verify role ({type(exc).__name__})'
        print(f'  SKIP before application: {company} — {title}: {reason}')
        return hs.HandshakeJob(title=title, company=company, handshake_url=job_url,
                               application_type='skipped_eligibility', tab_number=tab_number)

    hs.inspect_job = inspect
    # A separate hard-stop layer even when a user forgets environment settings.
    hs.auto_submit_handshake_resume_drops_enabled = lambda: _enabled("AUTO_SUBMIT_VERIFIED") and not any(
        _enabled(name) for name in ("NO_AUTO_SUBMIT", "HANDSHAKE_DRAFT_ONLY", "HANDSHAKE_REVIEW_ONLY")
    )

    def native_submit(page, *args, **kwargs):
        if not _may_submit(page):
            print("  BLOCKED native submit: page lacks verified eligibility or has onsite requirement")
            return False
        return original_native_submit(page, *args, **kwargs)

    hs.submit_handshake_native_application = native_submit
    hs._PAID_REMOTE_GUARD_INSTALLED = True
