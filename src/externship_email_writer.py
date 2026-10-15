from __future__ import annotations

import html
import re
from email.message import EmailMessage
from pathlib import Path

from src.externship_config import get_env
from src.externship_models import Lead
from src.externship_profile import SAMPLE_PROFILE
from src.externship_tailor import tailoring_lines_for_lead


def clean_filename(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value or "lead").strip("_")
    return value[:100] or "lead"


def choose_recipient(lead: Lead) -> str:
    if lead.contact_email:
        return lead.contact_email
    if lead.emails_found:
        return lead.emails_found[0]
    return ""


def _phone_pretty(raw: str) -> str:
    digits = re.sub(r"\D+", "", raw or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return raw or ""


def subject_for_lead(lead: Lead) -> str:
    clinic = (lead.clinic_name or "your clinic").strip()
    if len(clinic) > 70:
        clinic = clinic[:67].rstrip() + "..."
    return f"Medical externship inquiry - {clinic}"


def greeting_for_lead(lead: Lead) -> str:
    if lead.contact_name:
        first = lead.contact_name.split()[0].strip(",")
        if first:
            return f"Hi {first},"
    if lead.contact_title:
        title = lead.contact_title.strip()
        if title.lower().startswith(("dr.", "doctor")):
            return f"Hello {title},"
    return "Hello,"


def _credential_text() -> str:
    p = SAMPLE_PROFILE
    credentials: list[str] = []
    for label, key in [
        ("CPR", "cpr"),
        ("HIPAA training", "hipaa"),
        ("immunization/TB documentation", "immunizations_tb"),
        ("background check/drug screen readiness", "background_drug_screen"),
    ]:
        if str(p.get(key, "")).lower().startswith("yes"):
            credentials.append(label)
    return ", ".join(credentials) if credentials else "standard onboarding documents as requested"


def _candidate_voice_for(sender_email: str = "", sender_mode: str = "") -> bool:
    # The user requested first-person candidate voice. Keep helper mode available only when explicitly requested.
    mode = (sender_mode or get_env("EXTERNSHIP_EMAIL_SENDER_MODE", "candidate") or "candidate").strip().lower()
    if mode in {"helper", "coordinator", "third_person", "sample"}:
        return False
    if mode in {"auto"}:
        if sender_email:
            return sender_email.strip().lower() == str(SAMPLE_PROFILE.get("email", "")).strip().lower()
        return True
    return True


def _source_line_for_report(lead: Lead) -> str:
    lines = tailoring_lines_for_lead(lead)
    return lines.get("source_note", "")


def body_for_lead(
    lead: Lead,
    *,
    followup: bool = False,
    sender_email: str = "",
    sender_mode: str = "",
) -> str:
    p = SAMPLE_PROFILE
    name = p["full_name"]
    email = p["email"]
    phone = _phone_pretty(p["phone"])
    location = p["base_location"]
    commute = p["commute_limit"].lower()
    availability = p.get("availability", "Flexible")
    cred_text = _credential_text()
    clinic = lead.clinic_name or "your clinic"
    candidate_voice = _candidate_voice_for(sender_email, sender_mode)
    lines = tailoring_lines_for_lead(lead)
    noticed = lines.get("noticed") or f"I looked through the information I found for {clinic}."
    interest = lines.get("interest") or "I am interested in learning in a real patient-facing clinic environment."
    tasks = lines.get("tasks") or "patient intake, rooming, vitals, front/back-office support, EHR/admin help, and patient communication"

    helper_name = get_env("EXTERNSHIP_HELPER_NAME", "Sample Applicant")
    helper_line = get_env("EXTERNSHIP_HELPER_LINE", "Coordinating outreach for Sample Applicant")

    if followup:
        if candidate_voice:
            return f"""{greeting_for_lead(lead)}

I wanted to follow up on my note about a possible medical externship, volunteer clinical placement, or entry-level clinic assistant opportunity with {clinic}.

{noticed} {interest}

I am hoping to learn and contribute around {tasks}. I am based in {location}, have a car, can commute {commute}, and my availability is flexible. I can provide my resume plus {cred_text}.

Would your office be open to reviewing my resume, or could you point me to the office manager, practice manager, clinical supervisor, or externship/student placement contact?

Thank you,
{name}
{email}
{phone}
""".strip()
        return f"""{greeting_for_lead(lead)}

I wanted to follow up on my note about {name}, who is looking for a medical externship, volunteer clinical placement, or entry-level clinic assistant opportunity with {clinic}.

{noticed} {interest}

Sample is hoping to learn and contribute around {tasks}. She is based in {location}, has a car, can commute {commute}, and her availability is flexible. She can provide her resume plus {cred_text}.

Would your office be open to reviewing her resume, or could you point me to the office manager, practice manager, clinical supervisor, or externship/student placement contact?

Thank you,
{helper_name}
{helper_line}
Sample: {email} | {phone}
""".strip()

    if candidate_voice:
        return f"""{greeting_for_lead(lead)}

My name is {name}. I am looking for a medical externship, volunteer clinical placement, or entry-level clinic assistant opportunity where I can learn real clinic workflow and become useful to the team.

{noticed} {interest}

The areas I am most interested in learning and helping with are {tasks}. I am also open to front office, back office, patient intake, rooming/vitals support, scheduling, administrative support, or another clinic assistant pathway if that is what your office needs.

I am based in {location}, have a car, can commute {commute}, and my schedule/start date are flexible. I can provide my resume plus {cred_text}.

Would {clinic} be open to reviewing my resume for an externship or entry-level clinic assistant opportunity? If someone else handles this, could you point me to the office manager, practice manager, clinical supervisor, or student placement/externship contact?

Thank you,
{name}
{email}
{phone}
""".strip()

    return f"""{greeting_for_lead(lead)}

I am helping {name}, a Berkeley-based medical externship candidate, contact clinics directly. She is looking for a medical externship, volunteer clinical placement, or entry-level clinic assistant opportunity where she can learn real clinic workflow and become useful to the team.

{noticed} {interest}

The areas Sample is most interested in learning and helping with are {tasks}. She is also open to front office, back office, patient intake, rooming/vitals support, scheduling, administrative support, or another clinic assistant pathway if that is what your office needs.

Sample is based in {location}, has a car, can commute {commute}, and her schedule/start date are flexible. She can provide her resume plus {cred_text}.

Would {clinic} be open to reviewing her resume for an externship or entry-level clinic assistant opportunity? If someone else handles this, could you point me to the office manager, practice manager, clinical supervisor, or student placement/externship contact?

Thank you,
{helper_name}
{helper_line}
Sample: {email} | {phone}
""".strip()


def write_draft_files(lead: Lead, out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = clean_filename(f"{lead.clinic_name}_{lead.city}")
    recipient = choose_recipient(lead)
    subject = subject_for_lead(lead)
    body = body_for_lead(lead, sender_mode="candidate")
    followup_body = body_for_lead(lead, followup=True, sender_mode="candidate")

    txt_path = out_dir / f"{stem}_email.txt"
    txt_path.write_text(
        f"TO: {recipient or '[find public contact email or use contact form]'}\n"
        f"SUBJECT: {subject}\n\n"
        f"{body}\n",
        encoding="utf-8",
    )

    followup_path = out_dir / f"{stem}_followup.txt"
    followup_path.write_text(
        f"TO: {recipient or '[same as first email]'}\n"
        f"SUBJECT: Re: {subject}\n\n"
        f"{followup_body}\n",
        encoding="utf-8",
    )

    eml = EmailMessage()
    eml["To"] = recipient or ""
    eml["From"] = SAMPLE_PROFILE["email"]
    eml["Reply-To"] = SAMPLE_PROFILE["email"]
    eml["Subject"] = subject
    eml.set_content(body)
    eml_path = out_dir / f"{stem}.eml"
    eml_path.write_text(eml.as_string(), encoding="utf-8")

    return {"email_txt": txt_path, "followup_txt": followup_path, "eml": eml_path}


def write_email_preview(
    leads: list[Lead],
    out_path: Path,
    *,
    top: int | None = None,
    sender_email: str = "",
    sender_mode: str = "candidate",
) -> Path:
    selected = leads[:top] if top else leads
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cards = []
    for lead in selected:
        to = choose_recipient(lead) or "[no public email found]"
        subject = subject_for_lead(lead)
        body = body_for_lead(lead, sender_email=sender_email, sender_mode=sender_mode)
        followup = body_for_lead(lead, followup=True, sender_email=sender_email, sender_mode=sender_mode)
        lines = tailoring_lines_for_lead(lead)
        website = lead.website or lead.contact_page or lead.source_url or lead.google_maps_url or ""
        cards.append(
            "<section class='card'>"
            f"<h2>{html.escape(lead.clinic_name or 'Unknown clinic')}</h2>"
            f"<p><strong>Website:</strong> {html.escape(website or '[none]')}<br>"
            f"<strong>Services used:</strong> {html.escape(lines.get('services') or '[inferred from lead data]')}<br>"
            f"<strong>Tailoring evidence:</strong> {html.escape(lines.get('source_note') or '[none captured]')}</p>"
            f"<p><strong>To:</strong> {html.escape(to)}<br>"
            f"<strong>Subject:</strong> {html.escape(subject)}</p>"
            f"<h3>Initial email</h3><pre>{html.escape(body)}</pre>"
            f"<h3>Follow-up</h3><pre>{html.escape(followup)}</pre>"
            "</section>"
        )
    mode_text = "candidate first-person voice" if _candidate_voice_for(sender_email, sender_mode) else "helper/coordinator voice"
    html_doc = f"""<!doctype html>
<html><head><meta charset='utf-8'><title>Externship Email Preview</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 28px; background:#f6f7f9; color:#1f2937; }}
.card {{ background:#fff; border:1px solid #ddd; border-radius:12px; padding:18px 22px; margin:0 0 18px; box-shadow:0 1px 3px rgba(0,0,0,.05); }}
h1 {{ margin-bottom:6px; }}
h2 {{ margin:0 0 8px; font-size:20px; }}
h3 {{ margin:16px 0 8px; }}
pre {{ white-space:pre-wrap; line-height:1.45; font-size:14px; background:#f9fafb; padding:14px; border-radius:8px; border:1px solid #e5e7eb; }}
.note {{ color:#4b5563; margin-bottom:18px; }}
</style></head><body>
<h1>Tailored Externship Email Preview</h1>
<p class='note'>Mode: {html.escape(mode_text)}. These drafts use website/lead-specific services, interests, and clinic workflow language. Review before creating or sending Gmail drafts.</p>
{''.join(cards)}
</body></html>"""
    out_path.write_text(html_doc, encoding="utf-8")
    return out_path
