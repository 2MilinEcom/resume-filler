from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from typing import Any

try:
    from src.profile import PROFILE
except Exception:
    PROFILE = {}

try:
    from src.safety_policy import is_final_submit_text, is_standard_terms_text, documents_summary, POLICY
    from src.site_account_store import get_or_create_account, ACCOUNT_STORE_PATH, load_store, account_key
except Exception:
    PROFILE = {}


@dataclass
class ActionResult:
    ok: bool
    message: str
    changed_url: bool = False




def _blocked_marketing_destination(url: str) -> bool:
    try:
        host = urlparse(str(url or "")).netloc.lower()
    except Exception:
        return False
    return host in {"successfactors.com", "www.successfactors.com", "sap.com", "www.sap.com"}


def _blocked_marketing_click(page, text: str) -> bool:
    label = re.sub(r"\s+", " ", str(text or "").strip().lower())
    if label not in {"successfactors", "sap", "sap successfactors"}:
        return False
    try:
        host = urlparse(str(getattr(page, "url", "") or "")).netloc.lower()
    except Exception:
        host = ""
    return "successfactors" in host or "sap.com" in host
def _get_by_ref(page, ref: str):
    return page.locator(f'[data-ai-agent-id="{ref}"]').first


def _wait_after_action(page, before_pages=None) -> None:
    before_pages = before_pages or set()
    try:
        page.wait_for_timeout(900)
    except Exception:
        pass

    # Fold popups/new tabs back into the current page.
    try:
        new_pages = list(set(page.context.pages) - before_pages)
        if new_pages:
            popup = new_pages[-1]
            try:
                popup.wait_for_load_state("domcontentloaded", timeout=12_000)
            except Exception:
                pass
            target_url = ""
            try:
                target_url = popup.url
            except Exception:
                pass
            if target_url and target_url != "about:blank":
                try:
                    page.goto(target_url, wait_until="domcontentloaded", timeout=45_000)
                except Exception:
                    pass
            try:
                popup.close()
            except Exception:
                pass
    except Exception:
        pass

    try:
        page.wait_for_load_state("domcontentloaded", timeout=8_000)
    except Exception:
        pass
    try:
        page.wait_for_load_state("networkidle", timeout=5_000)
    except Exception:
        pass
    try:
        page.wait_for_timeout(700)
    except Exception:
        pass




def _looks_like_apply_action(text: str) -> bool:
    return bool(re.search(r"\b(apply|apply now|start application|continue application|new candidate|create profile)\b", str(text or ""), re.I))


def _click_revealed_apply_menu_item(page, *, parent_box: dict[str, Any] | None = None) -> ActionResult | None:
    """After a split Apply button is clicked, click the revealed menu item.

    This is generic browser behavior, not a Cargill-specific patch: many ATS skins
    expose a parent button and then reveal menuitems/links. The agent should still
    decide to click Apply; this helper makes that primitive action complete.
    """
    js = r"""
    ({ parentBox }) => {
      function norm(s) { return (s || '').replace(/\s+/g, ' ').trim(); }
      function visible(el) {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
      }
      function absUrl(raw) {
        if (!raw) return '';
        try { return new URL(raw, window.location.href).href; } catch { return String(raw || ''); }
      }
      function dest(el) {
        for (const attr of ['href','data-href','data-url','data-apply-url','data-target-url','data-ng-href','formaction']) {
          const raw = el.getAttribute && el.getAttribute(attr);
          if (raw && raw !== '#') return absUrl(raw);
        }
        const onclick = el.getAttribute && (el.getAttribute('onclick') || '');
        if (onclick) {
          const m = onclick.match(/https?:\/\/[^'"\)\s]+|\/career\?[^'"\)\s]+|\/talentcommunity\/[^'"\)\s]+|\/career\/[^'"\)\s]+/i);
          if (m) return absUrl(m[0]);
        }
        return '';
      }
      function bad(text, href) {
        return /create alert|job alert|search jobs|view profile|language|privacy|terms|home|facebook|linkedin company|twitter|youtube/i.test((text || '') + ' ' + (href || ''));
      }
      const parent = parentBox || null;
      const nodes = Array.from(document.querySelectorAll('a[href], button, [role="menuitem"], [role="option"], input[type="submit"], input[type="button"]'))
        .filter(visible)
        .filter(el => !el.disabled && el.getAttribute('aria-disabled') !== 'true');
      const candidates = [];
      for (let i = 0; i < nodes.length; i++) {
        const el = nodes[i];
        const text = norm(el.innerText || el.textContent || el.value || el.getAttribute('aria-label') || '');
        const href = dest(el);
        const hay = (text + ' ' + href).toLowerCase();
        if (bad(text, href)) continue;
        if (!/apply|start application|continue application|new candidate|create profile|successfactors|career\?company|talentcommunity/.test(hay)) continue;
        const rect = el.getBoundingClientRect();
        let score = 0;
        if (parent) {
          const below = rect.top >= parent.y - 10;
          const close = rect.top <= parent.y + parent.height + 340;
          const overlap = !(rect.right < parent.x - 120 || rect.left > parent.x + parent.width + 120);
          const sameBox = Math.abs(rect.top - parent.y) < 8 && Math.abs(rect.left - parent.x) < 8;
          if (below && close && overlap && !sameBox) score += 220;
        }
        if (/successfactors|career\?company|career2\./.test(hay)) score += 500;
        if (/talentcommunity|apply/.test(hay)) score += 180;
        if (/^apply now\s*»?$/i.test(text)) score += 120;
        if (/apply manually|new candidate|create profile/i.test(text)) score += 160;
        if (/linkedin/i.test(text)) score -= 120;
        if (score > 0) candidates.push({ index: i, text, href, score, top: rect.top });
      }
      candidates.sort((a,b) => b.score - a.score || a.top - b.top);
      return candidates.slice(0, 8);
    }
    """
    click_js = r"""
    ({ index }) => {
      function visible(el) {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
      }
      const nodes = Array.from(document.querySelectorAll('a[href], button, [role="menuitem"], [role="option"], input[type="submit"], input[type="button"]'))
        .filter(visible)
        .filter(el => !el.disabled && el.getAttribute('aria-disabled') !== 'true');
      const el = nodes[index];
      if (!el) return false;
      el.scrollIntoView({ block: 'center' });
      el.click();
      return true;
    }
    """
    try:
        candidates = page.evaluate(js, {"parentBox": parent_box or None}) or []
        if not candidates:
            return None
        chosen = candidates[0]
        label = chosen.get("text") or chosen.get("href") or "revealed apply menu item"
        before_url = getattr(page, "url", "")
        before_pages = set(page.context.pages)
        ok = bool(page.evaluate(click_js, {"index": int(chosen.get("index", -1))}))
        if not ok:
            return None
        _wait_after_action(page, before_pages)
        return ActionResult(True, f"Clicked revealed apply menu item: {label}", changed_url=(getattr(page, "url", "") != before_url))
    except Exception:
        return None

def click_ref(page, ref: str, *, text: str = "", allow_final_submit: bool = False) -> ActionResult:
    if not ref:
        return ActionResult(False, "click_ref missing ref")
    if _blocked_marketing_click(page, text):
        return ActionResult(False, "Blocked SAP/SuccessFactors marketing link; relaunch the employer job page instead.")
    if is_final_submit_text(text) and not allow_final_submit:
        return ActionResult(False, "Blocked final external submit; stopping for final review.")

    before_url = getattr(page, "url", "")
    try:
        before_pages = set(page.context.pages)
    except Exception:
        before_pages = set()

    try:
        loc = _get_by_ref(page, ref)
        loc.scroll_into_view_if_needed(timeout=5_000)
        try:
            parent_box = loc.bounding_box(timeout=2_000)
        except Exception:
            parent_box = None
        loc.click(timeout=8_000)
        page.wait_for_timeout(650)
        if getattr(page, "url", "") == before_url and _looks_like_apply_action(text):
            menu_result = _click_revealed_apply_menu_item(page, parent_box=parent_box)
            if menu_result is not None and menu_result.ok:
                return menu_result
        _wait_after_action(page, before_pages)
        return ActionResult(True, f"Clicked {text or ref}", changed_url=(getattr(page, "url", "") != before_url))
    except Exception as exc:
        return ActionResult(False, f"Could not click {text or ref}: {exc}")


def click_text(page, text: str, *, allow_final_submit: bool = False) -> ActionResult:
    if not text:
        return ActionResult(False, "click_text missing text")
    if _blocked_marketing_click(page, text):
        return ActionResult(False, "Blocked SAP/SuccessFactors marketing link; relaunch the employer job page instead.")
    if is_final_submit_text(text) and not allow_final_submit:
        return ActionResult(False, "Blocked final external submit; stopping for final review.")

    before_url = getattr(page, "url", "")
    try:
        before_pages = set(page.context.pages)
    except Exception:
        before_pages = set()

    patterns = [re.compile(rf"^{re.escape(text)}$", re.I), re.compile(re.escape(text), re.I)]
    for pattern in patterns:
        for role in ["button", "link", "menuitem", "option"]:
            try:
                loc = page.get_by_role(role, name=pattern).first
                if loc.count() and loc.is_visible() and loc.is_enabled():
                    loc.scroll_into_view_if_needed(timeout=3_000)
                    try:
                        parent_box = loc.bounding_box(timeout=2_000)
                    except Exception:
                        parent_box = None
                    loc.click(timeout=8_000)
                    page.wait_for_timeout(650)
                    if getattr(page, "url", "") == before_url and _looks_like_apply_action(text):
                        menu_result = _click_revealed_apply_menu_item(page, parent_box=parent_box)
                        if menu_result is not None and menu_result.ok:
                            return menu_result
                    _wait_after_action(page, before_pages)
                    return ActionResult(True, f"Clicked text {text}", changed_url=(getattr(page, "url", "") != before_url))
            except Exception:
                pass
        try:
            loc = page.get_by_text(pattern).first
            if loc.count() and loc.is_visible():
                loc.scroll_into_view_if_needed(timeout=3_000)
                loc.click(timeout=8_000)
                _wait_after_action(page, before_pages)
                return ActionResult(True, f"Clicked text {text}", changed_url=(getattr(page, "url", "") != before_url))
        except Exception:
            pass
    return ActionResult(False, f"Could not find clickable text: {text}")


def fill_ref(page, ref: str, value: str) -> ActionResult:
    if not ref:
        return ActionResult(False, "fill_ref missing ref")
    try:
        loc = _get_by_ref(page, ref)
        loc.scroll_into_view_if_needed(timeout=5_000)
        loc.fill(str(value), timeout=8_000)
        return ActionResult(True, f"Filled {ref}")
    except Exception as exc:
        return ActionResult(False, f"Could not fill {ref}: {exc}")


def fill_label(page, label: str, value: str) -> ActionResult:
    if not label:
        return ActionResult(False, "fill_label missing label")
    try:
        loc = page.get_by_label(re.compile(re.escape(label), re.I)).first
        if loc.count() and loc.is_visible() and loc.is_enabled():
            loc.fill(str(value), timeout=8_000)
            return ActionResult(True, f"Filled {label}")
    except Exception:
        pass

    # Fallback to DOM label/placeholder/name text search.
    js = r"""
    ({ label, value }) => {
      function norm(s) { return (s || '').replace(/\s+/g, ' ').trim().toLowerCase(); }
      function visible(el) {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
      }
      const wanted = norm(label);
      const fields = Array.from(document.querySelectorAll('input, textarea')).filter(visible);
      let best = null;
      let bestScore = 0;
      for (const field of fields) {
        let text = norm([field.getAttribute('aria-label'), field.getAttribute('placeholder'), field.getAttribute('name'), field.id].join(' '));
        if (field.id) {
          const lab = document.querySelector(`label[for="${CSS.escape(field.id)}"]`);
          if (lab) text += ' ' + norm(lab.innerText || lab.textContent || '');
        }
        let parent = field.parentElement;
        for (let depth = 0; parent && depth < 3; depth++, parent = parent.parentElement) {
          const p = norm(parent.innerText || parent.textContent || '');
          if (p.length < 350) text += ' ' + p;
        }
        let score = 0;
        if (text.includes(wanted)) score += 100;
        for (const token of wanted.split(/\s+/)) if (token && text.includes(token)) score += 8;
        if (score > bestScore) { bestScore = score; best = field; }
      }
      if (!best || bestScore < 30) return false;
      best.scrollIntoView({ block: 'center' });
      best.focus();
      best.value = value;
      best.dispatchEvent(new Event('input', { bubbles: true }));
      best.dispatchEvent(new Event('change', { bubbles: true }));
      return true;
    }
    """
    try:
        if page.evaluate(js, {"label": label, "value": str(value)}):
            return ActionResult(True, f"Filled {label}")
    except Exception as exc:
        return ActionResult(False, f"Could not fill {label}: {exc}")
    return ActionResult(False, f"Could not find field label: {label}")


def select_ref(page, ref: str, option: str) -> ActionResult:
    if not ref:
        return ActionResult(False, "select_ref missing ref")
    try:
        loc = _get_by_ref(page, ref)
        loc.scroll_into_view_if_needed(timeout=5_000)
        try:
            loc.select_option(label=str(option), timeout=5_000)
            return ActionResult(True, f"Selected {option}")
        except Exception:
            pass
        try:
            loc.select_option(value=str(option), timeout=5_000)
            return ActionResult(True, f"Selected {option}")
        except Exception:
            pass
        # Combobox custom UI fallback.
        loc.click(timeout=5_000)
        page.wait_for_timeout(300)
        return click_text(page, str(option), allow_final_submit=True)
    except Exception as exc:
        return ActionResult(False, f"Could not select {option}: {exc}")


def check_ref(page, ref: str, *, label: str = "") -> ActionResult:
    if not ref:
        return ActionResult(False, "check_ref missing ref")
    if label and (not POLICY.get("can_accept_standard_account_terms", False)) and is_standard_terms_text(label):
        return ActionResult(False, "Terms/privacy checkbox needs manual confirmation.")
    try:
        loc = _get_by_ref(page, ref)
        loc.scroll_into_view_if_needed(timeout=5_000)
        try:
            loc.check(timeout=5_000)
        except Exception:
            loc.click(timeout=5_000)
        return ActionResult(True, f"Checked {label or ref}")
    except Exception as exc:
        return ActionResult(False, f"Could not check {label or ref}: {exc}")


def upload_file_by_ref(page, ref: str, document_key: str) -> ActionResult:
    docs = documents_summary()
    document_key = (document_key or "").strip().lower()
    path = docs.get(document_key)
    if not path:
        return ActionResult(False, f"Missing required document: {document_key}")

    file_path = Path(path).expanduser()
    if not file_path.exists():
        return ActionResult(False, f"Configured document does not exist: {file_path}")

    try:
        loc = _get_by_ref(page, ref)
        loc.set_input_files(str(file_path), timeout=10_000)
        return ActionResult(True, f"Uploaded {document_key}: {file_path.name}")
    except Exception as exc:
        return ActionResult(False, f"Could not upload {document_key}: {exc}")


def open_url(page, url: str) -> ActionResult:
    if not url or not str(url).lower().startswith(("http://", "https://")):
        return ActionResult(False, f"Refusing invalid URL: {url}")
    if _blocked_marketing_destination(str(url)):
        return ActionResult(False, f"Blocked SAP/SuccessFactors marketing URL outside the application flow: {url}")
    before_url = getattr(page, "url", "")
    try:
        page.goto(str(url), wait_until="domcontentloaded", timeout=45_000)
        try:
            page.wait_for_load_state("networkidle", timeout=12_000)
        except Exception:
            pass
        page.wait_for_timeout(900)
        return ActionResult(True, f"Opened URL: {url}", changed_url=(getattr(page, "url", "") != before_url))
    except Exception as exc:
        return ActionResult(False, f"Could not open URL {url}: {exc}")


def go_back(page) -> ActionResult:
    before_url = getattr(page, "url", "")
    try:
        page.go_back(wait_until="domcontentloaded", timeout=20_000)
        page.wait_for_timeout(700)
        return ActionResult(True, "Went back", changed_url=(getattr(page, "url", "") != before_url))
    except Exception as exc:
        return ActionResult(False, f"Could not go back: {exc}")


def wait(page, seconds: float = 1.0) -> ActionResult:
    try:
        seconds = max(0.25, min(float(seconds), 8.0))
    except Exception:
        seconds = 1.0
    try:
        page.wait_for_timeout(int(seconds * 1000))
        return ActionResult(True, f"Waited {seconds:.1f}s")
    except Exception as exc:
        # ATS pages can close/replace the target after sign-in. Treat this as a
        # recoverable action failure so the main agent loop can switch to a live page
        # instead of crashing the entire process.
        return ActionResult(False, f"Wait failed because the page/context closed: {exc}")


def _fill_many_account_fields(page, fields: list[tuple[list[str], str]]) -> int:
    filled = 0
    for labels, value in fields:
        if not value:
            continue
        for label in labels:
            result = fill_label(page, label, value)
            if result.ok:
                filled += 1
                break
    return filled


def _select_country_us(page) -> bool:
    for ref_like in []:
        pass
    choices = ["United States", "United States of America", "USA", "US"]
    try:
        selects = page.locator("select")
        for i in range(selects.count()):
            sel = selects.nth(i)
            try:
                if not sel.is_visible() or not sel.is_enabled():
                    continue
                for choice in choices:
                    try:
                        sel.select_option(label=choice, timeout=1_500)
                        return True
                    except Exception:
                        pass
                    try:
                        sel.select_option(value=choice, timeout=1_500)
                        return True
                    except Exception:
                        pass
            except Exception:
                continue
    except Exception:
        pass
    return False


def _check_standard_terms(page) -> int:
    if not POLICY.get("can_accept_standard_account_terms", False):
        return 0
    js = r"""
    () => {
      function norm(s) { return (s || '').replace(/\s+/g, ' ').trim().toLowerCase(); }
      function visible(el) {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
      }
      let count = 0;
      const boxes = Array.from(document.querySelectorAll('input[type="checkbox"]')).filter(visible);
      for (const box of boxes) {
        if (box.checked) continue;
        let text = '';
        if (box.id) {
          const lab = document.querySelector(`label[for="${CSS.escape(box.id)}"]`);
          if (lab) text += ' ' + norm(lab.innerText || lab.textContent || '');
        }
        let parent = box.parentElement;
        for (let depth = 0; parent && depth < 5; depth++, parent = parent.parentElement) {
          text += ' ' + norm(parent.innerText || parent.textContent || '');
        }
        if (/terms of use|data privacy|privacy statement|privacy policy|read and accept|i accept|i agree/.test(text)) {
          box.scrollIntoView({ block: 'center' });
          box.click();
          count += 1;
        }
      }
      return count;
    }
    """
    try:
        return int(page.evaluate(js) or 0)
    except Exception:
        return 0


def _visible_text(page) -> str:
    try:
        return page.locator("body").inner_text(timeout=3_000)
    except Exception:
        return ""


def _account_surface(page) -> dict[str, Any]:
    """Return a tiny diagnostic summary of the visible account page."""
    js = r"""
    () => {
      function norm(s) { return (s || '').replace(/\s+/g, ' ').trim(); }
      function visible(el) {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
      }
      const fields = Array.from(document.querySelectorAll('input, textarea, select')).filter(visible).map(el => ({
        tag: el.tagName.toLowerCase(),
        type: (el.getAttribute('type') || '').toLowerCase(),
        name: el.getAttribute('name') || '',
        id: el.getAttribute('id') || '',
        label: norm(el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.getAttribute('title') || '')
      }));
      const buttons = Array.from(document.querySelectorAll('button, input[type="submit"], input[type="button"], a, [role="button"]')).filter(visible).map(el => norm(el.innerText || el.textContent || el.value || el.getAttribute('aria-label') || '')).filter(Boolean);
      return { field_count: fields.length, fields: fields.slice(0, 20), buttons: buttons.slice(0, 30), body_excerpt: norm(document.body ? document.body.innerText : '').slice(0, 1200) };
    }
    """
    try:
        value = page.evaluate(js)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _click_visible_button_like(page, patterns: list[str]) -> bool:
    """More tolerant click for SuccessFactors/SAP buttons that are not exposed as roles."""
    js = r"""
    ({ patterns }) => {
      function norm(s) { return (s || '').replace(/\s+/g, ' ').trim(); }
      function visible(el) {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
      }
      const regexes = patterns.map(p => new RegExp(p, 'i'));
      const nodes = Array.from(document.querySelectorAll('button, input[type="submit"], input[type="button"], a, [role="button"], span, div'))
        .filter(visible)
        .filter(el => !el.disabled && el.getAttribute('aria-disabled') !== 'true');
      const candidates = [];
      for (const el of nodes) {
        const text = norm(el.innerText || el.textContent || el.value || el.getAttribute('aria-label') || el.getAttribute('title') || '');
        if (!text) continue;
        let score = 0;
        for (let i = 0; i < regexes.length; i++) {
          if (regexes[i].test(text)) score += 100 - i;
        }
        if (!score) continue;
        const tag = el.tagName.toLowerCase();
        const role = (el.getAttribute('role') || '').toLowerCase();
        if (tag === 'button' || tag === 'input' || role === 'button') score += 50;
        if (/cancel|back|previous|search|alert|privacy|terms/i.test(text)) score -= 150;
        const rect = el.getBoundingClientRect();
        candidates.push({ el, score, text, top: rect.top });
      }
      candidates.sort((a,b) => b.score - a.score || a.top - b.top);
      if (!candidates.length) return { ok: false };
      const chosen = candidates[0];
      chosen.el.scrollIntoView({ block: 'center' });
      chosen.el.click();
      return { ok: true, text: chosen.text };
    }
    """
    try:
        result = page.evaluate(js, {"patterns": patterns})
        if isinstance(result, dict) and result.get("ok"):
            try:
                page.wait_for_timeout(1200)
            except Exception:
                pass
            _wait_after_action(page)
            return True
    except Exception:
        pass
    return False


def _click_create_or_continue(page) -> bool:
    # Try Playwright role/text first, then a DOM fallback for SAP/SuccessFactors skins.
    patterns = [
        "create account",
        "create an account",
        "register",
        "continue",
        "next",
        "submit",
        "save and continue",
        "save",
        "sign in",
        "log in",
        "login",
    ]
    for text in patterns:
        result = click_text(page, text, allow_final_submit=True)
        if result.ok:
            return True
    return _click_visible_button_like(page, [
        r"^\s*create(\s+an)?\s+account\s*$",
        r"^\s*register\s*$",
        r"^\s*continue\s*$",
        r"^\s*next\s*$",
        r"^\s*save\s+and\s+continue\s*$",
        r"^\s*save\s*$",
        r"^\s*sign\s*in\s*$",
        r"^\s*log\s*in\s*$",
        r"^\s*login\s*$",
    ])


def _try_sign_in_with_saved_credentials(page, *, email: str, password: str) -> bool:
    body = _visible_text(page).lower()
    if not email or not password:
        return False
    if "password" not in body or not any(term in body for term in ["sign in", "login", "log in", "already have an account", "returning candidate"]):
        return False
    # Do not sign in on an explicit create-account form that is asking for retyped email/password.
    if any(term in body for term in ["retype email", "choose password", "retype password", "confirm password"]):
        return False
    filled = 0
    if fill_label(page, "email", email).ok or fill_label(page, "email address", email).ok:
        filled += 1
    if fill_label(page, "password", password).ok:
        filled += 1
    if filled >= 2:
        return _click_visible_button_like(page, [r"^\s*sign\s*in\s*$", r"^\s*log\s*in\s*$", r"^\s*login\s*$", r"^\s*continue\s*$"])
    return False


def create_site_account(page, *, company: str = "", job_title: str = "") -> ActionResult:
    if not POLICY.get("can_create_external_accounts", False):
        return ActionResult(False, "External account creation disabled.")

    current_url = getattr(page, "url", "")
    try:
        key = account_key(current_url, company)
        existing_before = key in load_store()
    except Exception:
        existing_before = False

    record = get_or_create_account(current_url, company=company, job_title=job_title)
    email = str(record.get("email") or "")
    password = str(record.get("password") or "")

    if not email or not password:
        return ActionResult(False, "Could not create credentials because email/password is missing.")

    first = str(PROFILE.get("first_name") or PROFILE.get("preferred_first_name") or "Sample")
    last = str(PROFILE.get("last_name") or "Applicant")

    before_url = getattr(page, "url", "")
    before_surface = _account_surface(page)
    before_body = str(before_surface.get("body_excerpt") or _visible_text(page)).lower()

    # If a prior run already generated credentials and the page is a returning-candidate
    # sign-in screen, try logging in before attempting to create a duplicate account.
    if existing_before and _try_sign_in_with_saved_credentials(page, email=email, password=password):
        after_url = getattr(page, "url", "")
        return ActionResult(True, f"Submitted saved external-site credentials; credentials stored at {ACCOUNT_STORE_PATH}", changed_url=(after_url != before_url))

    # SuccessFactors often lands on a sign-in shell first. Move to the actual
    # create-account form before filling generated credentials.
    if "create an account" in before_body and not any(t in before_body for t in ["retype email", "choose password", "retype password", "confirm password"]):
        click_text(page, "Create an account", allow_final_submit=True)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=10_000)
        except Exception:
            pass
        page.wait_for_timeout(1200)

    filled = _fill_many_account_fields(page, [
        (["email address", "email"], email),
        (["retype email address", "confirm email", "verify email"], email),
        (["choose password", "new password", "password"], password),
        (["retype password", "confirm password"], password),
        (["first name", "given name"], first),
        (["last name", "family name", "surname"], last),
    ])
    if _select_country_us(page):
        filled += 1
    checked = _check_standard_terms(page)

    clicked = False
    if filled or checked:
        clicked = _click_create_or_continue(page)
    else:
        # No visible editable account form. Try a single sign-in if possible, but
        # do not loop create_site_account forever on a stale SuccessFactors shell.
        if existing_before and _try_sign_in_with_saved_credentials(page, email=email, password=password):
            after_url = getattr(page, "url", "")
            return ActionResult(True, f"Submitted saved external-site credentials; credentials stored at {ACCOUNT_STORE_PATH}", changed_url=(after_url != before_url))

    try:
        page.wait_for_timeout(2500)
    except Exception:
        pass
    _wait_after_action(page)

    after_url = getattr(page, "url", "")
    after_surface = _account_surface(page)
    msg = f"Created/filled external account fields={filled}, terms_checked={checked}; credentials saved to {ACCOUNT_STORE_PATH}"

    if clicked:
        return ActionResult(True, msg, changed_url=(after_url != before_url))

    if filled == 0 and checked == 0:
        visible_buttons = ", ".join(str(x) for x in (after_surface.get("buttons") or [])[:8])
        visible_fields = int(after_surface.get("field_count") or 0)
        detail = f"No visible account fields/terms/create/continue controls remain after the account step. fields={visible_fields}; buttons=[{visible_buttons}]"
        return ActionResult(False, msg + "; " + detail)

    return ActionResult(True, msg + "; create/continue button not detected", changed_url=(after_url != before_url))


def execute_agent_action(page, action: dict[str, Any], *, company: str = "", job_title: str = "", allow_final_submit: bool = False) -> ActionResult:
    kind = str(action.get("action") or "").strip().lower()
    ref = str(action.get("target_ref") or action.get("ref") or "").strip()
    text = str(action.get("target_text") or action.get("text") or action.get("label") or "").strip()
    value = str(action.get("value") or "")
    option = str(action.get("option") or action.get("value") or "")

    if kind == "click":
        if ref:
            return click_ref(page, ref, text=text, allow_final_submit=allow_final_submit)
        return click_text(page, text, allow_final_submit=allow_final_submit)
    if kind == "fill":
        if ref:
            return fill_ref(page, ref, value)
        return fill_label(page, text, value)
    if kind == "select":
        if ref:
            return select_ref(page, ref, option)
        return ActionResult(False, "select requires target_ref in this version")
    if kind == "check":
        return check_ref(page, ref, label=text)
    if kind == "upload_file":
        return upload_file_by_ref(page, ref, str(action.get("document_key") or action.get("value") or ""))
    if kind == "open_url":
        return open_url(page, str(action.get("url") or value or ""))
    if kind == "go_back":
        return go_back(page)
    if kind == "wait":
        return wait(page, action.get("seconds") or 1)
    if kind == "create_site_account":
        return create_site_account(page, company=company, job_title=job_title)
    return ActionResult(False, f"Unknown action: {kind}")
