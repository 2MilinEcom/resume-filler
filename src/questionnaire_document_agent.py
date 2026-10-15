from __future__ import annotations

import json
import os
import re
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

try:
    from src.profile import PROFILE
except Exception:
    try:
        from profile import PROFILE  # type: ignore
    except Exception:
        PROFILE = {}


ROOT = Path(__file__).resolve().parent.parent
GENERATED_DIR = ROOT / "documents" / "generated_questionnaires"


MARKETING_RESUME_FACTS = [
    "UC Berkeley B.S. Electrical Engineering and Computer Sciences candidate, GPA 3.67, expected graduation June 2027.",
    "Founded and scaled Blanc Studios LLC e-commerce businesses from an initial $800 investment to $2M+ in cumulative revenue and 30K+ orders.",
    "Scaled to about $100K in monthly revenue within three months by building repeatable acquisition and retention systems.",
    "Managed $800K+ in advertising spend across creative strategy, customer targeting, experimentation, budget allocation, and conversion optimization.",
    "Led content and growth strategy for Lirvana Labs, a $5.3M seed-funded technology startup, growing YouTube presence to about 100K monthly views.",
    "Executed a Lirvana Labs campaign generating $20K+ and supported audience expansion across Hong Kong, Mexico, China, and France.",
    "Built technical/product experience through BlackRock Aladdin, AWS, Facebook Summer Academy, and Apple software/product programs.",
]


SENSITIVE_OR_LEGAL_TERMS = [
    "signature",
    "certify",
    "certification",
    "attest",
    "attestation",
    "background check",
    "criminal",
    "disability",
    "veteran",
    "race",
    "ethnicity",
    "hispanic",
    "latino",
    "sexual orientation",
    "transgender",
    "salary",
    "compensation requirement",
    "desired compensation",
]


def _truthy(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def questionnaire_generation_enabled() -> bool:
    return _truthy(os.getenv("AI_GENERATE_OTHER_DOCUMENTS"), False) or _truthy(
        os.getenv("AI_FILL_QUESTIONNAIRES"), False
    )


def _clean(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _norm(text: Any) -> str:
    text = str(text or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _load_optional_text_file(path: Path, max_chars: int = 16000) -> str:
    try:
        if path.exists() and path.is_file():
            return path.read_text(errors="replace")[:max_chars]
    except Exception:
        pass
    return ""


def load_applicant_brief() -> str:
    candidates = [
        ROOT / "documents" / "applicant_brief.md",
        ROOT / "documents" / "ApplicantBrief.md",
        ROOT / "applicant_brief.md",
        ROOT / "data" / "applicant_brief.md",
    ]
    for candidate in candidates:
        text = _load_optional_text_file(candidate)
        if text.strip():
            return text.strip()
    return ""


def _page_text(page, max_chars: int = 24000) -> str:
    try:
        text = page.locator("body").inner_text(timeout=3500)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars]
    except Exception:
        return ""


def _interesting_instruction_excerpt(page_text: str, max_chars: int = 8000) -> str:
    text = str(page_text or "")
    if not text:
        return ""

    # Prefer windows around the words Handshake uses for this problem.
    terms = [
        "questionnaire",
        "other required documents",
        "short answer",
        "questions",
        "instructions from employer",
        "job description",
        "about the role",
        "what you",
        "why",
    ]
    lower = text.lower()
    chunks: List[str] = []
    for term in terms:
        start = lower.find(term)
        if start >= 0:
            lo = max(0, start - 1500)
            hi = min(len(text), start + 3500)
            chunk = text[lo:hi].strip()
            if chunk and chunk not in chunks:
                chunks.append(chunk)
        if sum(len(c) for c in chunks) >= max_chars:
            break

    if not chunks:
        return text[:max_chars]

    joined = "\n\n---\n\n".join(chunks)
    return joined[:max_chars]


def _candidate_questions(text: str) -> List[str]:
    questions: List[str] = []
    for match in re.finditer(r"([^\n\r?.!]{15,280}\?)", str(text or "")):
        q = _clean(match.group(1))
        qn = _norm(q)
        if not q or q in questions:
            continue
        if any(term in qn for term in [_norm(t) for t in SENSITIVE_OR_LEGAL_TERMS]):
            continue
        questions.append(q)
        if len(questions) >= 8:
            break
    return questions


def _safe_profile_for_prompt() -> Dict[str, Any]:
    keys = [
        "first_name",
        "last_name",
        "email",
        "phone",
        "city",
        "state",
        "school",
        "degree",
        "major",
        "expected_graduation",
        "gpa",
        "authorized_us",
        "sponsorship",
        "linkedin",
    ]
    return {k: PROFILE.get(k) for k in keys if PROFILE.get(k) is not None}


def _build_prompt(*, company: str, title: str, page_text: str, instructions: str) -> str:
    profile_json = json.dumps(_safe_profile_for_prompt(), indent=2, ensure_ascii=False)
    applicant_brief = load_applicant_brief()
    explicit_questions = _candidate_questions(instructions or page_text)
    question_block = "\n".join(f"- {q}" for q in explicit_questions) or "(No explicit question marks were detected. Infer a concise questionnaire/statement-of-interest document from the visible employer instructions and job description.)"

    return f"""
You are drafting a review-only questionnaire document for a Handshake job application.
The employer asks for a questionnaire, short-answer response, or other required document.

Return JSON only with this shape:
{{
  "document_title": "Questionnaire Responses - Company - Role",
  "responses": [
    {{"question": "question or section heading", "answer": "finished first-person answer"}}
  ],
  "review_notes": ["brief notes for the applicant to check before submitting"]
}}

Company: {company or 'Unknown company'}
Role: {title or 'Unknown role'}

Applicant profile:
{profile_json}

Marketing/product-growth resume facts to use when relevant:
{chr(10).join('- ' + fact for fact in MARKETING_RESUME_FACTS)}

Optional applicant brief from documents/applicant_brief.md:
{applicant_brief or '(No applicant brief was found.)'}

Explicit question candidates found in the page:
{question_block}

Most relevant visible page/instruction text:
{instructions[:8000]}

Broader visible job/application text excerpt:
{page_text[:12000]}

Rules:
- Write in first person as Sample.
- For marketing, growth, product marketing, social media, brand, or content roles, emphasize the e-commerce growth, paid media, customer acquisition, experimentation, conversion optimization, and product/technical background.
- Do not invent companies, jobs, credentials, awards, legal statuses, school dates, publications, or numbers not listed above or visible in the job text.
- If a requested item is not supported by the profile/page facts, say it needs manual review instead of making it up.
- Do not answer legal attestations, signatures, background-check questions, disability/veteran/race/sexual-orientation/transgender questions, or salary requirements.
- Keep each answer concise: usually 90-180 words unless a visible limit says otherwise.
- Do not mention AI, automation, or that this was generated.
- The result will be attached for manual review only; it must still sound polished and ready for the applicant to review.
""".strip()


def _extract_json(text: str) -> Dict[str, Any]:
    text = str(text or "").strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    return {}


def _fallback_payload(company: str, title: str, page_text: str, instructions: str) -> Optional[Dict[str, Any]]:
    if not _truthy(os.getenv("QUESTIONNAIRE_ALLOW_FALLBACK_DRAFT"), False):
        return None

    # A conservative fallback for review-only mode. It is intentionally generic
    # and tells the user to review before submitting.
    return {
        "document_title": f"Questionnaire Responses - {company or 'Company'} - {title or 'Role'}",
        "responses": [
            {
                "question": "Why are you interested in this role?",
                "answer": (
                    "I am interested in this role because it combines product, growth, and hands-on execution. "
                    "I have built and scaled e-commerce businesses from an initial $800 investment to more than $2M in cumulative revenue, "
                    "managed paid acquisition and creative testing, and used experimentation to improve customer acquisition and conversion. "
                    "I would be excited to bring that operator mindset to this team while continuing to learn from real customer and market feedback."
                ),
            },
            {
                "question": "Relevant experience",
                "answer": (
                    "My strongest relevant experience is in growth, paid media, and product execution. At Blanc Studios, I managed acquisition, "
                    "retention, budget allocation, and conversion optimization across businesses that reached 30K+ orders. At Lirvana Labs, "
                    "I led content and growth strategy for a venture-backed technology startup and helped grow YouTube presence to about 100K monthly views. "
                    "My EECS background also helps me work closely with technical teams and understand data, products, and user workflows."
                ),
            },
        ],
        "review_notes": [
            "Fallback draft created without OpenAI. Review carefully before submitting.",
            "Confirm this matches the employer's exact questionnaire instructions.",
        ],
    }


def _generate_payload(*, page, company: str, title: str) -> Optional[Dict[str, Any]]:
    page_text = _page_text(page)
    instructions = _interesting_instruction_excerpt(page_text)

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        print("  ⚠ OPENAI_API_KEY missing; cannot AI-generate questionnaire document.")
        return _fallback_payload(company, title, page_text, instructions)

    model = (
        os.getenv("QUESTIONNAIRE_AGENT_MODEL", "").strip()
        or os.getenv("SHORT_ANSWER_AGENT_MODEL", "").strip()
        or os.getenv("APPLICATION_AGENT_MODEL", "").strip()
        or "gpt-5-mini"
    )

    try:
        from openai import OpenAI

        client = OpenAI()
        response = client.responses.create(
            model=model,
            input=_build_prompt(company=company, title=title, page_text=page_text, instructions=instructions),
        )
        payload = _extract_json(response.output_text)
        responses = payload.get("responses")
        if not isinstance(responses, list) or not responses:
            print("  ⚠ Questionnaire agent returned no usable responses.")
            return _fallback_payload(company, title, page_text, instructions)
        return payload
    except Exception as exc:
        print(f"  ⚠ Questionnaire agent failed safely: {exc}")
        return _fallback_payload(company, title, page_text, instructions)


def _ascii_pdf_text(text: str) -> str:
    replacements = {
        "\u2013": "-",
        "\u2014": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2022": "-",
        "\u00a0": " ",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _escape_pdf_string(text: str) -> str:
    text = _ascii_pdf_text(text)
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _write_simple_pdf(path: Path, lines: List[str]) -> None:
    page_width = 612
    page_height = 792
    margin_x = 54
    top_y = 742
    line_height = 13
    max_lines = 50

    pages: List[List[str]] = []
    current: List[str] = []
    for line in lines:
        if len(current) >= max_lines:
            pages.append(current)
            current = []
        current.append(line)
    if current:
        pages.append(current)
    if not pages:
        pages = [[""]]

    objects: List[bytes] = []

    def add_obj(s: str | bytes) -> int:
        if isinstance(s, str):
            b = s.encode("latin-1", errors="replace")
        else:
            b = s
        objects.append(b)
        return len(objects)

    add_obj("<< /Type /Catalog /Pages 2 0 R >>")  # 1
    add_obj(b"")  # 2 placeholder
    add_obj("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")  # 3

    page_ids: List[int] = []
    for page_lines in pages:
        commands = ["BT", "/F1 10 Tf", "13 TL", f"{margin_x} {top_y} Td"]
        first = True
        for line in page_lines:
            escaped = _escape_pdf_string(line)
            if first:
                commands.append(f"({escaped}) Tj")
                first = False
            else:
                commands.append(f"T* ({escaped}) Tj")
        commands.append("ET")
        stream = "\n".join(commands).encode("latin-1", errors="replace")
        content_id = len(objects) + 2
        page_id = len(objects) + 1
        page_ids.append(page_id)
        add_obj(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_width} {page_height}] /Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>")
        add_obj(b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream")

    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects[1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode("latin-1")

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{i} 0 obj\n".encode("ascii"))
        out.extend(obj)
        out.extend(b"\nendobj\n")
    xref_pos = len(out)
    out.extend(f"xref\n0 {len(objects)+1}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        out.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    out.extend(f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode("ascii"))
    path.write_bytes(bytes(out))


def _slug(value: str, max_len: int = 60) -> str:
    value = re.sub(r"[^A-Za-z0-9]+", "_", str(value or "")).strip("_")
    return (value or "questionnaire")[:max_len].strip("_") or "questionnaire"


def _payload_to_lines(payload: Dict[str, Any], *, company: str, title: str) -> List[str]:
    doc_title = _clean(payload.get("document_title")) or f"Questionnaire Responses - {company} - {title}"
    lines: List[str] = []
    lines.append(doc_title)
    lines.append("")
    lines.append(f"Applicant: {PROFILE.get('first_name', 'Sample')} {PROFILE.get('last_name', 'Applicant')}")
    if PROFILE.get("email"):
        lines.append(f"Email: {PROFILE.get('email')}")
    if PROFILE.get("phone"):
        lines.append(f"Phone: {PROFILE.get('phone')}")
    lines.append(f"Company: {company or 'Unknown company'}")
    lines.append(f"Role: {title or 'Unknown role'}")
    lines.append(f"Drafted for review: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")
    lines.append("NOTE: Review this document before submitting the application.")
    lines.append("")

    responses = payload.get("responses")
    if not isinstance(responses, list):
        responses = []

    for idx, item in enumerate(responses, start=1):
        if not isinstance(item, dict):
            continue
        question = _clean(item.get("question")) or f"Response {idx}"
        answer = str(item.get("answer") or "").strip()
        if not answer:
            continue
        lines.append(f"{idx}. {question}")
        for para in re.split(r"\n\s*\n", answer):
            wrapped = textwrap.wrap(_clean(para), width=92) or [""]
            lines.extend(wrapped)
        lines.append("")

    notes = payload.get("review_notes")
    if isinstance(notes, list) and notes:
        lines.append("Review notes")
        for note in notes[:8]:
            for wrapped in textwrap.wrap("- " + _clean(note), width=92):
                lines.append(wrapped)
        lines.append("")

    return lines


def generate_questionnaire_document(*, page, company: str, title: str) -> Optional[Path]:
    if not questionnaire_generation_enabled():
        print("  Questionnaire document generation is disabled.")
        return None

    payload = _generate_payload(page=page, company=company, title=title)
    if not payload:
        return None

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{_slug(company, 40)}_{_slug(title, 55)}_questionnaire_{timestamp}.pdf"
    path = GENERATED_DIR / filename
    lines = _payload_to_lines(payload, company=company, title=title)
    _write_simple_pdf(path, lines)

    txt_path = path.with_suffix(".txt")
    try:
        txt_path.write_text("\n".join(lines), encoding="utf-8")
    except Exception:
        pass

    print(f"  ✓ Generated review-only questionnaire document: {path.name}")
    return path.resolve()


def latest_generated_questionnaire() -> Optional[Path]:
    try:
        files = sorted(GENERATED_DIR.glob("*_questionnaire_*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
        for p in files:
            if p.exists() and p.is_file():
                return p.resolve()
    except Exception:
        pass
    return None
