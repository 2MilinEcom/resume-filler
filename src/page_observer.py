from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse


def _normalize_space(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def classify_page(snapshot: dict[str, Any]) -> str:
    url = str(snapshot.get("url") or "").lower()
    body = str(snapshot.get("body_text") or "").lower()
    title = str(snapshot.get("title") or "").lower()

    if "greenhouse.io" in url:
        return "greenhouse"

    # These terminal/manual states must win before URL-based SuccessFactors
    # classification. SuccessFactors often keeps login_ns=register in the URL
    # even after account creation, including on verification or blocked states.
    if any(term in body for term in ["captcha", "verify you are human", "human verification"]):
        return "human_verification"
    if any(term in body for term in [
        "verification code",
        "enter the code",
        "email verification",
        "check your email",
        "confirm your email",
        "verify your email",
        "activation email",
        "activate your account",
        "security code",
    ]):
        return "email_verification"

    if any(term in body for term in ["review your application", "review and submit", "submit application", "final step"]):
        return "final_review_or_submit"

    # SuccessFactors uses opaque session URLs. A URL such as
    # career2.successfactors...career_job_req_id=...&login_ns=register is an
    # account/application gate even when the visible body text is sparse or slow
    # to hydrate. This keeps the agent on the current session URL instead of
    # trying to reconstruct/open a shorter URL.
    if "successfactors" in url:
        sf_form_hits = sum(1 for term in [
            "first name", "last name", "email", "resume", "phone",
            "work authorization", "candidate profile", "my information",
            "experience", "education"
        ] if term in body)
        if "career_ns=job_application" in url or "career_job_req_id" in url:
            if sf_form_hits >= 3 or any(term in body for term in ["resume", "candidate profile", "my information"]):
                return "application_form"
            return "account_gate"
        if any(term in body for term in ["create an account", "already have an account", "choose password", "retype password", "new candidate", "returning candidate", "sign in to apply", "career opportunities: sign in"]):
            return "account_gate"

    if any(term in body for term in ["create an account", "already have an account", "choose password", "retype password", "new candidate", "returning candidate", "sign in to apply"]):
        return "account_gate"

    controls = snapshot.get("controls") or []
    input_like = [c for c in controls if c.get("role") in {"textbox", "combobox", "checkbox", "radio", "file", "select"}]
    body_form_hits = sum(1 for term in ["first name", "last name", "email", "phone", "resume", "work authorization", "my information", "candidate information"] if term in body)
    if len(input_like) >= 5 or body_form_hits >= 3:
        return "application_form"

    if "job details" in title or "/job/" in url or "/jobs/" in url:
        return "job_detail"
    return "listing_or_unknown"


def observe_page(page, *, max_body_chars: int = 16000, max_controls: int = 160) -> dict[str, Any]:
    """Return a compact but actionable browser snapshot.

    The JS assigns stable data-ai-agent-id refs to visible controls, so the
    browser action layer can execute the model's selected primitive action.
    """
    js = r"""
    ({ maxBodyChars, maxControls }) => {
      const norm = s => (s || '').replace(/\s+/g, ' ').trim();

      function visible(el) {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== 'none' &&
               style.visibility !== 'hidden' &&
               rect.width > 0 &&
               rect.height > 0 &&
               rect.bottom >= 0 && rect.right >= 0 &&
               rect.top <= (window.innerHeight || document.documentElement.clientHeight) + 1200;
      }

      function labelFor(el) {
        let pieces = [];
        const aria = el.getAttribute('aria-label');
        const labelledBy = el.getAttribute('aria-labelledby');
        const placeholder = el.getAttribute('placeholder');
        const title = el.getAttribute('title');
        const name = el.getAttribute('name');
        const id = el.getAttribute('id');
        if (aria) pieces.push(aria);
        if (title) pieces.push(title);
        if (placeholder) pieces.push(placeholder);
        if (labelledBy) {
          for (const part of labelledBy.split(/\s+/)) {
            const lab = document.getElementById(part);
            if (lab) pieces.push(lab.innerText || lab.textContent || '');
          }
        }
        if (id) {
          const lab = document.querySelector(`label[for="${CSS.escape(id)}"]`);
          if (lab) pieces.push(lab.innerText || lab.textContent || '');
        }
        let parent = el.parentElement;
        for (let depth = 0; parent && depth < 3; depth++, parent = parent.parentElement) {
          const text = norm(parent.innerText || parent.textContent || '');
          if (text && text.length < 300) pieces.push(text);
        }
        if (name) pieces.push(name);
        if (id) pieces.push(id);
        return norm(pieces.join(' | ')).slice(0, 600);
      }

      function roleFor(el) {
        const tag = el.tagName.toLowerCase();
        const type = (el.getAttribute('type') || '').toLowerCase();
        const role = (el.getAttribute('role') || '').toLowerCase();
        if (role) return role;
        if (tag === 'a') return 'link';
        if (tag === 'button') return 'button';
        if (tag === 'select') return 'select';
        if (tag === 'textarea') return 'textbox';
        if (tag === 'input') {
          if (['submit', 'button'].includes(type)) return 'button';
          if (type === 'checkbox') return 'checkbox';
          if (type === 'radio') return 'radio';
          if (type === 'file') return 'file';
          return 'textbox';
        }
        return role || tag;
      }

      function destinationFor(el) {
        const attrs = ['href','data-href','data-url','data-apply-url','data-target-url','data-ng-href','formaction'];
        for (const attr of attrs) {
          const raw = el.getAttribute && el.getAttribute(attr);
          if (raw && raw !== '#') {
            try { return new URL(raw, window.location.href).href; } catch { return raw; }
          }
        }
        const onclick = el.getAttribute && (el.getAttribute('onclick') || '');
        if (onclick) {
          const match = onclick.match(/https?:\/\/[^'"\)\s]+|\/career\?[^'"\)\s]+|\/talentcommunity\/[^'"\)\s]+|\/career\/[^'"\)\s]+/i);
          if (match) {
            try { return new URL(match[0], window.location.href).href; } catch { return match[0]; }
          }
        }
        return '';
      }

      const selector = 'a[href], button, input, textarea, select, [role="button"], [role="link"], [role="menuitem"], [role="option"]';
      const nodes = Array.from(document.querySelectorAll(selector)).filter(visible);
      const controls = [];
      let counter = 0;
      for (const el of nodes) {
        if (counter >= maxControls) break;
        let ref = el.getAttribute('data-ai-agent-id');
        if (!ref) {
          ref = 'ai-' + Math.random().toString(36).slice(2, 10) + '-' + counter;
          el.setAttribute('data-ai-agent-id', ref);
        }
        counter += 1;
        const tag = el.tagName.toLowerCase();
        const type = (el.getAttribute('type') || '').toLowerCase();
        const rect = el.getBoundingClientRect();
        let options = [];
        if (tag === 'select') {
          options = Array.from(el.options || []).map(o => ({ text: norm(o.textContent || ''), value: o.value, selected: !!o.selected })).slice(0, 80);
        }
        controls.push({
          ref,
          role: roleFor(el),
          tag,
          type,
          text: norm(el.innerText || el.textContent || el.value || el.getAttribute('aria-label') || '').slice(0, 300),
          label: labelFor(el),
          name: el.getAttribute('name') || '',
          id: el.getAttribute('id') || '',
          href: destinationFor(el),
          value: (type === 'password') ? '[password]' : (el.value || ''),
          checked: !!el.checked,
          disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true',
          options,
          rect: { x: Math.round(rect.x), y: Math.round(rect.y), width: Math.round(rect.width), height: Math.round(rect.height) }
        });
      }

      return {
        url: window.location.href,
        host: window.location.host,
        path: window.location.pathname,
        title: document.title,
        body_text: norm(document.body ? document.body.innerText : '').slice(0, maxBodyChars),
        controls,
      };
    }
    """
    try:
        snapshot = page.evaluate(js, {"maxBodyChars": max_body_chars, "maxControls": max_controls})
        if not isinstance(snapshot, dict):
            snapshot = {}
    except Exception as exc:
        snapshot = {
            "url": getattr(page, "url", ""),
            "title": "",
            "body_text": "",
            "controls": [],
            "snapshot_error": repr(exc),
        }

    snapshot.setdefault("url", getattr(page, "url", ""))
    snapshot.setdefault("title", "")
    snapshot.setdefault("body_text", "")
    snapshot.setdefault("controls", [])
    snapshot["state"] = classify_page(snapshot)
    try:
        parsed = urlparse(str(snapshot.get("url") or ""))
        snapshot["host"] = parsed.netloc.lower()
    except Exception:
        snapshot["host"] = ""
    return snapshot


def compact_snapshot_for_prompt(snapshot: dict[str, Any]) -> dict[str, Any]:
    controls = []
    for control in snapshot.get("controls") or []:
        if not isinstance(control, dict):
            continue
        controls.append({
            "ref": control.get("ref"),
            "role": control.get("role"),
            "text": control.get("text"),
            "label": control.get("label"),
            "href": control.get("href"),
            "type": control.get("type"),
            "value": control.get("value"),
            "checked": control.get("checked"),
            "disabled": control.get("disabled"),
            "options": control.get("options", [])[:30],
        })
    return {
        "url": snapshot.get("url"),
        "title": snapshot.get("title"),
        "state": snapshot.get("state"),
        "body_text_excerpt": str(snapshot.get("body_text") or "")[:9000],
        "controls": controls[:120],
    }
