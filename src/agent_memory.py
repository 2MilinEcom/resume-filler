from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
EVENT_LOG_PATH = DATA_DIR / "application_events.jsonl"
FAILURE_MEMORY_PATH = DATA_DIR / "failure_memory.json"


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def normalize_host(url: str | None) -> str:
    try:
        return urlparse(str(url or "")).netloc.lower().replace("www.", "")
    except Exception:
        return ""


def load_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def save_json(path: Path, value: Any) -> None:
    ensure_data_dir()
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")


def append_event(event: dict[str, Any]) -> None:
    ensure_data_dir()
    payload = dict(event)
    payload.setdefault("created_at", now_iso())
    with EVENT_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        handle.write("\n")


def load_failure_memory() -> dict[str, Any]:
    value = load_json(FAILURE_MEMORY_PATH, {})
    return value if isinstance(value, dict) else {}


def get_failure_memory_for_url(url: str | None) -> dict[str, Any]:
    memory = load_failure_memory()
    host = normalize_host(url)
    if not host:
        return {}

    exact = memory.get(host)
    if isinstance(exact, dict):
        return exact

    # Allow parent-domain matches, e.g. jobs.cargill.com -> cargill.com.
    parts = host.split(".")
    for i in range(1, max(1, len(parts) - 1)):
        domain = ".".join(parts[i:])
        item = memory.get(domain)
        if isinstance(item, dict):
            return item
    return {}


def record_failure_memory(url: str | None, lesson: str, *, pattern: str = "", action_sequence: list[str] | None = None) -> None:
    host = normalize_host(url)
    if not host or not lesson:
        return

    memory = load_failure_memory()
    current = memory.get(host)
    if not isinstance(current, dict):
        current = {}

    current.update({
        "pattern": pattern or current.get("pattern", "agent learned from run"),
        "lesson": lesson,
        "last_updated": now_iso(),
    })
    if action_sequence:
        current["last_successful_action_sequence"] = action_sequence

    memory[host] = current
    save_json(FAILURE_MEMORY_PATH, memory)


def load_answer_bank_hints(limit: int = 80) -> list[dict[str, Any]]:
    """Read the local answer bank without forcing reuse.

    The agent uses these as supporting facts/hints, not blind commands. This lets it
    use facts such as GPA that the user already answered, while avoiding generic
    stale saved dropdown answers as authoritative truth.
    """
    path = DATA_DIR / "answer_bank.jsonl"
    if not path.exists():
        return []

    entries: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except Exception:
                continue
            if not isinstance(item, dict):
                continue
            question = str(item.get("question") or "").strip()
            answer = str(item.get("answer") or "").strip()
            category = str(item.get("category") or "").strip()
            if not answer:
                continue
            # Avoid flooding prompt with meaningless generic dropdown rows.
            if question.lower() in {"required dropdown question", "required radio question", "required screening question"}:
                if category not in {"gpa", "email", "phone", "linkedin", "name", "school", "graduation"}:
                    continue
            entries.append({
                "category": category,
                "question": question,
                "answer": answer,
                "company": item.get("company", ""),
                "job_title": item.get("job_title", ""),
                "source": item.get("source", "answer_bank"),
            })
    except Exception:
        return []

    return entries[-limit:]
