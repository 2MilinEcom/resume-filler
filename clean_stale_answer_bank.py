from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
p = ROOT / "data" / "answer_bank.jsonl"

if not p.exists():
    print("No data/answer_bank.jsonl found; nothing to clean.")
    raise SystemExit(0)

def norm(x: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(x or "").lower()).strip()

kept: list[str] = []
removed: list[tuple[str, str, str]] = []
original = p.read_text(encoding="utf-8")

for line in original.splitlines():
    if not line.strip():
        continue
    try:
        item = json.loads(line)
    except Exception:
        kept.append(line)
        continue

    q = norm(item.get("question") or item.get("normalized_question"))
    a = norm(item.get("answer") or item.get("normalized_answer"))
    cat = norm(item.get("category"))

    bad = False
    reason = ""

    # Critical profile facts confirmed by Sample on 2026-10-01.
    if ("sponsor" in q or "sponsorship" in q or cat == "sponsorship") and a in {"yes", "y"}:
        bad = True
        reason = "sponsorship must be No"
    elif ("authorized" in q or "eligible to work" in q or cat == "work authorization") and a in {"no", "n"}:
        bad = True
        reason = "work authorization must be Yes"
    elif ("citizen" in q or "citizenship" in q) and a and "citizen" not in a:
        bad = True
        reason = "citizenship must be U.S. citizen"
    elif ("graduat" in q or cat == "graduation") and a and "2027" not in a:
        bad = True
        reason = "graduation source-of-truth is June 2027"
    elif ("gpa" in q or cat == "gpa") and a and not any(x in a for x in ["3 67", "3 61", "3 7"]):
        bad = True
        reason = "GPA source-of-truth is 3.67 / 3.61-3.7"
    elif ("high school" in q or cat == "high school") and a and "2023" not in a:
        bad = True
        reason = "high school graduation year must be 2023"
    elif ("act" in q or "standardized" in q or cat == "standardized test") and "sat" not in q and a and a not in {"act", "29"} and "29" not in a:
        bad = True
        reason = "ACT source-of-truth is 29"
    elif "sat" in q and a and not any(x in a for x in ["dont have", "do not have", "no sat", "n a"]):
        bad = True
        reason = "SAT source-of-truth is no SAT score"
    elif "pronoun" in q and "he" not in a:
        bad = True
        reason = "pronouns source-of-truth is He/Him"
    elif ("current" in q and "offer" in q) and a in {"yes", "y"}:
        bad = True
        reason = "current offers source-of-truth is No"
    elif ("further education" in q or "graduate school" in q) and a in {"yes", "y"}:
        bad = True
        reason = "further education source-of-truth is No"
    elif ("applied" in q and ("12" in q or "18" in q or "2 year" in q)) and a in {"yes", "y"}:
        bad = True
        reason = "prior applications source-of-truth is No"
    elif ("gender" in q or cat == "gender") and "trans" not in q and a and "male" not in a and "man" not in a:
        bad = True
        reason = "gender source-of-truth is Male"
    elif ("hispanic" in q or "latino" in q or "race" in q or "ethnicity" in q) and a and not any(x in a for x in ["hispanic", "latino", "white"]):
        bad = True
        reason = "race/ethnicity source-of-truth is Hispanic/Latino, fallback White"
    elif ("veteran" in q or cat == "veteran") and a and not any(x in a for x in ["not", "no", "none"]):
        bad = True
        reason = "veteran source-of-truth is not a veteran"
    elif ("disability" in q or cat == "disability") and a and not any(x in a for x in ["no", "not", "dont", "do not"]):
        bad = True
        reason = "disability source-of-truth is No"

    if bad:
        removed.append((str(item.get("question", "")), str(item.get("answer", "")), reason))
    else:
        kept.append(json.dumps(item, ensure_ascii=False, sort_keys=True))

backup = p.with_suffix(".jsonl.bak")
backup.write_text(original, encoding="utf-8")
p.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")

print(f"Cleaned answer bank: removed {len(removed)} stale entries, kept {len(kept)}.")
print(f"Backup saved to: {backup}")
if removed:
    print("Removed examples:")
    for q, a, reason in removed[:30]:
        print(f"- {reason}: {q!r} -> {a!r}")
