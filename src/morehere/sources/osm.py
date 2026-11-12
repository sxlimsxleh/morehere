"""OpenStreetMap base layer: places and district boundaries from the Overpass API.

Flow for every run (rule 8, raw payloads are kept):

    fetch (Overpass)  ->  store RawRecord  ->  parse the STORED payload  ->  upsert

Parsing never reads the HTTP response directly, so `replay` can re-run it from the
database without touching the network. OSM data is ODbL: the `osm-overpass` registry
entry carries the attribution the app must show.

Run it:  python -m morehere.sources.osm {places,districts,replay}
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import Engine
from tenacity import RetryCallState, Retrying, retry_if_exception, stop_after_attempt
from tenacity import wait_exponential as _wait_exponential

from morehere.config import CityConfig, load_city_config
from morehere.db import repo
from morehere.db.session import make_engine, session_scope
from morehere.logging import configure_logging, run_context, timed_step
from morehere.models import GeoPoint, Place, PlaceKind, RawRecord, sha256_text
from morehere.text import normalise_whitespace

# Named explicitly: under `python -m`, __name__ is "__main__" and would miss the JSON handler.
log = logging.getLogger("morehere.sources.osm")

SOURCE_ID = "osm-overpass"
OVERPASS_URL = os.environ.get("OVERPASS_URL", "https://overpass-api.de/api/interpreter")
# Overpass asks clients to identify themselves; no personal details here.
USER_AGENT = "morehere/0.1 (Munich third-places scout)"
RETRY_STATUSES = frozenset({429, 502, 503, 504})

# OSM tags we keep on a Place. Everything else is dropped (decision M3: whitelist).
KEPT_TAGS = frozenset(
    {
        "amenity",
        "leisure",
        "office",
        "sport",
        "opening_hours",
        "wheelchair",
        "internet_access",
        "internet_access:fee",
        "website",
        "contact:website",
        "addr:street",
        "addr:housenumber",
        "addr:postcode",
        "addr:city",
    }
)


class OverpassError(RuntimeError):
    """Overpass answered 200 but reports a server-side error (e.g. a query timeout)."""


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


def build_places_query(config: CityConfig, timeout_s: int = 180) -> str:
    b = config.bbox
    bbox = f"{b.south},{b.west},{b.north},{b.east}"
    selectors = "\n".join(f'  nwr["{t.key}"="{t.value}"]({bbox});' for t in config.osm_place_tags)
    # `out center tags`: tags plus one centre point for ways and relations (buildings).
    return f"[out:json][timeout:{timeout_s}];\n(\n{selectors}\n);\nout center tags;"


def build_districts_query(timeout_s: int = 180) -> str:
    # Munich is admin_level 6 (kreisfreie Stadt); its Stadtbezirke are admin_level 9.
    # `out geom` returns every member way with its coordinates, which PostGIS assembles.
    return (
        f"[out:json][timeout:{timeout_s}];\n"
        'area["name"="München"]["boundary"="administrative"]["admin_level"="6"]->.city;\n'
        'rel(area.city)["boundary"="administrative"]["admin_level"="9"];\n'
        "out geom;"
    )


# ---------------------------------------------------------------------------
# Fetching with retries
# ---------------------------------------------------------------------------


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRY_STATUSES
    return isinstance(exc, httpx.TransportError | OverpassError)


_backoff = _wait_exponential(multiplier=2, min=2, max=60)


def _wait(retry_state: RetryCallState) -> float:
    """Honour Retry-After (capped at 2 min) when the server sends one, else back off."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, httpx.HTTPStatusError):
        retry_after = exc.response.headers.get("Retry-After", "")
        if retry_after.isdigit():
            return min(float(retry_after), 120.0)
    return _backoff(retry_state)


def fetch_overpass(
    client: httpx.Client,
    query: str,
    *,
    url: str = OVERPASS_URL,
    max_attempts: int = 4,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """POST a query and return the raw JSON text. Retries 429/5xx, network errors and
    Overpass runtime errors; anything else (e.g. 400 for a bad query) fails at once."""
    for attempt in Retrying(
        retry=retry_if_exception(_is_retryable),
        wait=_wait,
        stop=stop_after_attempt(max_attempts),
        sleep=sleep,
        reraise=True,
        before_sleep=lambda rs: log.warning(
            "osm.fetch.retry",
            extra={"fields": {"attempt": rs.attempt_number, "error": repr(rs.outcome.exception())}},
        ),
    ):
        with attempt:
            response = client.post(url, data={"data": query})
            response.raise_for_status()
            remark = json.loads(response.text).get("remark", "")
            if "error" in remark.lower():
                raise OverpassError(remark)
            return response.text
    raise AssertionError("unreachable: Retrying either returns or raises")


def make_client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=httpx.Timeout(200.0))


def store_payload(engine: Engine, kind: str, payload: str, fetched_at: datetime) -> RawRecord:
    """Save the payload as a RawRecord (deduplicated by hash) and return the stored one."""
    digest = sha256_text(payload)
    record = RawRecord(
        raw_record_id=f"osm-{kind}-{digest[:16]}",
        source_id=SOURCE_ID,
        fetched_at=fetched_at,
        sha256=digest,
        content_type="application/json",
        url=OVERPASS_URL,
        payload=payload,
    )
    with session_scope(engine) as session:
        stored, created = repo.save_raw_record(session, record)
    log.info("osm.raw_stored", extra={"fields": {"kind": kind, "created": created}})
    return stored


# ---------------------------------------------------------------------------
# Parsing places
# ---------------------------------------------------------------------------


def place_kind(tags: dict[str, str]) -> PlaceKind | None:
    """Map OSM tags to our PlaceKind. Order matters: the most specific rule wins."""
    amenity = tags.get("amenity")
    if tags.get("leisure") == "hackerspace":
        return "makerspace"
    if amenity == "library":
        return "library"
    if amenity in {"community_centre", "arts_centre"}:
        return "community_centre"
    if amenity == "coworking_space" or tags.get("office") == "coworking":
        return "coworking"
    if tags.get("sport") == "climbing":
        return "sports"
    if amenity == "cafe":
        return "cafe"
    return None


def _address(tags: dict[str, str]) -> str | None:
    street = tags.get("addr:street")
    number = tags.get("addr:housenumber")
    if street and number:
        return f"{street} {number}"
    return street


def _point(element: dict[str, Any]) -> GeoPoint | None:
    if "lat" in element:  # node
        return GeoPoint(lat=element["lat"], lon=element["lon"])
    if "center" in element:  # way / relation with `out center`
        return GeoPoint(lat=element["center"]["lat"], lon=element["center"]["lon"])
    return None


@dataclass
class ParsedPlaces:
    places: list[Place] = field(default_factory=list)
    skipped_unnamed: int = 0
    skipped_unknown_kind: int = 0
    skipped_no_location: int = 0


def parse_places(payload: str) -> ParsedPlaces:
    result = ParsedPlaces()
    seen: set[str] = set()
    for element in json.loads(payload).get("elements", []):
        tags: dict[str, str] = element.get("tags", {})
        name = normalise_whitespace(tags.get("name", ""))
        if not name:
            result.skipped_unnamed += 1
            continue
        kind = place_kind(tags)
        if kind is None:
            result.skipped_unknown_kind += 1
            continue
        geo = _point(element)
        if geo is None:
            result.skipped_no_location += 1
            continue
        osm_id = f"{element['type']}/{element['id']}"
        if osm_id in seen:  # Overpass can return an element twice via two selectors
            continue
        seen.add(osm_id)
        result.places.append(
            Place(
                place_id=f"osm-{element['type']}-{element['id']}",
                name=name,
                address=_address(tags),
                district=None,  # assigned by location after upsert
                geo=geo,
                osm_id=osm_id,
                kind=kind,
                osm_tags={k: v for k, v in tags.items() if k in KEPT_TAGS},
            )
        )
    return result


# ---------------------------------------------------------------------------
# Parsing districts
# ---------------------------------------------------------------------------


@dataclass
class ParsedDistrict:
    number: int
    name: str
    osm_id: str
    # Each member way as WKT LINESTRING; PostGIS assembles them into polygons.
    ways_wkt: list[str]


def _squash(text: str) -> str:
    return "".join(ch for ch in text.casefold() if ch.isalnum())


def match_district(config: CityConfig, tags: dict[str, str]) -> tuple[int, str] | None:
    """Find the configured district an OSM boundary relation refers to.

    Matches on the name with spaces, hyphens and a leading "Stadtbezirk NN" ignored,
    then falls back to the `ref` tag (the district number).
    """
    name = tags.get("name", "")
    candidate = _squash(name.removeprefix("Stadtbezirk"))
    candidate = candidate.lstrip("0123456789")
    for district in config.districts:
        if _squash(district.name) == candidate:
            return district.number, district.name
    ref = tags.get("ref", "").lstrip("0")
    for district in config.districts:
        if ref and ref == str(district.number):
            return district.number, district.name
    return None


def parse_districts(config: CityConfig, payload: str) -> tuple[list[ParsedDistrict], list[str]]:
    """Returns (matched districts, names of relations that matched no configured district)."""
    districts: list[ParsedDistrict] = []
    unmatched: list[str] = []
    for element in json.loads(payload).get("elements", []):
        if element.get("type") != "relation":
            continue
        tags = element.get("tags", {})
        match = match_district(config, tags)
        if match is None:
            unmatched.append(tags.get("name", f"relation/{element['id']}"))
            continue
        ways = []
        for member in element.get("members", []):
            coords = member.get("geometry") or []
            if member.get("type") == "way" and len(coords) >= 2:
                points = ", ".join(f"{c['lon']} {c['lat']}" for c in coords)
                ways.append(f"LINESTRING({points})")
        districts.append(
            ParsedDistrict(
                number=match[0], name=match[1], osm_id=f"relation/{element['id']}", ways_wkt=ways
            )
        )
    return districts, unmatched


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


def load_places(engine: Engine, record: RawRecord, seen_at: datetime) -> dict[str, int]:
    """Parse a stored places payload and upsert it. Returns counts for the run summary."""
    parsed = parse_places(record.payload)
    with session_scope(engine) as session:
        for place in parsed.places:
            repo.save_place(session, place, seen_at=seen_at)
        districted = repo.assign_districts(session)
        not_seen = repo.count_places_not_seen_since(session, seen_at)
    return {
        "places_upserted": len(parsed.places),
        "skipped_unnamed": parsed.skipped_unnamed,
        "skipped_unknown_kind": parsed.skipped_unknown_kind,
        "skipped_no_location": parsed.skipped_no_location,
        "places_with_district": districted,
        "places_not_seen_this_run": not_seen,
    }


def ingest_places(
    engine: Engine,
    client: httpx.Client,
    config: CityConfig,
    now: datetime | None = None,
    **fetch_kwargs: Any,
) -> dict[str, int]:
    now = now or datetime.now(UTC)
    with timed_step(log, "osm.places.fetch") as step:
        payload = fetch_overpass(client, build_places_query(config), **fetch_kwargs)
        step["bytes"] = len(payload)
    record = store_payload(engine, "places", payload, now)
    with timed_step(log, "osm.places.load", raw_record_id=record.raw_record_id) as step:
        counts = load_places(engine, record, seen_at=now)
        step.update(counts)
    return counts


def ingest_districts(
    engine: Engine, client: httpx.Client, config: CityConfig, now: datetime | None = None,
    **fetch_kwargs: Any,
) -> dict[str, int]:  # fmt: skip
    now = now or datetime.now(UTC)
    with timed_step(log, "osm.districts.fetch") as step:
        payload = fetch_overpass(client, build_districts_query(), **fetch_kwargs)
        step["bytes"] = len(payload)
    record = store_payload(engine, "districts", payload, now)
    with timed_step(log, "osm.districts.load", raw_record_id=record.raw_record_id) as step:
        districts, unmatched = parse_districts(config, record.payload)
        with session_scope(engine) as session:
            for d in districts:
                repo.save_district(session, d.number, d.name, d.osm_id, d.ways_wkt)
            districted = repo.assign_districts(session)
        step.update(
            districts=len(districts),
            unmatched=len(unmatched),
            unmatched_names=unmatched,
            places_with_district=districted,
        )
    missing = {d.number for d in config.districts} - {d.number for d in districts}
    if missing:
        log.warning("osm.districts.missing", extra={"fields": {"numbers": sorted(missing)}})
    return {"districts": len(districts), "unmatched": len(unmatched), "missing": len(missing)}


def replay_places(engine: Engine, now: datetime | None = None) -> dict[str, int]:
    """Re-parse the latest stored places payload without calling Overpass."""
    with session_scope(engine) as session:
        record = repo.latest_raw_record(session, SOURCE_ID, id_prefix="osm-places-")
    if record is None:
        raise SystemExit("No stored OSM places payload yet; run `make osm` first.")
    with timed_step(log, "osm.places.replay", raw_record_id=record.raw_record_id) as step:
        counts = load_places(engine, record, seen_at=now or record.fetched_at)
        step.update(counts)
    return counts


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="OpenStreetMap ingestion for morehere.")
    parser.add_argument("command", choices=["places", "districts", "replay"])
    args = parser.parse_args(argv)

    configure_logging()
    engine = make_engine()
    config = load_city_config()
    with run_context():
        if args.command == "replay":
            counts = replay_places(engine)
        else:
            with make_client() as client:
                ingest = ingest_places if args.command == "places" else ingest_districts
                counts = ingest(engine, client, config)
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    main()
