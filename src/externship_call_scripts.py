from __future__ import annotations

from pathlib import Path

from src.externship_models import Lead
from src.externship_profile import SAMPLE_PROFILE
from src.externship_email_writer import clean_filename


def main_phone(lead: Lead) -> str:
    if lead.main_phone:
        return lead.main_phone
    if lead.phones_found:
        return lead.phones_found[0]
    return "[find main clinic phone]"


def script_for_lead(lead: Lead) -> str:
    p = SAMPLE_PROFILE
    manager = lead.contact_name or lead.contact_title or "the office manager or clinical supervisor"
    return f"""CALL TARGET: {lead.clinic_name}
PHONE: {main_phone(lead)}
ASK FOR: {manager}
WEBSITE: {lead.website or lead.contact_page}

FRONT DESK SCRIPT
Hi, my name is Sample Applicant. I’m calling to ask whether your clinic is open to hosting a medical extern or considering an entry-level clinic assistant / medical assistant opportunity. Is your office manager, practice manager, or clinical supervisor available?

IF ASKED FOR DETAILS
I’m based in Berkeley, have a car, and can commute up to about an hour. I’m flexible on start date and schedule right now. I have CPR, HIPAA, immunization/TB documentation, and background/drug screen readiness available if needed. I can send my resume and any documents your clinic needs.

IF MANAGER IS UNAVAILABLE
What is the best email address for the person who handles externships, student placements, or hiring for medical assistants?

IF THEY SAY THEY DO NOT TAKE EXTERNS
Thank you. Do you know of any nearby clinics, urgent cares, or practice managers who do take externs or entry-level medical assistants?

VOICEMAIL
Hi, this is Sample Applicant. I’m calling to ask if {lead.clinic_name} is open to hosting a medical extern or considering an entry-level clinic assistant / medical assistant opportunity. I’m based in Berkeley, have CPR and HIPAA training, and can provide my resume and onboarding documents. My phone number is {p['phone']}. Again, that’s {p['phone']}. Thank you.

CALL LOG OPTIONS
- no answer
- left voicemail
- receptionist said email manager
- manager interested
- not accepting externs
- call back later
- wrong number
- needs school paperwork
- needs resume first
""".strip()


def write_call_script(lead: Lead, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{clean_filename(lead.clinic_name)}_call_script.txt"
    path.write_text(script_for_lead(lead), encoding="utf-8")
    return path
