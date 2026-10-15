from __future__ import annotations

import base64
import csv
import hashlib
from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import Iterable

from src.externship_config import GMAIL_CREDENTIALS_PATH, GMAIL_TOKEN_PATH, OUTREACH_DAILY_SEND_LIMIT
from src.externship_email_writer import body_for_lead, choose_recipient, subject_for_lead
from src.externship_filters import active_leads
from src.externship_models import Lead
from src.externship_profile import SAMPLE_PROFILE

SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]

QUEUE_FIELDS = [
    "queue_id",
    "draft_type",
    "clinic_name",
    "contact_email",
    "subject",
    "body_preview",
    "gmail_draft_id",
    "approved_to_send",
    "sent_at",
    "message_id",
    "created_at",
    "notes",
]


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def date_yyyy_mm_dd() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _lazy_google_imports():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except Exception as exc:
        raise RuntimeError(
            "Missing Gmail API packages. Run: python -m pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib"
        ) from exc
    return Request, Credentials, InstalledAppFlow, build


def gmail_service():
    Request, Credentials, InstalledAppFlow, build = _lazy_google_imports()
    creds = None
    token_path = GMAIL_TOKEN_PATH
    credentials_path = GMAIL_CREDENTIALS_PATH
    token_path.parent.mkdir(parents=True, exist_ok=True)

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        if not credentials_path.exists():
            raise FileNotFoundError(
                f"Missing Gmail OAuth credentials file: {credentials_path}\n"
                "Download OAuth Desktop credentials from Google Cloud and save them as credentials.json in the project root."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
        creds = flow.run_local_server(port=0)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    return build("gmail", "v1", credentials=creds)


def make_mime_message(to: str, subject: str, body: str, sender: str = "", reply_to: str = "") -> str:
    msg = EmailMessage()
    msg["To"] = to
    if sender:
        msg["From"] = sender
    if reply_to:
        msg["Reply-To"] = reply_to
    msg["Subject"] = subject
    msg.set_content(body)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    return raw


def create_gmail_draft(service, *, to: str, subject: str, body: str, sender: str = "", reply_to: str = "") -> str:
    raw = make_mime_message(to=to, subject=subject, body=body, sender=sender, reply_to=reply_to)
    draft = service.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
    return str(draft.get("id") or "")


def send_gmail_draft(service, draft_id: str) -> str:
    sent = service.users().drafts().send(userId="me", body={"id": draft_id}).execute()
    return str(sent.get("id") or "")


def queue_id_for(*parts: str) -> str:
    raw = "|".join(str(p or "") for p in parts).lower().encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:16]


def load_queue(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as f:
        return [dict(row) for row in csv.DictReader(f)]


def save_queue(path: Path, rows: Iterable[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=QUEUE_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in QUEUE_FIELDS})


def upsert_queue_row(path: Path, row: dict[str, str]) -> None:
    rows = load_queue(path)
    by_id = {r.get("queue_id", ""): r for r in rows if r.get("queue_id")}
    old = by_id.get(row["queue_id"], {})
    merged = dict(old)
    merged.update({k: v for k, v in row.items() if v != ""})
    if not merged.get("approved_to_send"):
        merged["approved_to_send"] = "NO"
    by_id[row["queue_id"]] = merged
    save_queue(path, by_id.values())


def _lead_draft_values(lead: Lead, draft_type: str, *, sender_email: str = "") -> tuple[str, str, str]:
    to = choose_recipient(lead)
    subject = subject_for_lead(lead)
    followup = draft_type.startswith("followup")
    if followup:
        subject = f"Re: {subject}"
    body = body_for_lead(lead, followup=followup, sender_email=sender_email, sender_mode="candidate")
    return to, subject, body


def create_drafts_for_leads(
    leads: list[Lead],
    *,
    queue_path: Path,
    top: int | None = None,
    force: bool = False,
    draft_type: str = "initial",
) -> tuple[list[Lead], int, int]:
    selected = active_leads(leads)
    if top:
        selected = selected[:top]
    service = gmail_service()
    sender_email = ""
    try:
        sender_email = str(service.users().getProfile(userId="me").execute().get("emailAddress") or "")
    except Exception:
        sender_email = ""
    if sender_email:
        print(f"Gmail sender: {sender_email}")
    created = 0
    skipped = 0

    for lead in selected:
        to, subject, body = _lead_draft_values(lead, draft_type, sender_email=sender_email)
        if not to:
            skipped += 1
            print(f"SKIP no email: {lead.clinic_name}")
            continue
        if draft_type == "initial" and lead.gmail_draft_id and not force:
            skipped += 1
            print(f"SKIP existing Gmail draft: {lead.clinic_name} ({lead.gmail_draft_id})")
            continue
        if draft_type == "followup1" and lead.followup_1_draft_id and not force:
            skipped += 1
            print(f"SKIP existing follow-up #1 draft: {lead.clinic_name} ({lead.followup_1_draft_id})")
            continue
        if draft_type == "followup2" and lead.followup_2_draft_id and not force:
            skipped += 1
            print(f"SKIP existing follow-up #2 draft: {lead.clinic_name} ({lead.followup_2_draft_id})")
            continue

        draft_id = create_gmail_draft(service, to=to, subject=subject, body=body, reply_to=str(SAMPLE_PROFILE.get("email", "")))
        created += 1
        stamp = now_iso()
        if draft_type == "initial":
            lead.gmail_draft_id = draft_id
            lead.gmail_draft_created_at = stamp
        elif draft_type == "followup1":
            lead.followup_1_draft_id = draft_id
        elif draft_type == "followup2":
            lead.followup_2_draft_id = draft_id

        qid = queue_id_for(draft_type, lead.clinic_name, to, subject)
        upsert_queue_row(queue_path, {
            "queue_id": qid,
            "draft_type": draft_type,
            "clinic_name": lead.clinic_name,
            "contact_email": to,
            "subject": subject,
            "body_preview": body[:900].replace("\n", " "),
            "gmail_draft_id": draft_id,
            "approved_to_send": "NO",
            "created_at": stamp,
            "notes": "First-person tailored Sample draft. Review in Gmail. Change approved_to_send to YES only after manual approval.",
        })
        print(f"Gmail draft created: {lead.clinic_name} -> {to} ({draft_id})")
    return leads, created, skipped


def _is_approved(value: str) -> bool:
    return str(value or "").strip().lower() in {"yes", "y", "true", "1", "approved", "send"}


def send_approved_drafts(queue_path: Path, *, confirm_send: bool = False, daily_limit: int | None = None) -> tuple[int, int]:
    rows = load_queue(queue_path)
    if not rows:
        print(f"No queue file found at {queue_path}")
        return 0, 0
    pending = [r for r in rows if _is_approved(r.get("approved_to_send", "")) and not r.get("sent_at") and r.get("gmail_draft_id")]
    daily_limit = daily_limit or OUTREACH_DAILY_SEND_LIMIT
    pending = pending[:daily_limit]
    if not pending:
        print("No approved unsent drafts in queue.")
        return 0, 0
    print(f"Approved unsent drafts: {len(pending)}")
    for row in pending:
        print(f" - {row.get('clinic_name')} <{row.get('contact_email')}> [{row.get('draft_type')}] {row.get('gmail_draft_id')}")
    if not confirm_send:
        print("Dry run only. To send these Gmail drafts, rerun with --confirm-send.")
        return 0, len(pending)

    service = gmail_service()
    sent_count = 0
    today = date_yyyy_mm_dd()
    for row in rows:
        if sent_count >= daily_limit:
            break
        if not _is_approved(row.get("approved_to_send", "")) or row.get("sent_at") or not row.get("gmail_draft_id"):
            continue
        message_id = send_gmail_draft(service, row["gmail_draft_id"])
        row["sent_at"] = now_iso()
        row["message_id"] = message_id
        row["notes"] = (row.get("notes", "") + f" | sent {today}").strip(" |")
        sent_count += 1
        print(f"SENT: {row.get('clinic_name')} -> {row.get('contact_email')} ({message_id})")
    save_queue(queue_path, rows)
    return sent_count, 0


def delete_gmail_draft(service, draft_id: str) -> None:
    service.users().drafts().delete(userId="me", id=draft_id).execute()


def delete_queued_drafts(queue_path: Path, *, confirm_delete: bool = False) -> tuple[int, int]:
    rows = load_queue(queue_path)
    if not rows:
        print(f"No queue file found at {queue_path}")
        return 0, 0
    targets = [r for r in rows if r.get("gmail_draft_id") and not r.get("sent_at")]
    if not targets:
        print("No queued unsent Gmail drafts to delete.")
        return 0, 0
    print(f"Queued unsent Gmail drafts: {len(targets)}")
    for row in targets:
        print(f" - {row.get('clinic_name')} <{row.get('contact_email')}> {row.get('gmail_draft_id')}")
    if not confirm_delete:
        print("Dry run only. Rerun with --confirm-delete to delete these Gmail drafts and clear queue draft IDs.")
        return 0, len(targets)
    service = gmail_service()
    deleted = 0
    errors = 0
    for row in rows:
        draft_id = row.get("gmail_draft_id")
        if not draft_id or row.get("sent_at"):
            continue
        try:
            delete_gmail_draft(service, draft_id)
            deleted += 1
            row["gmail_draft_id"] = ""
            row["notes"] = (row.get("notes", "") + " | deleted queued draft").strip(" |")
            print(f"DELETED draft: {row.get('clinic_name')} ({draft_id})")
        except Exception as exc:
            errors += 1
            row["notes"] = (row.get("notes", "") + f" | delete failed: {exc}").strip(" |")
            print(f"ERROR deleting {draft_id}: {exc}")
    save_queue(queue_path, rows)
    return deleted, errors


def parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00").replace("+00:00", ""))
    except Exception:
        try:
            return datetime.strptime(value[:10], "%Y-%m-%d")
        except Exception:
            return None


def leads_due_for_followup(leads: list[Lead], *, days_since: int, followup_number: int, include_all: bool = False) -> list[Lead]:
    cutoff = datetime.now() - timedelta(days=days_since)
    due: list[Lead] = []
    for lead in active_leads(leads):
        if not choose_recipient(lead):
            continue
        if include_all:
            due.append(lead)
            continue
        if followup_number == 1:
            if lead.followup_1_sent_at or lead.followup_1_draft_id:
                continue
            sent_at = parse_iso(lead.first_email_sent_at)
        else:
            if lead.followup_2_sent_at or lead.followup_2_draft_id:
                continue
            sent_at = parse_iso(lead.followup_1_sent_at)
        if sent_at and sent_at <= cutoff:
            due.append(lead)
    return due
