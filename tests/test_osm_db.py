"""OSM ingestion end to end against Postgres, with Overpass replaced by fixtures.

These tests commit (ingestion manages its own transactions), so each one starts by
emptying the tables it touches.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from sqlalchemy import Engine, delete, func, select

from morehere.config import load_city_config
from morehere.db import repo
from morehere.db.seed import seed_sources
from morehere.db.session import session_scope
from morehere.db.tables import DistrictRow, PlaceRow, RawRecordRow
from morehere.models import GeoPoint
from morehere.sources import osm

pytestmark = pytest.mark.db

FIXTURES = Path(__file__).parent / "fixtures"
PLACES = (FIXTURES / "overpass_places.json").read_text(encoding="utf-8")
DISTRICTS = (FIXTURES / "overpass_districts.json").read_text(encoding="utf-8")
CONFIG = load_city_config()
T1 = datetime(2026, 11, 12, 3, 0, tzinfo=UTC)
T2 = datetime(2026, 11, 19, 3, 0, tzinfo=UTC)


def client_returning(*payloads: str) -> httpx.Client:
    queue = list(payloads)
    return httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=queue.pop(0)))
    )


@pytest.fixture
def engine(db_engine: Engine) -> Iterator[Engine]:
    with session_scope(db_engine) as s:
        s.execute(delete(PlaceRow).where(PlaceRow.osm_id.is_not(None)))
        s.execute(delete(DistrictRow))
        s.execute(delete(RawRecordRow).where(RawRecordRow.source_id == osm.SOURCE_ID))
    seed_sources(db_engine)
    yield db_engine


def districts_of(engine: Engine) -> dict[str, str | None]:
    with session_scope(engine) as s:
        return dict(s.execute(select(PlaceRow.place_id, PlaceRow.district)).all())


def test_districts_are_built_from_split_ways_and_respect_holes(engine: Engine) -> None:
    counts = osm.ingest_districts(engine, client_returning(DISTRICTS), CONFIG, now=T1)
    assert counts == {"districts": 2, "unmatched": 1, "missing": 23}
    with session_scope(engine) as s:
        assert repo.district_at(s, GeoPoint(lat=48.137, lon=11.576)) == "Altstadt-Lehel"
        assert repo.district_at(s, GeoPoint(lat=48.150, lon=11.570)) == "Maxvorstadt"
        assert repo.district_at(s, GeoPoint(lat=48.1495, lon=11.564)) is None  # in the hole
        assert repo.district_at(s, GeoPoint(lat=48.300, lon=11.400)) is None  # outside


def test_places_ingest_stores_raw_upserts_and_assigns_districts(engine: Engine) -> None:
    osm.ingest_districts(engine, client_returning(DISTRICTS), CONFIG, now=T1)
    counts = osm.ingest_places(engine, client_returning(PLACES), CONFIG, now=T1)

    assert counts == {
        "places_upserted": 6,
        "skipped_unnamed": 1,
        "skipped_unknown_kind": 1,
        "skipped_no_location": 1,
        "places_with_district": 4,
        "places_not_seen_this_run": 0,
    }
    assert districts_of(engine) == {
        "osm-node-1001": "Altstadt-Lehel",
        "osm-node-1005": "Altstadt-Lehel",
        "osm-way-2001": "Maxvorstadt",
        "osm-way-2002": "Maxvorstadt",
        "osm-relation-3001": None,  # inside Maxvorstadt's hole
        "osm-node-1004": None,  # outside every district
    }
    with session_scope(engine) as s:
        raw = repo.latest_raw_record(s, osm.SOURCE_ID, id_prefix="osm-places-")
        assert raw is not None and raw.payload == PLACES
        place = repo.get_place(s, "osm-node-1001")
        assert place is not None and place.address == "Teststraße 1"


def test_running_twice_is_idempotent(engine: Engine) -> None:
    osm.ingest_places(engine, client_returning(PLACES), CONFIG, now=T1)
    osm.ingest_places(engine, client_returning(PLACES), CONFIG, now=T2)
    with session_scope(engine) as s:
        raw_count = s.scalar(
            select(func.count())
            .select_from(RawRecordRow)
            .where(RawRecordRow.source_id == osm.SOURCE_ID)
        )
        assert raw_count == 1  # identical payload stored once
        assert s.scalar(select(func.count()).select_from(PlaceRow)) == 6
        assert s.scalar(select(func.min(PlaceRow.last_seen_at))) == T2


def test_a_place_missing_from_the_next_run_is_reported_not_deleted(engine: Engine) -> None:
    osm.ingest_places(engine, client_returning(PLACES), CONFIG, now=T1)

    smaller = json.loads(PLACES)
    smaller["elements"] = [e for e in smaller["elements"] if e["id"] != 1005]
    counts = osm.ingest_places(engine, client_returning(json.dumps(smaller)), CONFIG, now=T2)

    assert counts["places_upserted"] == 5
    assert counts["places_not_seen_this_run"] == 1
    with session_scope(engine) as s:
        assert repo.get_place(s, "osm-node-1005") is not None


def test_replay_reparses_the_stored_payload_without_network(engine: Engine) -> None:
    osm.ingest_places(engine, client_returning(PLACES), CONFIG, now=T1)
    with session_scope(engine) as s:
        s.execute(delete(PlaceRow))
    counts = osm.replay_places(engine)
    assert counts["places_upserted"] == 6


def test_places_before_districts_is_harmless(engine: Engine) -> None:
    counts = osm.ingest_places(engine, client_returning(PLACES), CONFIG, now=T1)
    assert counts["places_with_district"] == 0
    osm.ingest_districts(engine, client_returning(DISTRICTS), CONFIG, now=T1)
    assert districts_of(engine)["osm-node-1001"] == "Altstadt-Lehel"
