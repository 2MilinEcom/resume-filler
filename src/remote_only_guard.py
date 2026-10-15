"""Fail-closed work-arrangement gate for Handshake marketing internship discovery.

Runs before any Handshake application controls are clicked.
No credentials, external requests, or application submissions are performed here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class RemoteDecision:
    allowed: bool
    reason: str


def classify_remote(title: str, description: str) -> RemoteDecision:
    title = str(title or '')
    body = str(description or '')
    # Ignore surrounding Handshake navigation/recommendation text as far as possible.
    s = re.sub(r'\s+', ' ', (title + ' ' + body).lower())
    if not s.strip():
        return RemoteDecision(False, 'no posting text available')

    # Remove explicit *negations* of an in-person requirement first.
    s = re.sub(r'\b(?:no|without|never|not)\s+(?:mandatory|required|regular|occasional\s+)?(?:in.person|on.site|onsite|office)\s+(?:attendance|visits?|days?|work|requirement[s]?)\s+(?:is\s+)?required\b', ' ', s)
    s = re.sub(r'\bno\s+(?:in.person|on.site|onsite|office)\s+(?:attendance|visits?|days?|requirements?)\b', ' ', s)

    disallowed = [
        (r'\bhybrid\b', 'hybrid work'),
        (r'\b(?:in.person|on.site|onsite)\s+(?:attendance|work|days?|visits?|meetings?|events?|training|orientation)\b', 'in-person obligation'),
        (r'\b(?:must|required|expected|mandatory|obligated)\b.{0,75}\b(?:commute|report to (?:the |an? )?office|come (?:in|to (?:the )?office)|visit (?:the )?office|work (?:in|at|from) (?:the |an? )?office|attend (?:in.person|on.site|onsite)|travel)\b', 'required onsite work or travel'),
        (r'\b(?:commute|office (?:attendance|visits?|days?)|in.person (?:attendance|events?|meetings?)|travel)\b.{0,70}\b(?:required|mandatory|expected|must)\b', 'required attendance/travel'),
        (r'\b(?:[1-5]|one|two|three|four|five)\s+days?\s+(?:per|a|each)\s+week\s+(?:in|at)\s+(?:the )?office\b', 'office days'),
        (r'\b(?:remote|work from home)\b.{0,100}\b(?:but|however|except)\b.{0,75}\b(?:onsite|on.site|in.person|office|travel)\b', 'remote with onsite exception'),
        (r'\b(?:relocat(?:e|ion)|willing to relocate)\s+(?:is\s+)?(?:required|mandatory)\b', 'relocation required'),
        (r'\b(?:fully )?(?:on.site|onsite|in.person)\s+(?:position|role|job|internship)\b', 'onsite role'),
    ]
    for pattern, reason in disallowed:
        if re.search(pattern, s):
            return RemoteDecision(False, reason)

    # 'Remote' must appear as a *work arrangement*, not merely a search keyword.
    positive = [
        r'\b(?:fully|100\s*%|entirely|completely|exclusively)\s+remote\b',
        r'\bremote\s*[-–—,/ ]+\s*(?:intern(?:ship)?|marketing|position|role|work|job|only|us|usa|united states|california|ca)\b',
        r'\b(?:work arrangement|work location|job location|workplace type|location type|work model|work setting)\s*[:\-]?\s*remote\b',
        r'\b(?:remote\s+(?:work|internship|marketing|position|role|job|opportunity))\b',
        r'\b(?:work from home|work from anywhere|telecommut(?:e|ing))\b',
        r'\bremote\s*\((?:us|usa|united states|california|ca|[a-z ]+ only)\)',
    ]
    if not any(re.search(p, s) for p in positive):
        return RemoteDecision(False, 'fully remote arrangement not explicitly verified')

    # State restrictions are allowed; requirements to visit a physical office are not.
    return RemoteDecision(True, 'explicit remote arrangement with no detected mandatory office requirement')


def _posting_text(page) -> str:
    """Prefer the job's content rather than global Handshake search/filter navigation."""
    selectors = [
        '[data-testid*="job-description" i]',
        '[data-testid*="job-details" i]',
        '[class*="job-description" i]',
        '[class*="job-details" i]',
        'main article',
        'main',
        'article',
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel)
            if loc.count():
                content = loc.first.inner_text(timeout=2500)
                if len(content.strip()) > 80:
                    # Handshake often includes paid/remote "Similar Jobs" cards inside main.
                    # Never treat a different job's compensation/location as proof.
                    content = re.split(r'(?im)^\s*(?:similar jobs|recommended jobs|jobs you may also like|alumni at this employer|about the employer|what they.re looking for)\s*$', content, maxsplit=1)[0]
                    return content[:35000]
        except Exception:
            continue
    # Reading the whole body could include 'Remote' as a menu filter.
    # Fail closed if no posting region can be identified.
    return ''


def install_remote_guard() -> None:
    import src.handshake as hs
    if getattr(hs, '_REMOTE_ONLY_PATCH_INSTALLED', False):
        return
    original_inspect = hs.inspect_job

    def guarded_inspect_job(page, job_url, number, total, tab_number):
        print(f'\n[{number}/{total}] Checking 100% remote eligibility BEFORE applying...')
        try:
            page.goto(job_url, wait_until='domcontentloaded', timeout=45000)
            try:
                page.wait_for_timeout(1000)
            except Exception:
                pass
            title = hs.get_job_title(page)
            company = hs.get_company_name(page)
            text = _posting_text(page)
            decision = classify_remote(title, text)
        except Exception as exc:
            title, company = 'Unknown job', 'Unknown company'
            decision = RemoteDecision(False, f'could not verify remote details ({type(exc).__name__})')
        if not decision.allowed:
            print(f'  SKIP non-verified fully remote: {company} — {title}: {decision.reason}')
            return hs.HandshakeJob(title=title, company=company, handshake_url=job_url,
                                   application_type='skipped_remote_mismatch', tab_number=tab_number)
        print(f'  VERIFIED remote: {company} — {title}')
        return original_inspect(page, job_url, number, total, tab_number)

    hs.inspect_job = guarded_inspect_job
    # Independently enforce review-only on native Handshake flows even if the
    # currently installed handshake.py is an older build without draft-only flags.
    hs.auto_submit_handshake_resume_drops_enabled = lambda: False
    hs.submit_handshake_native_application = lambda *args, **kwargs: False
    hs._REMOTE_ONLY_PATCH_INSTALLED = True
