from __future__ import annotations

import json
import secrets
import string
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    from src.profile import PROFILE
except Exception:
    PROFILE = {}

try:
    from src.agent_memory import DATA_DIR
except Exception:
    DATA_DIR = Path(__file__).resolve().parent.parent / "data"


ACCOUNT_STORE_PATH = DATA_DIR / "site_accounts.json"


def _normalize_key(value: str | None) -> str:
    import re
    value = str(value or "").lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "unknown"


def _host(url: str | None) -> str:
    try:
        return urlparse(str(url or "")).netloc.lower().replace("www.", "") or "external-site"
    except Exception:
        return "external-site"


def account_key(url: str | None, company: str = "") -> str:
    host = _host(url)
    company_key = _normalize_key(company or host)
    if "successfactors" in host or "cargill" in host:
        return f"successfactors:{company_key}"
    return f"{host}:{company_key}"


def load_store() -> dict[str, Any]:
    try:
        if ACCOUNT_STORE_PATH.exists():
            value = json.loads(ACCOUNT_STORE_PATH.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                return value
    except Exception:
        pass
    return {}


def save_store(store: dict[str, Any]) -> None:
    ACCOUNT_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    ACCOUNT_STORE_PATH.write_text(json.dumps(store, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    try:
        ACCOUNT_STORE_PATH.chmod(0o600)
    except Exception:
        pass


def generate_password(length: int = 18) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%_-+?"
    while True:
        password = "".join(secrets.choice(alphabet) for _ in range(length))
        if (
            any(ch.islower() for ch in password)
            and any(ch.isupper() for ch in password)
            and any(ch.isdigit() for ch in password)
            and any(ch in "!@#$%_-+?" for ch in password)
        ):
            return password


def profile_value(key: str, default: str = "") -> str:
    value = PROFILE.get(key, default)
    if value is None:
        return default
    return str(value).strip()


def get_or_create_account(url: str | None, *, company: str = "", job_title: str = "") -> dict[str, Any]:
    store = load_store()
    key = account_key(url, company)
    current = store.get(key)
    if isinstance(current, dict) and current.get("email") and current.get("password"):
        current["last_url"] = str(url or current.get("last_url") or "")
        save_store(store)
        return current

    record = {
        "site_key": key,
        "host": _host(url),
        "company": company,
        "job_title": job_title,
        "email": profile_value("email"),
        "password": generate_password(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_url": str(url or ""),
    }
    store[key] = record
    save_store(store)
    return record
