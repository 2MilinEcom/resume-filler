from __future__ import annotations

import html
import json
from pathlib import Path
from urllib.parse import quote

from src.externship_models import Lead
from src.externship_email_writer import choose_recipient, subject_for_lead, body_for_lead, clean_filename
from src.externship_contact_finder import score_lead
from src.externship_filters import active_leads, excluded_leads
from src.externship_profile import SAMPLE_PROFILE
from src.externship_tailor import tailoring_lines_for_lead


def mailto_for(lead: Lead) -> str:
    to = choose_recipient(lead)
    subject = subject_for_lead(lead)
    body = body_for_lead(lead, sender_mode="candidate")
    return f"mailto:{quote(to)}?subject={quote(subject)}&body={quote(body)}"


def draft_links(lead: Lead) -> str:
    stem = clean_filename(f"{lead.clinic_name}_{lead.city}")
    base = f"../drafts/externship/{quote(stem)}"
    return (
        f'<a href="{base}_email.txt" target="_blank">txt</a> '
        f'<a href="{base}_followup.txt" target="_blank">follow-up</a> '
        f'<a href="{base}.eml" target="_blank">eml</a>'
    )


def _link(url: str, label: str) -> str:
    safe = html.escape(url or "")
    if not safe:
        return ""
    return f'<a href="{safe}" target="_blank" rel="noopener noreferrer">{html.escape(label)}</a>'


def lead_row(lead: Lead, index: int) -> str:
    recipient = choose_recipient(lead) or ""
    phone = lead.main_phone or (lead.phones_found[0] if lead.phones_found else "")
    score = score_lead(lead)
    priority = html.escape(lead.priority or "")
    tags = html.escape(lead.tags or "")
    source = lead.source_url or lead.google_maps_url or ""
    source_link = _link(source, "source")
    website = lead.website or lead.contact_page or ""
    site_link = _link(website, "website")
    maps_link = _link(lead.google_maps_url or "", "map")
    email_link = f'<a href="{mailto_for(lead)}">mailto</a>' if recipient else "find email / call first"
    draft_anchor = f"draft-{index}"
    gmail = ""
    if lead.gmail_draft_id:
        gmail = f"<br><span class='muted'>Gmail draft: {html.escape(lead.gmail_draft_id)}</span>"
    call = f'<a href="tel:{html.escape(phone)}">{html.escape(phone)}</a>' if phone else ""
    notes = html.escape(lead.source_note or lead.notes or "")
    apollo_bits = []
    if getattr(lead, "apollo_contact_email", ""):
        apollo_bits.append("Apollo email: " + html.escape(lead.apollo_contact_email))
    if getattr(lead, "apollo_contact_name", "") or getattr(lead, "apollo_contact_title", ""):
        apollo_bits.append("Apollo contact: " + html.escape(" - ".join(x for x in [lead.apollo_contact_name, lead.apollo_contact_title] if x)))
    if getattr(lead, "apollo_contact_fit", ""):
        apollo_bits.append("Apollo fit: " + html.escape(lead.apollo_contact_fit))
    if getattr(lead, "apollo_hiring_reason", ""):
        apollo_bits.append("Reason: " + html.escape(lead.apollo_hiring_reason[:180]))
    if getattr(lead, "apollo_candidates_found", ""):
        apollo_bits.append("Apollo hiring candidates: " + html.escape(lead.apollo_candidates_found))
    if getattr(lead, "apollo_notes", ""):
        apollo_bits.append("Apollo notes: " + html.escape(lead.apollo_notes[:180]))
    apollo_text = "<br>".join(apollo_bits)
    hiring_bits = []
    if getattr(lead, "hiring_signal_status", ""):
        hiring_bits.append("Hiring signal: " + html.escape(lead.hiring_signal_status))
    if getattr(lead, "hiring_signal_title", ""):
        hiring_bits.append("Role/signal: " + html.escape(lead.hiring_signal_title))
    if getattr(lead, "hiring_signal_url", ""):
        hiring_bits.append(_link(lead.hiring_signal_url, "hiring/careers page"))
    if getattr(lead, "hiring_signal_summary", ""):
        hiring_bits.append(html.escape(lead.hiring_signal_summary[:220]))
    hiring_text = "<br>".join(hiring_bits)
    npi = ""
    if lead.npi_matched == "yes":
        npi = f"<b>NPI matched</b><br><span class='muted'>{html.escape(lead.npi_provider_names or '')}</span>"
    elif "npi_no_match" in (lead.notes or ""):
        npi = "<span class='muted'>NPI: no close org match</span>"
    distance = f"<br><span class='muted'>{html.escape(lead.distance_miles)} mi from search center</span>" if lead.distance_miles else ""
    found = []
    if lead.emails_found:
        found.append("emails: " + html.escape(", ".join(lead.emails_found[:3])))
    if lead.phones_found:
        found.append("phones: " + html.escape(", ".join(lead.phones_found[:3])))
    found_text = "<br>".join(found)
    grade = html.escape(lead.outreach_grade or "")
    services = html.escape(lead.site_services or "")
    return f"""
    <tr>
      <td>{index}</td>
      <td><b>{html.escape(lead.clinic_name)}</b><br><span class="muted">{html.escape(lead.specialty)}</span>{distance}<br><a href="#{draft_anchor}">view tailored draft</a></td>
      <td>{html.escape(lead.city)}<br><span class="muted">{html.escape(lead.address)}</span></td>
      <td>{html.escape(lead.contact_name)}<br><span class="muted">{html.escape(lead.contact_title)}</span><br>{npi}<br><span class="muted">{apollo_text}</span></td>
      <td>{html.escape(recipient)}<br>{email_link} | {draft_links(lead)}{gmail}<br><span class="muted">{found_text}</span></td>
      <td>{call}</td>
      <td>{site_link}<br>{maps_link}<br>{source_link}</td>
      <td>{score}<br><span class="badge">{priority}</span> <span class="badge">{grade}</span><br><span class="muted">{services or tags}</span></td>
      <td>{notes}<br><span class="muted">{hiring_text}</span></td>
      <td><input type="checkbox"> emailed<br><input type="checkbox"> called<br><input type="checkbox"> follow-up</td>
    </tr>
    """


def draft_card(lead: Lead, index: int) -> str:
    to = choose_recipient(lead) or "[no public email found - call first or use public contact path]"
    subject = subject_for_lead(lead)
    initial = body_for_lead(lead, sender_mode="candidate")
    followup = body_for_lead(lead, followup=True, sender_mode="candidate")
    lines = tailoring_lines_for_lead(lead)
    website = lead.website or lead.contact_page or lead.source_url or lead.google_maps_url or ""
    website_link = _link(website, website or "website") if website else "[no website captured]"
    source_note = lines.get("source_note") or lead.website_evidence or "No website evidence captured yet. Run: python externship_outreach.py tailor --top 60 --force-refresh"
    services = lines.get("services") or lead.site_services or "inferred from clinic name / lead data"
    tasks = lines.get("tasks") or lead.tailored_tasks or ""
    anchor = f"draft-{index}"
    initial_id = f"initial-{index}"
    followup_id = f"followup-{index}"
    return f"""
<section class="draft-card" id="{anchor}">
  <div class="draft-head">
    <div>
      <h3>{index}. {html.escape(lead.clinic_name)}</h3>
      <p class="muted">Website/source: {website_link}</p>
    </div>
    <div class="pill">{html.escape(lead.city or 'Bay Area')}</div>
  </div>
  <div class="tailor-box">
    <b>Tailoring used:</b> {html.escape(services)}<br>
    <b>Interested in learning/helping with:</b> {html.escape(tasks)}<br>
    <b>Evidence:</b> {html.escape(source_note)}
  </div>
  <div class="tailor-box hiring-box">
    <b>Hiring signal:</b> {html.escape(getattr(lead, "hiring_signal_status", "") or "not scanned")}<br>
    <b>Role/careers signal:</b> {html.escape(getattr(lead, "hiring_signal_title", "") or "")}<br>
    <b>Hiring page:</b> {_link(getattr(lead, "hiring_signal_url", ""), "open hiring/careers page") if getattr(lead, "hiring_signal_url", "") else ""}<br>
    <b>Summary:</b> {html.escape(getattr(lead, "hiring_signal_summary", "") or "Run hiring-scan to check whether this clinic has MA/clinic-support openings.")}
  </div>
  <p><b>To:</b> {html.escape(to)}<br><b>Subject:</b> {html.escape(subject)}</p>
  <div class="draft-actions">
    <button onclick="copyText('{initial_id}')">Copy initial email</button>
    <button onclick="copyText('{followup_id}')">Copy follow-up</button>
  </div>
  <details open>
    <summary>Initial cold email</summary>
    <pre id="{initial_id}">{html.escape(initial)}</pre>
  </details>
  <details>
    <summary>Follow-up email</summary>
    <pre id="{followup_id}">{html.escape(followup)}</pre>
  </details>
</section>
"""


def excluded_row(lead: Lead, index: int) -> str:
    return f"""
    <tr>
      <td>{index}</td>
      <td>{html.escape(lead.clinic_name)}</td>
      <td>{html.escape(lead.city)}</td>
      <td>{html.escape(lead.website or lead.source_url or '')}</td>
      <td>{html.escape(lead.excluded_reason or 'excluded')}</td>
    </tr>
    """


def write_report(leads: list[Lead], report_path: Path, json_path: Path) -> None:
    active = sorted(active_leads(leads), key=score_lead, reverse=True)
    excluded = excluded_leads(leads)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps([lead.to_dict() for lead in active], indent=2, ensure_ascii=False), encoding="utf-8")
    rows = "\n".join(lead_row(lead, i) for i, lead in enumerate(active, 1))
    draft_cards = "\n".join(draft_card(lead, i) for i, lead in enumerate(active, 1))
    excluded_rows = "\n".join(excluded_row(lead, i) for i, lead in enumerate(excluded, 1))
    p = SAMPLE_PROFILE
    report_path.write_text(f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Sample Externship Outreach Dashboard</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif; margin: 24px; color: #1f2937; background:#f9fafb; }}
h1 {{ margin-bottom: 0; }}
h2 {{ margin-top: 30px; }}
.summary {{ background: #f3f4f6; border-radius: 12px; padding: 16px; margin: 16px 0 24px; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; margin-bottom: 28px; background:white; }}
th, td {{ border: 1px solid #e5e7eb; padding: 8px; vertical-align: top; }}
th {{ background: #111827; color: white; position: sticky; top: 0; }}
tr:nth-child(even) {{ background: #fafafa; }}
.badge, .pill {{ display: inline-block; background: #dbeafe; padding: 2px 6px; border-radius: 6px; }}
.muted {{ color: #6b7280; font-size: 12px; }}
a {{ color: #2563eb; }}
.warning {{ background: #fff7ed; border: 1px solid #fed7aa; padding: 10px; border-radius: 10px; }}
.draft-card {{ background:#fff; border:1px solid #d1d5db; border-radius:14px; padding:18px 20px; margin:0 0 18px; box-shadow:0 1px 3px rgba(0,0,0,.06); }}
.draft-head {{ display:flex; align-items:flex-start; justify-content:space-between; gap:16px; }}
.draft-head h3 {{ margin:0 0 4px; }}
.tailor-box {{ background:#eef6ff; border:1px solid #bfdbfe; padding:12px; border-radius:10px; margin:12px 0; line-height:1.45; }}
pre {{ white-space:pre-wrap; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size:13px; line-height:1.5; background:#f8fafc; padding:14px; border:1px solid #e5e7eb; border-radius:10px; }}
summary {{ cursor:pointer; font-weight:700; margin:10px 0; }}
button {{ border:1px solid #2563eb; background:#2563eb; color:white; border-radius:8px; padding:6px 10px; cursor:pointer; margin-right:8px; }}
button:hover {{ background:#1d4ed8; }}
.hiring-box {{ background:#ecfdf5; border-color:#bbf7d0; }}
.nav {{ margin: 12px 0 22px; }}
.nav a {{ margin-right:12px; }}
</style>
<script>
function copyText(id) {{
  const el = document.getElementById(id);
  if (!el) return;
  navigator.clipboard.writeText(el.textContent).then(() => alert('Copied draft email'));
}}
</script>
</head>
<body>
<h1>Sample Externship Outreach Dashboard</h1>
<div class="summary">
  <b>Candidate:</b> {html.escape(p['full_name'])}<br>
  <b>Email:</b> {html.escape(p['email'])}<br>
  <b>Phone:</b> {html.escape(p['phone'])}<br>
  <b>Base:</b> {html.escape(p['base_location'])}; {html.escape(p['commute_limit'])}<br>
  <b>Goal:</b> {html.escape(p['target_externship'])}<br>
  <b>Rules:</b> drafts first; Gmail sending only for rows manually approved in the queue; manual calls only; no contact-form auto-submit.<br>
  <b>Discovery:</b> Google Places API + NPI Registry + website crawler. Academy/school/training leads are filtered out.
</div>
<div class="warning">
  <b>Active leads:</b> {len(active)} &nbsp; | &nbsp; <b>Filtered academy/school leads:</b> {len(excluded)}<br>
  The tailored email cards below are first-person Sample drafts. Review wording, recipient, and fit before sending.<br>
  Apollo fields appear only when you run apollo-preview/apollo-enrich or the stricter apollo-hiring-preview/apollo-hiring-enrich flow. Apollo phone, personal email, and waterfall enrichment are disabled by default.<br>
  Hiring-signal fields appear after <code>python externship_outreach.py hiring-scan --top 60 --open</code>. A hiring signal is not a guarantee, but it separates active/careers-page leads from generic clinic contacts.
</div>
<div class="nav"><a href="#leads">Lead table</a><a href="#drafts">Tailored draft emails</a><a href="#excluded">Filtered-out leads</a></div>
<h2 id="leads">Active Clinic Leads</h2>
<table>
<thead><tr><th>#</th><th>Clinic</th><th>Location</th><th>Contact</th><th>Email / Draft</th><th>Phone</th><th>Links</th><th>Score</th><th>Notes</th><th>Manual Log</th></tr></thead>
<tbody>
{rows}
</tbody>
</table>
<h2 id="drafts">Tailored Draft Emails by Clinic Website</h2>
<p class="muted">Each card shows the clinic-specific draft, the website/service signals used, and copy buttons. These are the bodies that Gmail draft creation uses.</p>
{draft_cards}
<h2 id="excluded">Filtered Out: Academy / School / Training Leads</h2>
<table>
<thead><tr><th>#</th><th>Name</th><th>City</th><th>Website/source</th><th>Reason</th></tr></thead>
<tbody>
{excluded_rows}
</tbody>
</table>
</body>
</html>""", encoding="utf-8")
