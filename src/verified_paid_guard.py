"""Conservative compensation eligibility check for an EXACT internship.

Fail closed: no positive evidence => never open an external application.
Public web search is attempted for postings with no salary shown. No API key needed.
"""
from __future__ import annotations
import html
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass

@dataclass(frozen=True)
class PaidDecision:
    allowed: bool
    reason: str
    source: str = ''

NEGATIVE = [
    r'\bunpaid\b', r'\bnon[ -]?paid\b', r'\bwithout (?:pay|compensation)\b',
    r'\bno (?:monetary )?(?:compensation|pay|salary|stipend)\b',
    r'\bvolunteer (?:internship|position|role)\b',
    r'\bfor (?:academic |college )?credit only\b',
    r'\bnot (?:a )?paid (?:internship|position)\b',
]
POSITIVE = [
    r'\bpaid (?:internship|intern|position|role|opportunity)\b',
    r'\b(?:internship|intern|position|role) (?:is |will be )?paid\b',
    r'\b(?:hourly |annual )?(?:pay|salary|compensation|wage|stipend)\s*[:=]\s*\$\s*\d',
    r'\$\s*\d+(?:\.\d+)?\s*(?:-|to|–|—)\s*\$?\s*\d+(?:\.\d+)?\s*(?:/|per\s*)(?:hour|hr|year|yr|week|month)\b',
    r'\$\s*\d+(?:\.\d+)?\s*(?:/|per\s*)(?:hour|hr|year|yr|week|month)\b',
    r'\b(?:guaranteed|fixed)\s+(?:stipend|compensation)\s*(?:of|:)\s*\$\s*\d',
]


def classify_paid(text: str) -> PaidDecision:
    s = re.sub(r'\s+', ' ', str(text or '').lower())
    # Do not allow negated 'paid' to count as proof.
    for pattern in NEGATIVE:
        if re.search(pattern, s):
            return PaidDecision(False, 'explicitly unpaid or non-compensated')
    for pattern in POSITIVE:
        if re.search(pattern, s):
            return PaidDecision(True, 'explicit paid compensation in the exact posting')
    return PaidDecision(False, 'paid compensation not confirmed')


def _fetch(url: str, max_bytes: int = 150_000) -> str:
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (compatible; InternshipVerification/1.0)'})
    with urllib.request.urlopen(req, timeout=9) as res:
        return res.read(max_bytes).decode('utf-8', errors='replace')


def _clean_html(raw: str) -> str:
    raw = re.sub(r'(?is)<(script|style|nav|footer|aside)\b.*?</\1>', ' ', raw)
    raw = re.sub(r'(?s)<[^>]*>', ' ', raw)
    return re.sub(r'\s+', ' ', html.unescape(raw)).strip()


def _tokens(s: str) -> set[str]:
    stop = {'intern', 'internship', 'marketing', 'social', 'media', 'digital', 'and', 'the', 'for', 'with', 'group', 'inc', 'llc', 'at', 'of', 'a', 'an'}
    return {x for x in re.findall(r'[a-z0-9]+', s.lower()) if len(x)>2 and x not in stop}


def _same_posting(title: str, company: str, content: str) -> bool:
    lower = content.lower()
    if company and not any(x in lower for x in _tokens(company)):
        return False
    tt = _tokens(title)
    if tt and len(tt & _tokens(content)) < max(1, min(len(tt), 2)):
        return False
    # Generic 'marketing intern' alone cannot safely prove the match.
    if not tt and not ('marketing' in lower and 'intern' in lower):
        return False
    return True


def _bing_rss(title: str, company: str) -> list[tuple[str,str]]:
    query = f'"{company}" "{title}" (salary OR paid OR stipend OR compensation)'
    url = 'https://www.bing.com/search?format=rss&q=' + urllib.parse.quote(query)
    root = ET.fromstring(_fetch(url))
    result = []
    for item in root.findall('.//item')[:8]:
        link = item.findtext('link', '').strip()
        snippet = _clean_html((item.findtext('title') or '') + ' ' + (item.findtext('description') or ''))
        if link.startswith(('http://','https://')):
            result.append((link,snippet))
    return result


def research_compensation(title: str, company: str) -> PaidDecision:
    """Fetch independently indexed pages for exact title+employer; no guessed pay.

    Search snippets are discovery clues only. A source must show a matched posting,
    and we deliberately reject if no reliable full page substantiates compensation.
    """
    try:
        results = _bing_rss(title, company)
    except Exception as exc:
        return PaidDecision(False, f'compensation research unavailable ({type(exc).__name__})')
    for url, snippet in results:
        host = (urllib.parse.urlparse(url).hostname or '').lower()
        if not host or any(x in host for x in ('facebook.com','linkedin.com','reddit.com','youtube.com')):
            continue
        if not _same_posting(title,company,snippet):
            continue
        try:
            page = _clean_html(_fetch(url))[:180000]
        except Exception:
            continue
        if not _same_posting(title, company, page):
            continue
        # Prefer exact job title's nearby section, not unrelated recommended jobs.
        title_l = title.lower().strip()
        pos = page.lower().find(title_l)
        if pos < 0:
            continue
        local = page[max(0,pos-400):pos+5500]
        decision = classify_paid(local)
        if decision.allowed:
            return PaidDecision(True, 'independent page confirms pay for matching job; manually verify before submitting', url)
        if decision.reason.startswith('explicitly'):
            return PaidDecision(False, 'independent page describes internship as unpaid', url)
    return PaidDecision(False, 'no verified paid compensation found after web research')


def verify_paid(title: str, company: str, posting_text: str) -> PaidDecision:
    local = classify_paid(posting_text)
    if local.allowed:
        return local
    if local.reason.startswith('explicitly'):
        return local
    return research_compensation(title, company)
