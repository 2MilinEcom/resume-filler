from __future__ import annotations

import argparse
import csv
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.externship_models import Lead
from src.externship_seed_data import STARTER_LEADS
from src.externship_io import ensure_dirs, load_leads_csv, merge_leads, save_leads_csv, save_leads_json
from src.externship_contact_finder import enrich_leads, score_lead
from src.externship_email_writer import write_draft_files, write_email_preview
from src.externship_call_scripts import write_call_script
from src.externship_report import write_report
from src.externship_tracker import initialize_tracker, print_followups_due
from src.externship_config import DEFAULT_MAX_LEADS, DEFAULT_RADIUS_MILES, DEFAULT_TOP, FOLLOWUP_1_DAYS, FOLLOWUP_2_DAYS, get_env
from src.externship_google_places import discover_google_places, test_google_places
from src.externship_npi import enrich_leads_with_npi
from src.externship_filters import active_leads, excluded_leads, mark_excluded_leads, write_exclusion_report, filter_leads_file
from src.externship_gmail import create_drafts_for_leads, delete_queued_drafts, leads_due_for_followup, send_approved_drafts, load_queue
from src.externship_call_queue import write_call_queue
from src.externship_tailor import tailor_leads
from src.externship_apollo import apollo_health, apollo_enrich_leads
from src.externship_hiring_signals import scan_hiring_signals

DATA_DIR = ROOT / "data"
LEADS_CSV = DATA_DIR / "externship_leads.csv"
LEADS_JSON = DATA_DIR / "externship_leads.json"
TRACKER_CSV = DATA_DIR / "externship_tracker.csv"
REPORT_HTML = DATA_DIR / "externship_review.html"
REPORT_JSON = DATA_DIR / "externship_review.json"
EXCLUDED_CSV = DATA_DIR / "externship_excluded_leads.csv"
SEND_QUEUE_CSV = DATA_DIR / "externship_send_queue.csv"
CALL_QUEUE_CSV = DATA_DIR / "externship_call_queue.csv"
CALL_QUEUE_HTML = DATA_DIR / "externship_call_queue.html"
EMAIL_PREVIEW_HTML = DATA_DIR / "externship_email_preview.html"
APOLLO_REPORT_CSV = DATA_DIR / "externship_apollo_report.csv"
APOLLO_REPORT_JSON = DATA_DIR / "externship_apollo_report.json"
HIRING_REPORT_CSV = DATA_DIR / "externship_hiring_signals.csv"
DRAFTS_DIR = ROOT / "drafts" / "externship"


def seed_leads() -> list[Lead]:
    return [Lead.from_dict(item) for item in STARTER_LEADS]


def _sort_active(leads: list[Lead]) -> list[Lead]:
    return sorted(active_leads(leads), key=score_lead, reverse=True)


def _save_active_and_excluded(leads: list[Lead]) -> list[Lead]:
    """Mark academy/school leads, write excluded report, save only active clinic leads."""
    ensure_dirs(ROOT)
    marked = mark_excluded_leads(leads)
    active = active_leads(marked)
    write_exclusion_report(marked, EXCLUDED_CSV)
    save_leads_csv(LEADS_CSV, active)
    save_leads_json(LEADS_JSON, active)
    initialize_tracker(TRACKER_CSV, active)
    removed = len(excluded_leads(marked))
    if removed:
        print(f"Academy/school filter removed {removed} lead(s). Details: {EXCLUDED_CSV}")
    return active


def cmd_init(args) -> None:
    ensure_dirs(ROOT)
    existing = load_leads_csv(LEADS_CSV)
    merged = merge_leads(existing, seed_leads())
    active = _save_active_and_excluded(merged)
    print(f"Initialized externship outreach data with {len(active)} active clinic lead(s).")
    print(f"Lead CSV: {LEADS_CSV}")
    print(f"Tracker:  {TRACKER_CSV}")


def cmd_add_lead(args) -> None:
    ensure_dirs(ROOT)
    leads = load_leads_csv(LEADS_CSV)
    lead = Lead(
        clinic_name=args.name,
        specialty=args.specialty or "",
        city=args.city or "",
        website=args.website or "",
        contact_page=args.contact_page or "",
        main_phone=args.phone or "",
        contact_name=args.contact_name or "",
        contact_title=args.contact_title or "",
        contact_email=args.email or "",
        source_note="manually added",
        priority=args.priority or "medium",
        tags=args.tags or "manual",
        discovery_source="manual",
    )
    merged = merge_leads(leads, [lead])
    active = _save_active_and_excluded(merged)
    print(f"Added/merged lead: {args.name}")
    print(f"Active lead count: {len(active)}")


def load_or_seed() -> list[Lead]:
    ensure_dirs(ROOT)
    leads = load_leads_csv(LEADS_CSV)
    if not leads:
        leads = seed_leads()
        leads = _save_active_and_excluded(leads)
    return leads


def save_all(leads: list[Lead]) -> list[Lead]:
    return _save_active_and_excluded(leads)


def cmd_filter(args) -> None:
    before, kept, backup = filter_leads_file(LEADS_CSV, LEADS_JSON)
    leads = load_leads_csv(LEADS_CSV)
    write_exclusion_report(load_leads_csv(backup) if backup else [], EXCLUDED_CSV)
    print(f"Academy/school filter complete: {before} -> {kept} active lead(s).")
    if backup:
        print(f"Backup: {backup}")
    print(f"Current lead CSV: {LEADS_CSV}")
    print(f"Excluded report: {EXCLUDED_CSV}")


def cmd_discover(args) -> None:
    ensure_dirs(ROOT)
    existing = load_or_seed() if getattr(args, "include_seed", False) else load_leads_csv(LEADS_CSV)
    if not get_env("GOOGLE_MAPS_API_KEY"):
        print("Missing GOOGLE_MAPS_API_KEY in .env. Add it first, then rerun discover.")
        return
    found = discover_google_places(radius_miles=args.radius_miles, max_leads=args.max_leads)
    if not found:
        print("WARNING: Google Places returned 0 new leads. Run: python externship_outreach.py test-google")
    else:
        print(f"Google Places returned {len(found)} fresh lead(s) before merging with existing CSV.")
    merged = merge_leads(existing, found)
    marked = mark_excluded_leads(merged)
    work = active_leads(marked)
    if not args.skip_npi:
        work = enrich_leads_with_npi(work, max_leads=args.max_leads)
    if not args.skip_website_enrich:
        work = enrich_leads(work, max_leads=args.max_leads)
    work = tailor_leads(work, top=args.max_leads, force_refresh=False)
    active = save_all(work + excluded_leads(marked))
    print(f"Discovery complete. Total stored active clinic leads: {len(active)}")
    print(f"Lead CSV: {LEADS_CSV}")


def cmd_npi(args) -> None:
    leads = _sort_active(load_or_seed())
    leads = enrich_leads_with_npi(leads, max_leads=args.max_leads)
    active = save_all(leads)
    print(f"NPI enrichment complete for {len(active)} active stored lead(s).")


def cmd_enrich(args) -> None:
    leads = _sort_active(load_or_seed())
    if args.npi:
        leads = enrich_leads_with_npi(leads, max_leads=args.max_leads)
    leads = enrich_leads(leads, max_leads=args.max_leads)
    leads = tailor_leads(leads, top=args.max_leads, force_refresh=False)
    active = save_all(leads)
    print(f"Enriched {len(active)} active lead(s).")


def cmd_drafts(args) -> None:
    leads = _sort_active(load_or_seed())
    if args.top:
        leads = leads[:args.top]
    leads = tailor_leads(leads, top=None, force_refresh=False)
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    for lead in leads:
        paths = write_draft_files(lead, DRAFTS_DIR)
        script_path = write_call_script(lead, DRAFTS_DIR)
        print(f"Drafted {lead.clinic_name}: {paths['email_txt'].name}, {script_path.name}")
    # Merge updated tailoring fields back into the full lead CSV.
    full = merge_leads(load_or_seed(), leads)
    save_all(full)
    print(f"Drafts folder: {DRAFTS_DIR}")


def cmd_email_preview(args) -> None:
    leads = _sort_active(load_or_seed())
    if args.top:
        leads = leads[:args.top]
    leads = tailor_leads(leads, top=None, force_refresh=False)
    full = merge_leads(load_or_seed(), leads)
    save_all(full)
    sender_email = getattr(args, "sender_email", "") or get_env("EXTERNSHIP_PREVIEW_SENDER_EMAIL", "")
    sender_mode = getattr(args, "sender_mode", "candidate") or "candidate"
    out = write_email_preview(
        leads,
        EMAIL_PREVIEW_HTML,
        top=None,
        sender_email=sender_email,
        sender_mode=sender_mode,
    )
    print(f"Email preview: {out}")
    print("Review this before creating Gmail drafts.")
    if args.open:
        webbrowser.open(out.resolve().as_uri())


def cmd_tailor(args) -> None:
    leads = _sort_active(load_or_seed())
    if args.top:
        leads = leads[:args.top]
    leads = tailor_leads(leads, top=None, force_refresh=args.force_refresh)
    full = merge_leads(load_or_seed(), leads)
    active = save_all(full)
    write_report(active, REPORT_HTML, REPORT_JSON)
    print(f"Website tailoring refreshed for {len(leads)} lead(s).")
    print(f"Report: {REPORT_HTML}")
    if args.open:
        webbrowser.open(REPORT_HTML.resolve().as_uri())

def cmd_report(args) -> None:
    leads = _sort_active(load_or_seed())
    leads = tailor_leads(leads, top=None, force_refresh=False)
    save_all(leads)
    write_report(leads, REPORT_HTML, REPORT_JSON)
    initialize_tracker(TRACKER_CSV, leads)
    print(f"Report: {REPORT_HTML}")
    print(f"JSON:   {REPORT_JSON}")
    print(f"Excluded academy/school leads: {EXCLUDED_CSV}")
    if args.open:
        webbrowser.open(REPORT_HTML.resolve().as_uri())


def cmd_run(args) -> None:
    cmd_init(args)
    if args.discover:
        cmd_discover(args)
    elif not args.skip_enrich:
        cmd_enrich(args)
    cmd_drafts(args)
    cmd_report(args)
    print("\nPipeline complete. Review drafts before sending anything.")


def cmd_test_google(args) -> None:
    code = test_google_places()
    if code == 0:
        print("Google Places diagnostic passed.")
    else:
        print(f"Google Places diagnostic failed with code {code}.")


def cmd_followups(args) -> None:
    print_followups_due(TRACKER_CSV)


def cmd_hiring_scan(args) -> None:
    leads = _sort_active(load_or_seed())
    leads = scan_hiring_signals(
        leads,
        top=args.top,
        force_refresh=args.force_refresh,
        report_csv=HIRING_REPORT_CSV,
    )
    leads = tailor_leads(leads, top=None, force_refresh=False)
    active = save_all(leads)
    write_report(active, REPORT_HTML, REPORT_JSON)
    active_signals = [l for l in active if getattr(l, "hiring_signal_status", "") in {"active_ma_opening", "careers_page_found", "externship_signal"}]
    active_ma = [l for l in active if getattr(l, "hiring_signal_status", "") == "active_ma_opening"]
    print(f"Hiring scan complete. Active/careers/externship signals: {len(active_signals)}; active MA/clinic-support openings: {len(active_ma)}")
    print(f"Hiring report: {HIRING_REPORT_CSV}")
    print(f"Dashboard updated: {REPORT_HTML}")
    if args.open:
        webbrowser.open(REPORT_HTML.resolve().as_uri())


def cmd_apollo_test(args) -> None:
    try:
        result = apollo_health()
    except Exception as exc:
        print(f"Apollo API test failed: {exc}")
        raise SystemExit(2)
    print("Apollo API key loaded and accepted.")
    if result:
        status = result.get("status") or result.get("message") or result.get("health") or "ok"
        print(f"Apollo health: {status}")
    print("Safe defaults: phones=false, personal emails=false, waterfall=false.")


def cmd_apollo_preview(args) -> None:
    leads = _sort_active(load_or_seed())
    leads, summary = apollo_enrich_leads(
        leads,
        missing_email_only=args.missing_email_only,
        max_clinics=args.max_clinics,
        max_credits=args.max_credits,
        contacts_per_clinic=args.contacts_per_clinic,
        search_only=True,
        hiring_contacts_only=getattr(args, "hiring_contacts_only", False),
        require_hiring_signal=getattr(args, "require_hiring_signal", False),
        strict_hiring_owners=False,
        report_csv=APOLLO_REPORT_CSV,
        report_json=APOLLO_REPORT_JSON,
    )
    save_all(leads)
    print(f"Apollo preview complete. Clinics searched: {summary.get('searched_clinics')}; candidates found: {summary.get('candidates_found')}")
    print("No paid enrichment was requested in preview mode.")
    print(f"Preview CSV: {APOLLO_REPORT_CSV}")


def cmd_apollo_enrich(args) -> None:
    leads = _sort_active(load_or_seed())
    leads, summary = apollo_enrich_leads(
        leads,
        missing_email_only=args.missing_email_only,
        max_clinics=args.max_clinics,
        max_credits=args.max_credits,
        contacts_per_clinic=args.contacts_per_clinic,
        search_only=False,
        hiring_contacts_only=getattr(args, "hiring_contacts_only", False),
        require_hiring_signal=getattr(args, "require_hiring_signal", False),
        strict_hiring_owners=False,
        report_csv=APOLLO_REPORT_CSV,
        report_json=APOLLO_REPORT_JSON,
    )
    leads = tailor_leads(leads, top=None, force_refresh=False)
    active = save_all(leads)
    write_report(active, REPORT_HTML, REPORT_JSON)
    print("Apollo enrichment complete.")
    print(f"Clinics searched: {summary.get('searched_clinics')}")
    print(f"Candidates found: {summary.get('candidates_found')}")
    print(f"People enrichment requested: {summary.get('enrichment_requested')}")
    print(f"Emails found: {summary.get('emails_found')}")
    print(f"Credits reported by Apollo: {summary.get('credits_consumed')}")
    print(f"Apollo report: {APOLLO_REPORT_CSV}")
    print(f"Lead CSV updated: {LEADS_CSV}")
    print(f"Dashboard updated: {REPORT_HTML}")
    if args.open:
        webbrowser.open(REPORT_HTML.resolve().as_uri())


def cmd_apollo_hiring_preview(args) -> None:
    # This is the safer v8 flow: scan for hiring signals first, then show only HR/recruiter/clinic-manager type contacts.
    leads = _sort_active(load_or_seed())
    if args.scan_first:
        leads = scan_hiring_signals(leads, top=args.scan_top or max(args.max_clinics, 25), force_refresh=args.force_scan, report_csv=HIRING_REPORT_CSV)
        save_all(leads)
    leads, summary = apollo_enrich_leads(
        leads,
        missing_email_only=args.missing_email_only,
        max_clinics=args.max_clinics,
        max_credits=args.max_credits,
        contacts_per_clinic=args.contacts_per_clinic,
        search_only=True,
        hiring_contacts_only=True,
        require_hiring_signal=args.require_hiring_signal,
        strict_hiring_owners=not args.allow_clinical_leaders,
        report_csv=APOLLO_REPORT_CSV,
        report_json=APOLLO_REPORT_JSON,
    )
    save_all(leads)
    mode = "strict hiring-owner" if not args.allow_clinical_leaders else "broader hiring-contact"
    print(f"Apollo hiring preview complete ({mode}). Clinics searched: {summary.get('searched_clinics')}; matching contacts found: {summary.get('hiring_candidates_found')}")
    print("No paid enrichment was requested in preview mode.")
    print(f"Preview CSV: {APOLLO_REPORT_CSV}")


def cmd_apollo_hiring_enrich(args) -> None:
    leads = _sort_active(load_or_seed())
    if args.scan_first:
        leads = scan_hiring_signals(leads, top=args.scan_top or max(args.max_clinics, 25), force_refresh=args.force_scan, report_csv=HIRING_REPORT_CSV)
        save_all(leads)
    leads, summary = apollo_enrich_leads(
        leads,
        missing_email_only=args.missing_email_only,
        max_clinics=args.max_clinics,
        max_credits=args.max_credits,
        contacts_per_clinic=args.contacts_per_clinic,
        search_only=False,
        hiring_contacts_only=True,
        require_hiring_signal=args.require_hiring_signal,
        strict_hiring_owners=not args.allow_clinical_leaders,
        report_csv=APOLLO_REPORT_CSV,
        report_json=APOLLO_REPORT_JSON,
    )
    leads = tailor_leads(leads, top=None, force_refresh=False)
    active = save_all(leads)
    write_report(active, REPORT_HTML, REPORT_JSON)
    print("Apollo hiring-contact enrichment complete.")
    print(f"Clinics searched: {summary.get('searched_clinics')}")
    mode = "strict hiring-owner" if not args.allow_clinical_leaders else "broader hiring-contact"
    print(f"Matching contacts found ({mode}): {summary.get('hiring_candidates_found')}")
    print(f"People enrichment requested: {summary.get('enrichment_requested')}")
    print(f"Emails found: {summary.get('emails_found')}")
    print(f"Credits reported by Apollo: {summary.get('credits_consumed')}")
    print(f"Apollo report: {APOLLO_REPORT_CSV}")
    print(f"Hiring report: {HIRING_REPORT_CSV}")
    print(f"Dashboard updated: {REPORT_HTML}")
    if args.open:
        webbrowser.open(REPORT_HTML.resolve().as_uri())

def cmd_gmail_drafts(args) -> None:
    leads = _sort_active(load_or_seed())
    if args.top:
        work = tailor_leads(leads[:args.top], top=None, force_refresh=False)
        leads = merge_leads(leads, work)
    else:
        leads = tailor_leads(leads, top=None, force_refresh=False)
    leads, created, skipped = create_drafts_for_leads(
        leads,
        queue_path=SEND_QUEUE_CSV,
        top=args.top,
        force=args.force,
        draft_type="initial",
    )
    save_all(leads)
    print(f"Gmail drafts created: {created}; skipped: {skipped}")
    print(f"Approval queue: {SEND_QUEUE_CSV}")
    print("Review the drafts in Gmail. To send later, mark approved_to_send=YES in the queue and run send-approved --confirm-send.")


def cmd_prepare_followups(args) -> None:
    leads = _sort_active(load_or_seed())
    due = leads_due_for_followup(
        leads,
        days_since=args.days_since,
        followup_number=args.followup_number,
        include_all=args.all,
    )
    if args.top:
        due = due[:args.top]
    if not due:
        print("No follow-up drafts due. Use --all to create follow-up drafts anyway.")
        return
    draft_type = "followup1" if args.followup_number == 1 else "followup2"
    leads, created, skipped = create_drafts_for_leads(
        due,
        queue_path=SEND_QUEUE_CSV,
        top=None,
        force=args.force,
        draft_type=draft_type,
    )
    # Merge updated due leads into full list.
    full = merge_leads(load_or_seed(), leads)
    save_all(full)
    print(f"Follow-up Gmail drafts created: {created}; skipped: {skipped}")
    print(f"Approval queue: {SEND_QUEUE_CSV}")


def _sync_sent_from_queue_to_leads() -> None:
    rows = load_queue(SEND_QUEUE_CSV)
    if not rows:
        return
    leads = load_leads_csv(LEADS_CSV)
    by_name = {lead.clinic_name.lower(): lead for lead in leads}
    changed = False
    for row in rows:
        if not row.get("sent_at"):
            continue
        lead = by_name.get(str(row.get("clinic_name") or "").lower())
        if not lead:
            continue
        draft_type = row.get("draft_type") or "initial"
        if draft_type == "initial" and not lead.first_email_sent_at:
            lead.first_email_sent_at = row["sent_at"]
            lead.gmail_message_id = row.get("message_id", "")
            changed = True
        elif draft_type == "followup1" and not lead.followup_1_sent_at:
            lead.followup_1_sent_at = row["sent_at"]
            changed = True
        elif draft_type == "followup2" and not lead.followup_2_sent_at:
            lead.followup_2_sent_at = row["sent_at"]
            changed = True
    if changed:
        save_all(leads)


def cmd_send_approved(args) -> None:
    sent, pending = send_approved_drafts(
        SEND_QUEUE_CSV,
        confirm_send=args.confirm_send,
        daily_limit=args.limit,
    )
    if sent:
        _sync_sent_from_queue_to_leads()
    print(f"Sent: {sent}; pending dry-run count: {pending}")


def cmd_gmail_clear_drafts(args) -> None:
    deleted, pending = delete_queued_drafts(SEND_QUEUE_CSV, confirm_delete=args.confirm_delete)
    if args.confirm_delete:
        leads = load_leads_csv(LEADS_CSV)
        for lead in leads:
            lead.gmail_draft_id = ""
            lead.gmail_draft_created_at = ""
            lead.followup_1_draft_id = ""
            lead.followup_2_draft_id = ""
        save_all(leads)
    print(f"Deleted queued Gmail drafts: {deleted}; dry-run/pending or errors: {pending}")


def cmd_call_queue(args) -> None:
    leads = _sort_active(load_or_seed())
    csv_path, html_path, count = write_call_queue(leads, CALL_QUEUE_CSV, CALL_QUEUE_HTML, top=args.top)
    print(f"Call queue created with {count} lead(s).")
    print(f"CSV:  {csv_path}")
    print(f"HTML: {html_path}")
    if args.open:
        webbrowser.open(html_path.resolve().as_uri())


def cmd_gmail_test(args) -> None:
    from src.externship_gmail import gmail_service
    service = gmail_service()
    profile = service.users().getProfile(userId="me").execute()
    print("Gmail connected.")
    print(f"Email address: {profile.get('emailAddress')}")
    print(f"Draft queue file: {SEND_QUEUE_CSV}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Medical externship outreach CRM for Sample Applicant.")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("init", help="Create/merge seed lead CSV/tracker and filter academy leads.")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("add-lead", help="Add one manual lead.")
    p.add_argument("--name", required=True)
    p.add_argument("--specialty", default="")
    p.add_argument("--city", default="")
    p.add_argument("--website", default="")
    p.add_argument("--contact-page", default="")
    p.add_argument("--phone", default="")
    p.add_argument("--email", default="")
    p.add_argument("--contact-name", default="")
    p.add_argument("--contact-title", default="")
    p.add_argument("--priority", default="medium")
    p.add_argument("--tags", default="manual")
    p.set_defaults(func=cmd_add_lead)

    p = sub.add_parser("filter", help="Remove academy/school/training leads from current CSV.")
    p.set_defaults(func=cmd_filter)

    p = sub.add_parser("discover", help="Use Google Places + NPI + website crawl to discover fresh nearby clinic leads.")
    p.add_argument("--radius-miles", type=float, default=DEFAULT_RADIUS_MILES)
    p.add_argument("--max-leads", type=int, default=DEFAULT_MAX_LEADS)
    p.add_argument("--include-seed", action="store_true", help="Merge new Google leads with starter leads before saving.")
    p.add_argument("--skip-npi", action="store_true")
    p.add_argument("--skip-website-enrich", action="store_true")
    p.set_defaults(func=cmd_discover)

    p = sub.add_parser("npi", help="Run NPI Registry matching on existing leads.")
    p.add_argument("--max-leads", type=int, default=None)
    p.set_defaults(func=cmd_npi)

    p = sub.add_parser("enrich", help="Visit public clinic pages and extract public emails/phones/contact links.")
    p.add_argument("--max-leads", type=int, default=None)
    p.add_argument("--npi", action="store_true", help="Also run NPI Registry matching first.")
    p.set_defaults(func=cmd_enrich)

    p = sub.add_parser("drafts", help="Generate local txt/eml email drafts and call scripts.")
    p.add_argument("--top", type=int, default=None)
    p.set_defaults(func=cmd_drafts)

    p = sub.add_parser("email-preview", help="Create an HTML preview of the improved email bodies before making Gmail drafts.")
    p.add_argument("--top", type=int, default=DEFAULT_TOP)
    p.add_argument("--open", action="store_true")
    p.add_argument("--sender-email", default="", help="Use this to preview helper voice when sending from Sample's Gmail.")
    p.add_argument("--sender-mode", choices=["auto", "candidate", "helper"], default="candidate")
    p.set_defaults(func=cmd_email_preview)


    p = sub.add_parser("hiring-scan", help="Scan clinic/careers pages for active medical-assistant or clinic-support hiring signals.")
    p.add_argument("--top", type=int, default=DEFAULT_TOP)
    p.add_argument("--force-refresh", action="store_true")
    p.add_argument("--open", action="store_true")
    p.set_defaults(func=cmd_hiring_scan)

    p = sub.add_parser("apollo-test", help="Test APOLLO_API_KEY without spending enrichment credits.")
    p.set_defaults(func=cmd_apollo_test)

    p = sub.add_parser("apollo-preview", help="Search Apollo for likely clinic contacts without paid enrichment.")
    p.add_argument("--max-clinics", type=int, default=10)
    p.add_argument("--max-credits", type=int, default=25)
    p.add_argument("--contacts-per-clinic", type=int, default=1)
    p.add_argument("--missing-email-only", action="store_true", default=True)
    p.add_argument("--hiring-contacts-only", action="store_true", default=True, help="Only keep HR/recruiter/clinic manager/operations/placement contacts.")
    p.add_argument("--require-hiring-signal", action="store_true", help="Only search clinics where hiring-scan found active/careers/externship signal.")
    p.set_defaults(func=cmd_apollo_preview)

    p = sub.add_parser("apollo-enrich", help="Use Apollo to find/enrich work emails for clinics missing contact_email. Phones/waterfall remain disabled by env defaults.")
    p.add_argument("--max-clinics", type=int, default=25)
    p.add_argument("--max-credits", type=int, default=25)
    p.add_argument("--contacts-per-clinic", type=int, default=1)
    p.add_argument("--missing-email-only", action="store_true", default=True)
    p.add_argument("--hiring-contacts-only", action="store_true", default=True, help="Only keep HR/recruiter/clinic manager/operations/placement contacts.")
    p.add_argument("--require-hiring-signal", action="store_true", help="Only search clinics where hiring-scan found active/careers/externship signal.")
    p.add_argument("--open", action="store_true")
    p.set_defaults(func=cmd_apollo_enrich)

    p = sub.add_parser("apollo-hiring-preview", help="Strict preview: find likely hiring owners only; no paid enrichment.")
    p.add_argument("--max-clinics", type=int, default=10)
    p.add_argument("--max-credits", type=int, default=25)
    p.add_argument("--contacts-per-clinic", type=int, default=1)
    p.add_argument("--missing-email-only", action="store_true", default=True)
    p.add_argument("--require-hiring-signal", action="store_true", help="Only target clinics where hiring-scan found active/careers/externship signal.")
    p.add_argument("--allow-clinical-leaders", action="store_true", help="Allow medical directors/clinical leaders as fallback contacts. Default is stricter: HR/recruiting, clinic/practice/office managers, operations, or training/placement only.")
    p.add_argument("--scan-first", action="store_true", default=True)
    p.add_argument("--force-scan", action="store_true")
    p.add_argument("--scan-top", type=int, default=None)
    p.set_defaults(func=cmd_apollo_hiring_preview)

    p = sub.add_parser("apollo-hiring-enrich", help="Strict enrichment: enrich likely hiring owners only, email-only, no phone/waterfall.")
    p.add_argument("--max-clinics", type=int, default=10)
    p.add_argument("--max-credits", type=int, default=10)
    p.add_argument("--contacts-per-clinic", type=int, default=1)
    p.add_argument("--missing-email-only", action="store_true", default=True)
    p.add_argument("--require-hiring-signal", action="store_true", help="Only target clinics where hiring-scan found active/careers/externship signal.")
    p.add_argument("--allow-clinical-leaders", action="store_true", help="Allow medical directors/clinical leaders as fallback contacts. Default is stricter: HR/recruiting, clinic/practice/office managers, operations, or training/placement only.")
    p.add_argument("--scan-first", action="store_true", default=True)
    p.add_argument("--force-scan", action="store_true")
    p.add_argument("--scan-top", type=int, default=None)
    p.add_argument("--open", action="store_true")
    p.set_defaults(func=cmd_apollo_hiring_enrich)

    p = sub.add_parser("gmail-test", help="Connect to Gmail API using credentials.json and print the signed-in mailbox.")
    p.set_defaults(func=cmd_gmail_test)

    p = sub.add_parser("gmail-drafts", help="Create Gmail drafts for active leads with public emails. Does not send.")
    p.add_argument("--top", type=int, default=DEFAULT_TOP)
    p.add_argument("--force", action="store_true", help="Create new drafts even if a draft id already exists.")
    p.set_defaults(func=cmd_gmail_drafts)

    p = sub.add_parser("prepare-followups", help="Create Gmail follow-up drafts. Does not send.")
    p.add_argument("--top", type=int, default=DEFAULT_TOP)
    p.add_argument("--days-since", type=int, default=FOLLOWUP_1_DAYS)
    p.add_argument("--followup-number", type=int, choices=[1, 2], default=1)
    p.add_argument("--all", action="store_true", help="Create follow-up drafts for all active emailed leads even if dates are missing.")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_prepare_followups)

    p = sub.add_parser("gmail-clear-drafts", help="Delete queued unsent Gmail drafts so you can regenerate improved copies.")
    p.add_argument("--confirm-delete", action="store_true", help="Actually delete queued unsent Gmail drafts. Without this, dry-run only.")
    p.set_defaults(func=cmd_gmail_clear_drafts)

    p = sub.add_parser("send-approved", help="Send only Gmail drafts manually approved in data/externship_send_queue.csv.")
    p.add_argument("--confirm-send", action="store_true", help="Actually send. Without this, it only prints a dry run.")
    p.add_argument("--limit", type=int, default=None)
    p.set_defaults(func=cmd_send_approved)

    p = sub.add_parser("call-queue", help="Create manual call queue CSV/HTML for leads with phone numbers.")
    p.add_argument("--top", type=int, default=DEFAULT_TOP)
    p.add_argument("--open", action="store_true")
    p.set_defaults(func=cmd_call_queue)

    p = sub.add_parser("tailor", help="Refresh website-specific tailoring and rebuild the dashboard with draft emails.")
    p.add_argument("--top", type=int, default=DEFAULT_TOP)
    p.add_argument("--force-refresh", action="store_true", help="Refetch clinic websites instead of using cached website profiles.")
    p.add_argument("--open", action="store_true")
    p.set_defaults(func=cmd_tailor)

    p = sub.add_parser("report", help="Generate HTML review dashboard with full tailored draft emails.")
    p.add_argument("--open", action="store_true")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("run", help="Run seed + optional discover/enrich + local drafts + report.")
    p.add_argument("--discover", action="store_true", help="Use Google Places discovery before drafting.")
    p.add_argument("--skip-enrich", action="store_true")
    p.add_argument("--skip-npi", action="store_true")
    p.add_argument("--skip-website-enrich", action="store_true")
    p.add_argument("--radius-miles", type=float, default=DEFAULT_RADIUS_MILES)
    p.add_argument("--max-leads", type=int, default=DEFAULT_MAX_LEADS)
    p.add_argument("--top", type=int, default=None)
    p.add_argument("--open", action="store_true")
    p.set_defaults(func=cmd_run, include_seed=True)

    p = sub.add_parser("test-google", help="Test Google API key and Places API New.")
    p.set_defaults(func=cmd_test_google)

    p = sub.add_parser("followups", help="Print follow-ups due from tracker CSV.")
    p.set_defaults(func=cmd_followups)

    parser.set_defaults(func=cmd_run, skip_enrich=False, discover=False, skip_npi=False, skip_website_enrich=False, max_leads=DEFAULT_MAX_LEADS, top=None, open=True, include_seed=True, radius_miles=DEFAULT_RADIUS_MILES)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
