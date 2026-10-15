from __future__ import annotations

import json
import re
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from src.externship_models import Lead

NPI_URL = "https://npiregistry.cms.hhs.gov/api/"


def _get_json(params: dict[str, str | int], timeout: int = 25) -> dict:
    req = Request(f"{NPI_URL}?{urlencode(params)}", headers={"User-Agent": "ExternshipOutreach/1.0"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except HTTPError as exc:
        return {"error": f"http_{exc.code}", "message": exc.read().decode("utf-8", errors="replace")[:600]}
    except URLError as exc:
        return {"error": "url_error", "message": str(exc.reason)}
    except Exception as exc:
        return {"error": type(exc).__name__, "message": str(exc)}


def _clean_org_name(name: str) -> str:
    value = re.sub(r"\b(inc|llc|corp|corporation|medical group|health center|clinic|urgent care|center|the)\b", " ", name or "", flags=re.I)
    value = re.sub(r"[^A-Za-z0-9\s]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value or name


def _city_state_from_lead(lead: Lead) -> tuple[str, str]:
    city = lead.city or ""
    state = "CA"
    m = re.search(r",\s*([A-Z]{2})\s+\d{5}", lead.address or "")
    if m:
        state = m.group(1)
    if not city and lead.address:
        parts = [p.strip() for p in lead.address.split(",")]
        if len(parts) >= 3:
            city = parts[-3]
    return city, state


def _provider_name(result: dict) -> str:
    basic = result.get("basic") or {}
    if basic.get("organization_name"):
        return str(basic.get("organization_name"))
    parts = [basic.get("first_name"), basic.get("last_name")]
    return " ".join(str(p) for p in parts if p).strip()


def _taxonomy_text(result: dict) -> str:
    values = []
    for tax in result.get("taxonomies") or []:
        desc = str(tax.get("desc") or tax.get("taxonomy_description") or "").strip()
        if desc and desc not in values:
            values.append(desc)
    return "; ".join(values[:6])


def _endpoint_text(result: dict) -> str:
    endpoints = result.get("endpoints") or []
    values = []
    for item in endpoints[:5]:
        endpoint = item.get("endpoint") or ""
        endpoint_type = item.get("endpointType") or item.get("endpoint_type") or ""
        if endpoint:
            values.append(f"{endpoint_type}:{endpoint}" if endpoint_type else endpoint)
    return "; ".join(values)


def enrich_lead_with_npi(lead: Lead, *, limit: int = 5) -> Lead:
    city, state = _city_state_from_lead(lead)
    org = _clean_org_name(lead.clinic_name)
    if not org or not city:
        return lead
    params = {
        "version": "2.1",
        "organization_name": org,
        "city": city,
        "state": state,
        "limit": limit,
    }
    data = _get_json(params)
    if data.get("error"):
        note = f"npi_error:{data.get('error')}"
        lead.notes = (lead.notes + " | " + note).strip(" |")
        return lead
    results = data.get("results") or []
    if not results and " " in org:
        # Try a broader first significant token if organization matching is too strict.
        broad = org.split()[0]
        params["organization_name"] = broad
        data = _get_json(params)
        results = data.get("results") or []
    if not results:
        if "npi_no_match" not in lead.notes:
            lead.notes = (lead.notes + " | npi_no_match").strip(" |")
        return lead
    names = []
    taxonomies = []
    endpoints = []
    for result in results[:limit]:
        name = _provider_name(result)
        tax = _taxonomy_text(result)
        endpoint = _endpoint_text(result)
        if name and name not in names:
            names.append(name)
        if tax:
            taxonomies.append(tax)
        if endpoint:
            endpoints.append(endpoint)
    lead.npi_matched = "yes"
    lead.npi_provider_names = "; ".join(names[:8])
    lead.npi_taxonomies = "; ".join(dict.fromkeys(taxonomies))[:900]
    lead.npi_endpoint = "; ".join(dict.fromkeys(endpoints))[:900]
    lead.enrichment_sources = "; ".join(x for x in [lead.enrichment_sources, "npi_registry"] if x)
    if lead.npi_endpoint and not lead.contact_email and "@" in lead.npi_endpoint:
        m = re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", lead.npi_endpoint, flags=re.I)
        if m:
            lead.contact_email = m.group(0).lower()
    return lead


def enrich_leads_with_npi(leads: list[Lead], *, max_leads: int | None = None, sleep_seconds: float = 0.15) -> list[Lead]:
    selected = leads[:max_leads] if max_leads else leads
    for i, lead in enumerate(selected, start=1):
        print(f"[{i}/{len(selected)}] NPI match: {lead.clinic_name}")
        try:
            enrich_lead_with_npi(lead)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            lead.notes = (lead.notes + f" | npi_error:{type(exc).__name__}:{exc}").strip(" |")
        time.sleep(sleep_seconds)
    return leads
