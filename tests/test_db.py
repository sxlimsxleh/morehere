"""Integration tests against a real Postgres with PostGIS (see conftest.py)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, func, inspect, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from morehere.db import repo
from morehere.db.seed import load_sources, seed_sources
from morehere.db.tables import EvidenceRow, ListingRow, PlaceRow, RawRecordRow, SourceRow, TagRow
from morehere.golden import DEFAULT_RAW_DIR, golden_draft, load_golden
from morehere.models import (
    Evidence,
    GeoPoint,
    Listing,
    Place,
    RawRecord,
    Schedule,
    ScheduleBreak,
    Tag,
    sha256_text,
)

pytestmark = pytest.mark.db

NOW = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
MARIENPLATZ = GeoPoint(lat=48.1374, lon=11.5755)

# Golden source kinds -> the registry entry their real counterparts come from.
REGISTRY_SOURCE = {
    "ical": "ical-public-feeds",
    "email": "email-inbox",
    "web_page": "pasted-links",
    "tip": "community-tips",
    "submission": "organiser-form",
}


def raw_record(file_name: str, source_id: str, raw_record_id: str | None = None) -> RawRecord:
    payload = (DEFAULT_RAW_DIR / file_name).read_text(encoding="utf-8")
    return RawRecord(
        raw_record_id=raw_record_id or file_name,
        source_id=source_id,
        fetched_at=NOW,
        sha256=sha256_text(payload),
        content_type="text/plain",
        payload=payload,
    )


def evidence(text_: str, raw_record_id: str = "01_luma_language_cafe_schwabing.ics") -> Evidence:
    return Evidence(
        source_id="ical-public-feeds",
        raw_record_id=raw_record_id,
        source_text=text_,
        captured_at=NOW,
    )


def place(place_id: str, lat: float, lon: float, kind: str = "cafe") -> Place:
    return Place(place_id=place_id, name=place_id, geo=GeoPoint(lat=lat, lon=lon), kind=kind)  # type: ignore[arg-type]


# --- Schema and migrations ---------------------------------------------------


def test_extensions_are_installed(session: Session) -> None:
    installed = set(session.scalars(text("SELECT extname FROM pg_extension")))
    assert {"postgis", "vector"} <= installed


def test_models_and_migrations_match(db_engine: Engine, alembic_config: Config) -> None:
    # Raises if autogenerate would produce any operation, i.e. tables.py and the
    # migrations have drifted apart.
    command.check(alembic_config)


def test_downgrade_then_upgrade_round_trips(db_engine: Engine, alembic_config: Config) -> None:
    config = alembic_config
    command.downgrade(config, "base")
    assert "listings" not in inspect(db_engine).get_table_names()
    command.upgrade(config, "head")
    assert "listings" in inspect(db_engine).get_table_names()


# --- Source registry ---------------------------------------------------------


def test_seed_is_idempotent(db_engine: Engine) -> None:
    expected = len(load_sources())
    assert seed_sources(db_engine) == expected
    assert seed_sources(db_engine) == expected
    with db_engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(SourceRow)) == expected


def test_every_registry_source_round_trips(session: Session) -> None:
    for source in load_sources():
        assert repo.get_source(session, source.source_id) == source


# --- Raw records -------------------------------------------------------------


def test_identical_raw_record_is_stored_once(session: Session) -> None:
    first, created = repo.save_raw_record(
        session, raw_record("02_newsletter_newcomers_weekly.eml", "email-inbox", "raw-a")
    )
    assert created

    # Same content forwarded again by someone else: new id, same hash.
    again, created_again = repo.save_raw_record(
        session, raw_record("02_newsletter_newcomers_weekly.eml", "email-inbox", "raw-b")
    )
    assert not created_again
    assert again.raw_record_id == "raw-a"
    assert again == first

    count = session.scalar(select(func.count()).select_from(RawRecordRow))
    assert count == 1


def test_same_content_from_another_source_is_kept(session: Session) -> None:
    repo.save_raw_record(session, raw_record("07_run_club_isar.txt", "pasted-links", "raw-a"))
    _, created = repo.save_raw_record(
        session, raw_record("07_run_club_isar.txt", "community-tips", "raw-b")
    )
    assert created


# --- Places ------------------------------------------------------------------


def test_places_near_returns_nearest_first_with_distance(session: Session) -> None:
    repo.save_place(session, place("cafe-near", 48.1390, 11.5770))  # ~200 m
    repo.save_place(session, place("library-mid", 48.1440, 11.5800, kind="library"))  # ~800 m
    repo.save_place(session, place("cafe-pasing", 48.1497, 11.4613))  # ~8.6 km

    within_1km = repo.places_near(session, MARIENPLATZ, radius_m=1000)
    assert [p.place_id for p, _ in within_1km] == ["cafe-near", "library-mid"]
    distances = [d for _, d in within_1km]
    assert distances == sorted(distances)
    assert 150 < distances[0] < 250

    cafes = repo.places_near(session, MARIENPLATZ, radius_m=1000, kind="cafe")
    assert [p.place_id for p, _ in cafes] == ["cafe-near"]


def test_place_round_trips_including_coordinates(session: Session) -> None:
    original = Place(
        place_id="osm-node-1",
        name="Café Lindwurm",
        address="Hohenzollernstraße 41",
        geo=GeoPoint(lat=48.1612, lon=11.5751),
        osm_id="node/1",
        kind="cafe",
        osm_tags={"amenity": "cafe", "internet_access": "wlan"},
    )
    repo.save_place(session, original)
    loaded = repo.get_place(session, "osm-node-1")
    assert loaded is not None
    assert loaded.geo is not None
    assert loaded.geo.lat == pytest.approx(48.1612)
    assert loaded.geo.lon == pytest.approx(11.5751)
    assert loaded.model_copy(update={"geo": original.geo}) == original


def test_place_without_coordinates_is_allowed(session: Session) -> None:
    repo.save_place(session, Place(place_id="tip-place", name="Kino im Hinterhof", kind="other"))
    loaded = repo.get_place(session, "tip-place")
    assert loaded is not None and loaded.geo is None


# --- Listings ----------------------------------------------------------------


def _published_listing(tags: list[Tag]) -> Listing:
    return Listing(
        listing_id="tandem-tuesday",
        title="Tandem Tuesday",
        place_id="cafe-lindwurm",
        category="language_exchange",
        schedule=Schedule(
            rrule="FREQ=WEEKLY;BYDAY=TU",
            dtstart=datetime(2026, 9, 8, 19, 0),
            duration_min=120,
            exdates=[datetime(2026, 12, 29).date()],
            breaks=[ScheduleBreak(label="Sommerpause", months=[8])],
        ),
        language="en+de",
        price_eur=0.0,
        price_period="per_visit",
        come_alone=True,
        beginner_friendly=True,
        group_size="medium",
        first_timer_info="Look for the table with the little flags.",
        tags=tags,
        field_evidence={
            "schedule": evidence("RRULE:FREQ=WEEKLY;BYDAY=TU"),
            "come_alone": evidence("Most people come alone, so don't be shy!"),
        },
        status="published",
        last_verified_at=NOW,
        source_ids=["email-inbox", "ical-public-feeds"],
    )


def _prepare_listing_parents(session: Session) -> None:
    repo.save_place(session, place("cafe-lindwurm", 48.1612, 11.5751))
    repo.save_raw_record(
        session, raw_record("01_luma_language_cafe_schwabing.ics", "ical-public-feeds")
    )


TAGS = [
    Tag(name="come alone OK", evidence=evidence("Most people come alone, so don't be shy!")),
    Tag(name="all levels", evidence=evidence("All levels welcome, from A1 to native.")),
]


def test_listing_round_trips_with_evidence_tags_and_sources(session: Session) -> None:
    _prepare_listing_parents(session)
    original = _published_listing(TAGS)
    repo.save_listing(session, original)
    assert repo.get_listing(session, "tandem-tuesday") == original


def test_saving_again_replaces_children_without_orphans(session: Session) -> None:
    _prepare_listing_parents(session)
    repo.save_listing(session, _published_listing(TAGS))
    repo.save_listing(session, _published_listing(TAGS[:1]))

    loaded = repo.get_listing(session, "tandem-tuesday")
    assert loaded is not None
    assert [t.name for t in loaded.tags] == ["come alone OK"]
    # 2 field evidence + 1 tag; the old version's evidence rows are gone.
    assert session.scalar(select(func.count()).select_from(EvidenceRow)) == 3


def test_database_rejects_a_tag_without_evidence(session: Session) -> None:
    _prepare_listing_parents(session)
    repo.save_listing(session, _published_listing([]))
    with pytest.raises(IntegrityError, match="evidence_id"), session.begin_nested():
        session.execute(
            insert(TagRow).values(listing_id="tandem-tuesday", name="sneaky", evidence_id=None)
        )


def test_database_rejects_publishing_without_a_schedule(session: Session) -> None:
    repo.save_place(session, place("cafe-lindwurm", 48.1612, 11.5751))
    with (
        pytest.raises(IntegrityError, match="published_needs_schedule"),
        session.begin_nested(),
    ):
        session.execute(
            insert(ListingRow).values(
                listing_id="bad",
                title="Bad",
                place_id="cafe-lindwurm",
                category="social",
                status="published",
                schedule=None,
                last_verified_at=NOW,
            )
        )


def test_database_rejects_unknown_status(session: Session) -> None:
    repo.save_place(session, place("cafe-lindwurm", 48.1612, 11.5751))
    with pytest.raises(IntegrityError, match="status_valid"), session.begin_nested():
        session.execute(
            insert(ListingRow).values(
                listing_id="bad", title="Bad", place_id="cafe-lindwurm", category="social",
                status="live",
            )
        )  # fmt: skip


def test_geo_column_has_a_spatial_index(session: Session) -> None:
    indexes = inspect(session.connection()).get_indexes(PlaceRow.__tablename__)
    assert any(ix["name"] == "ix_places_geo" for ix in indexes)


# --- Drafts: the whole golden set goes into the curator queue and back -------


def test_every_golden_draft_round_trips(session: Session) -> None:
    golden = load_golden()
    for golden_file, listing in golden.all_listings():
        source_id = REGISTRY_SOURCE[golden_file.source_kind]
        repo.save_raw_record(session, raw_record(golden_file.file, source_id))
        draft = golden_draft(golden, golden_file, listing)
        draft = draft.model_copy(update={"source_id": source_id})

        draft_id = repo.save_draft(session, draft)
        assert repo.get_draft(session, draft_id) == draft
