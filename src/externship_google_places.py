from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import ssl

try:
    import requests  # type: ignore
except Exception:
    requests = None

try:
    import certifi  # type: ignore
except Exception:
    certifi = None

from src.externship_models import Lead
from src.externship_config import (
    DEFAULT_DISCOVERY_CENTERS,
    DEFAULT_MAX_LEADS,
    DEFAULT_RADIUS_MILES,
    DEFAULT_SEARCH_QUERIES,
    ROOT,
    get_env,
)

GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
TEXT_SEARCH_NEW_URL = "https://places.googleapis.com/v1/places:searchText"
NEARBY_SEARCH_NEW_URL = "https://places.googleapis.com/v1/places:searchNearby"
DEBUG_PATH = ROOT / "data" / "externship_google_debug.json"

# Keep the mask outreach-focused. Phone/website are useful and intentional here.
PLACES_FIELD_MASK = ",".join([
    "places.id",
    "places.displayName",
    "places.formattedAddress",
    "places.location",
    "places.nationalPhoneNumber",
    "places.internationalPhoneNumber",
    "places.websiteUri",
    "places.googleMapsUri",
    "places.primaryType",
    "places.types",
    "places.businessStatus",
])

# Smaller fallback mask. If the key can query Places but a field is blocked/billed
# unexpectedly, this still proves discovery works and saves leads for later enrichment.
BASIC_FIELD_MASK = ",".join([
    "places.id",
    "places.displayName",
    "places.formattedAddress",
    "places.location",
    "places.googleMapsUri",
    "places.primaryType",
    "places.types",
    "places.businessStatus",
])

NEARBY_TYPES = [
    "doctor",
    "hospital",
    "dentist",
    "physiotherapist",
]

# Hard-coded Bay Area centers avoid wasting Google calls on geocoding and keep
# discovery working even when the local Python SSL store breaks Geocoding.
KNOWN_CENTER_COORDS: dict[str, tuple[float, float]] = {
    "berkeley": (37.8715, -122.2730),
    "berkeley, ca": (37.8715, -122.2730),
    "berkeley, ca 94704": (37.8665, -122.2605),
    "oakland": (37.8044, -122.2712),
    "oakland, ca": (37.8044, -122.2712),
    "san francisco": (37.7749, -122.4194),
    "san francisco, ca": (37.7749, -122.4194),
    "walnut creek": (37.9101, -122.0652),
    "walnut creek, ca": (37.9101, -122.0652),
    "san leandro": (37.7249, -122.1561),
    "san leandro, ca": (37.7249, -122.1561),
    "hayward": (37.6688, -122.0808),
    "hayward, ca": (37.6688, -122.0808),
}

def _known_center(address: str) -> tuple[float | None, float | None]:
    key = " ".join(str(address or "").lower().replace(",", " ").split())
    variants = {
        "berkeley ca 94704": "berkeley, ca 94704",
        "berkeley ca": "berkeley, ca",
        "oakland ca": "oakland, ca",
        "san francisco ca": "san francisco, ca",
        "walnut creek ca": "walnut creek, ca",
        "san leandro ca": "san leandro, ca",
        "hayward ca": "hayward, ca",
    }
    mapped = variants.get(key, key)
    value = KNOWN_CENTER_COORDS.get(mapped)
    if value:
        return value
    return None, None


def _api_key() -> str:
    return get_env("GOOGLE_MAPS_API_KEY")


def _write_debug(events: list[dict[str, Any]]) -> None:
    try:
        DEBUG_PATH.parent.mkdir(parents=True, exist_ok=True)
        DEBUG_PATH.write_text(json.dumps(events[-200:], indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _ssl_context():
    # Mac framework Python frequently fails urllib HTTPS with CERTIFICATE_VERIFY_FAILED.
    # Prefer certifi when present, then fall back to default verification.
    try:
        if certifi is not None:
            return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        pass
    try:
        return ssl.create_default_context()
    except Exception:
        return None


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: int = 30) -> dict[str, Any]:
    # Prefer requests because it ships its own CA handling via certifi in most venvs.
    if requests is not None:
        try:
            resp = requests.post(url, json=payload, headers={"Content-Type": "application/json", **headers}, timeout=timeout)
            text = resp.text or ""
            if resp.status_code >= 400:
                return {"error": {"code": resp.status_code, "message": text[:3000]}}
            return resp.json() if text else {}
        except Exception as exc:
            # Fall through to urllib after recording enough detail for debugging.
            requests_error = f"requests_error:{type(exc).__name__}:{exc}"
        else:
            requests_error = ""
    else:
        requests_error = "requests_not_installed"

    data = json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        kwargs = {"timeout": timeout}
        ctx = _ssl_context()
        if ctx is not None:
            kwargs["context"] = ctx
        with urlopen(req, **kwargs) as resp:  # type: ignore[arg-type]
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {}
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {"error": {"code": exc.code, "message": body[:3000], "requests_error": requests_error}}
    except URLError as exc:
        return {"error": {"message": f"url_error:{exc.reason}", "requests_error": requests_error}}
    except Exception as exc:
        return {"error": {"message": f"error:{type(exc).__name__}:{exc}", "requests_error": requests_error}}


def _get_json(url: str, params: dict[str, Any], timeout: int = 30) -> dict[str, Any]:
    full_url = f"{url}?{urlencode(params)}"
    if requests is not None:
        try:
            resp = requests.get(url, params=params, timeout=timeout, headers={"User-Agent": "ExternshipOutreach/1.0"})
            text = resp.text or ""
            if resp.status_code >= 400:
                return {"status": f"HTTP_{resp.status_code}", "error_message": text[:3000]}
            return resp.json() if text else {}
        except Exception as exc:
            requests_error = f"requests_error:{type(exc).__name__}:{exc}"
        else:
            requests_error = ""
    else:
        requests_error = "requests_not_installed"

    req = Request(full_url, headers={"User-Agent": "ExternshipOutreach/1.0"})
    try:
        kwargs = {"timeout": timeout}
        ctx = _ssl_context()
        if ctx is not None:
            kwargs["context"] = ctx
        with urlopen(req, **kwargs) as resp:  # type: ignore[arg-type]
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {}
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {"status": f"HTTP_{exc.code}", "error_message": body[:3000], "requests_error": requests_error}
    except URLError as exc:
        return {"status": "URL_ERROR", "error_message": str(exc.reason), "requests_error": requests_error}
    except Exception as exc:
        return {"status": "ERROR", "error_message": f"{type(exc).__name__}:{exc}", "requests_error": requests_error}

def geocode_address(address: str) -> tuple[float | None, float | None, str]:
    known_lat, known_lng = _known_center(address)
    if known_lat is not None and known_lng is not None:
        return known_lat, known_lng, "ok_known_center"

    key = _api_key()
    if not key:
        return None, None, "missing_google_maps_api_key"
    data = _get_json(GEOCODE_URL, {"address": address, "key": key})
    if data.get("status") != "OK":
        detail = data.get("error_message") or data.get("requests_error") or "failed"
        return None, None, f"geocode_{data.get('status') or detail}:{detail}"[:260]
    results = data.get("results") or []
    if not results:
        return None, None, "geocode_no_results"
    loc = (((results[0] or {}).get("geometry") or {}).get("location") or {})
    try:
        return float(loc.get("lat")), float(loc.get("lng")), "ok"
    except Exception:
        return None, None, "geocode_bad_location"


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 3958.7613
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _city_from_address(address: str) -> str:
    parts = [p.strip() for p in (address or "").split(",") if p.strip()]
    if len(parts) >= 3:
        return parts[-3]
    if len(parts) >= 2:
        return parts[0]
    return ""


def _tags_from_place(place: dict[str, Any], query: str) -> str:
    values: list[str] = []
    for value in [query, place.get("primaryType")]:
        if value:
            text = str(value).replace("_", " ")
            if text not in values:
                values.append(text)
    for value in place.get("types") or []:
        text = str(value).replace("_", " ")
        if text not in values:
            values.append(text)
    return ",".join(values[:12])


def _business_is_open(place: dict[str, Any]) -> bool:
    status = str(place.get("businessStatus") or "").upper()
    return status not in {"CLOSED_PERMANENTLY", "CLOSED_TEMPORARILY"}


def place_to_lead(place: dict[str, Any], *, query: str, center_name: str, center_lat: float, center_lng: float) -> Lead | None:
    if not _business_is_open(place):
        return None
    name = ((place.get("displayName") or {}).get("text") or "").strip()
    if not name:
        return None
    loc = place.get("location") or {}
    lat = loc.get("latitude")
    lng = loc.get("longitude")
    distance = ""
    try:
        if lat is not None and lng is not None:
            distance = f"{haversine_miles(center_lat, center_lng, float(lat), float(lng)):.1f}"
    except Exception:
        distance = ""
    address = place.get("formattedAddress") or ""
    website = place.get("websiteUri") or ""
    domain_note = ""
    try:
        if website:
            domain_note = urlparse(website).netloc.lower().replace("www.", "")
    except Exception:
        pass
    specialty = str(place.get("primaryType") or query).replace("_", " ")
    source_note = f"Google Places New: {query}; center={center_name}"
    if domain_note:
        source_note += f"; domain={domain_note}"
    phone = place.get("nationalPhoneNumber") or place.get("internationalPhoneNumber") or ""
    return Lead(
        clinic_name=name,
        specialty=specialty,
        city=_city_from_address(address),
        address=address,
        website=website,
        main_phone=phone,
        source_url=place.get("googleMapsUri") or website,
        source_note=source_note,
        priority="medium",
        tags=_tags_from_place(place, query),
        google_place_id=place.get("id") or "",
        google_maps_url=place.get("googleMapsUri") or "",
        latitude=str(lat or ""),
        longitude=str(lng or ""),
        distance_miles=distance,
        discovery_source="google_places_new",
        enrichment_sources="google_places_new",
    )


def _places_headers(field_mask: str) -> dict[str, str]:
    return {"X-Goog-Api-Key": _api_key(), "X-Goog-FieldMask": field_mask}


def _error_message(data: dict[str, Any]) -> str:
    if not data.get("error"):
        return ""
    err = data.get("error") or {}
    msg = str(err.get("message") or err.get("code") or "unknown error")
    # Condense noisy JSON error payloads for terminal readability.
    msg = msg.replace("\\n", " ")
    return msg[:900]


def search_places_text(
    *,
    query: str,
    center_lat: float,
    center_lng: float,
    radius_miles: float,
    center_name: str,
    max_results: int = 20,
    debug_events: list[dict[str, Any]] | None = None,
) -> tuple[list[Lead], str]:
    key = _api_key()
    if not key:
        return [], "missing_google_maps_api_key"
    radius_meters = max(1000, min(int(radius_miles * 1609.344), 50000))
    payload = {
        "textQuery": query,
        "maxResultCount": max(1, min(max_results, 20)),
        "locationBias": {
            "circle": {
                "center": {"latitude": center_lat, "longitude": center_lng},
                "radius": radius_meters,
            }
        },
    }
    data = _post_json(TEXT_SEARCH_NEW_URL, payload, _places_headers(PLACES_FIELD_MASK))
    if data.get("error"):
        # Retry with a basic mask so field/SKU issues do not hide discovery entirely.
        first_error = _error_message(data)
        basic = _post_json(TEXT_SEARCH_NEW_URL, payload, _places_headers(BASIC_FIELD_MASK))
        if basic.get("error"):
            msg = _error_message(basic) or first_error
            if debug_events is not None:
                debug_events.append({"method": "text", "query": query, "center": center_name, "error": msg, "first_error": first_error})
            return [], f"places_error:{msg}"
        data = basic
        status = f"ok_basic_fields_after_error:{first_error[:160]}"
    else:
        status = "ok"
    leads: list[Lead] = []
    for place in data.get("places") or []:
        lead = place_to_lead(place, query=query, center_name=center_name, center_lat=center_lat, center_lng=center_lng)
        if lead:
            leads.append(lead)
    if debug_events is not None:
        debug_events.append({"method": "text", "query": query, "center": center_name, "count": len(leads), "status": status})
    return leads, status


def search_places_nearby(
    *,
    included_type: str,
    center_lat: float,
    center_lng: float,
    radius_miles: float,
    center_name: str,
    max_results: int = 20,
    debug_events: list[dict[str, Any]] | None = None,
) -> tuple[list[Lead], str]:
    radius_meters = max(1000, min(int(radius_miles * 1609.344), 50000))
    payload = {
        "includedTypes": [included_type],
        "maxResultCount": max(1, min(max_results, 20)),
        "locationRestriction": {
            "circle": {
                "center": {"latitude": center_lat, "longitude": center_lng},
                "radius": radius_meters,
            }
        },
    }
    data = _post_json(NEARBY_SEARCH_NEW_URL, payload, _places_headers(PLACES_FIELD_MASK))
    if data.get("error"):
        first_error = _error_message(data)
        basic = _post_json(NEARBY_SEARCH_NEW_URL, payload, _places_headers(BASIC_FIELD_MASK))
        if basic.get("error"):
            msg = _error_message(basic) or first_error
            if debug_events is not None:
                debug_events.append({"method": "nearby", "type": included_type, "center": center_name, "error": msg, "first_error": first_error})
            return [], f"nearby_error:{msg}"
        data = basic
        status = f"ok_basic_fields_after_error:{first_error[:160]}"
    else:
        status = "ok"
    leads: list[Lead] = []
    for place in data.get("places") or []:
        lead = place_to_lead(place, query=included_type, center_name=center_name, center_lat=center_lat, center_lng=center_lng)
        if lead:
            leads.append(lead)
    if debug_events is not None:
        debug_events.append({"method": "nearby", "type": included_type, "center": center_name, "count": len(leads), "status": status})
    return leads, status


def _dedupe_key(lead: Lead) -> str:
    for value in [lead.google_place_id, lead.website, lead.source_url, f"{lead.clinic_name}|{lead.address}"]:
        value = str(value or "").strip().lower()
        if value:
            return value
    return str(lead.clinic_name or "").strip().lower()


def discover_google_places(
    *,
    radius_miles: float | None = None,
    max_leads: int | None = None,
    queries: list[str] | None = None,
    centers: list[tuple[str, str]] | None = None,
    sleep_seconds: float = 0.15,
) -> list[Lead]:
    radius_miles = radius_miles or DEFAULT_RADIUS_MILES
    max_leads = max_leads or DEFAULT_MAX_LEADS
    queries = queries or DEFAULT_SEARCH_QUERIES
    centers = centers or DEFAULT_DISCOVERY_CENTERS

    seen: set[str] = set()
    results: list[Lead] = []
    debug_events: list[dict[str, Any]] = []
    print(f"Google Places discovery: radius={radius_miles} miles, target leads={max_leads}")

    if not _api_key():
        print("  ! GOOGLE_MAPS_API_KEY is missing from .env")
        _write_debug([{"error": "missing_google_maps_api_key"}])
        return []

    for center_name, center_address in centers:
        lat, lng, status = geocode_address(center_address)
        if lat is None or lng is None:
            print(f"  ! Could not geocode {center_address}: {status}")
            debug_events.append({"method": "geocode", "center": center_name, "address": center_address, "status": status})
            continue
        print(f"  Center: {center_name} ({lat:.5f}, {lng:.5f})")

        # Text search first because it can find clinics by phrase and returns strong names/domains.
        for base_query in queries:
            if len(results) >= max_leads:
                break
            # Make the text query explicit about the location. This improves results vs.
            # relying only on locationBias for some Google projects/regions.
            query_variants = [base_query, f"{base_query} near {center_address}"]
            for query in query_variants:
                if len(results) >= max_leads:
                    break
                leads, st = search_places_text(
                    query=query,
                    center_lat=lat,
                    center_lng=lng,
                    radius_miles=radius_miles,
                    center_name=center_name,
                    max_results=min(20, max_leads - len(results)),
                    debug_events=debug_events,
                )
                if st.startswith("ok"):
                    print(f"    text: {query}: {len(leads)} result(s)")
                else:
                    print(f"    ! text: {query}: {st}")
                for lead in leads:
                    key = _dedupe_key(lead)
                    if key in seen:
                        continue
                    seen.add(key)
                    results.append(lead)
                    if len(results) >= max_leads:
                        break
                time.sleep(sleep_seconds)

        # Nearby search fallback/booster. This often returns real offices even when text
        # search is sparse or query phrasing is too narrow.
        for included_type in NEARBY_TYPES:
            if len(results) >= max_leads:
                break
            leads, st = search_places_nearby(
                included_type=included_type,
                center_lat=lat,
                center_lng=lng,
                radius_miles=radius_miles,
                center_name=center_name,
                max_results=min(20, max_leads - len(results)),
                debug_events=debug_events,
            )
            if st.startswith("ok"):
                print(f"    nearby: {included_type}: {len(leads)} result(s)")
            else:
                print(f"    ! nearby: {included_type}: {st}")
            for lead in leads:
                key = _dedupe_key(lead)
                if key in seen:
                    continue
                seen.add(key)
                results.append(lead)
                if len(results) >= max_leads:
                    break
            time.sleep(sleep_seconds)

        if len(results) >= max_leads:
            break

    _write_debug(debug_events)
    print(f"Google Places discovery produced {len(results)} unique lead(s).")
    print(f"Google debug log: {DEBUG_PATH}")
    return results


def test_google_places() -> int:
    """Small diagnostic used by `python externship_outreach.py test-google`."""
    print("Google Places diagnostic")
    key = _api_key()
    print(f"  key loaded: {bool(key)}")
    if not key:
        print("  Add GOOGLE_MAPS_API_KEY to .env first.")
        return 2
    lat, lng, status = geocode_address("Berkeley, CA 94704")
    print(f"  geocode Berkeley: {status} {lat} {lng}")
    if lat is None or lng is None:
        _write_debug([{"method": "geocode", "address": "Berkeley, CA 94704", "status": status}])
        print(f"  Debug written to: {DEBUG_PATH}")
        return 3
    events: list[dict[str, Any]] = []
    leads, st = search_places_text(
        query="primary care clinic near Berkeley CA",
        center_lat=lat,
        center_lng=lng,
        radius_miles=10,
        center_name="Berkeley",
        max_results=5,
        debug_events=events,
    )
    print(f"  text search status: {st}")
    print(f"  text search leads: {len(leads)}")
    for lead in leads[:5]:
        print(f"   - {lead.clinic_name} | {lead.main_phone or 'no phone'} | {lead.website or lead.google_maps_url}")
    if not leads:
        print(f"  Debug written to: {DEBUG_PATH}")
        _write_debug(events)
        return 4
    _write_debug(events)
    return 0
