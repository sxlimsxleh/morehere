"""iCal parsing, series inference, probing and ingestion."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest
from sqlalchemy import Engine, delete

from morehere.db import repo
from morehere.db.seed import seed_sources
from morehere.db.session import session_scope
from morehere.db.tables import RawRecordRow, SourceRow
from morehere.golden import DEFAULT_RAW_DIR
from morehere.models import Source
from morehere.sources import ical

FIXTURES = Path(__file__).parent / "fixtures"
DATED = (FIXTURES / "ical_dated_events.ics").read_text(encoding="utf-8")
NOW = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)


def raw(name: str) -> str:
    return (DEFAULT_RAW_DIR / name).read_text(encoding="utf-8")


def mock_client(*responses: httpx.Response) -> httpx.Client:
    queue = list(responses)
    return httpx.Client(transport=httpx.MockTransport(lambda _: queue.pop(0)))


# --- Parsing the dataset's .ics files ----------------------------------------


def test_luma_event_with_rrule_becomes_a_schedule() -> None:
    feed = ical.parse_feed(raw("01_luma_language_cafe_schwabing.ics"))
    assert feed.name == "Munich Tandem Collective"
    event = feed.events[0]
    assert event.summary == "Tandem Tuesday – English/German Language Café"
    assert event.location == "Café Lindwurm, Hohenzollernstraße 41, 80801 München"
    schedule = ical.event_schedule(event)
    assert schedule is not None
    assert (schedule.rrule, schedule.dtstart, schedule.duration_min) == (
        "FREQ=WEEKLY;BYDAY=TU",
        datetime(2026, 9, 8, 19, 0),
        120,
    )


def test_exdates_are_read_as_local_dates() -> None:
    schedule = ical.event_schedule(ical.parse_feed(raw("21_ical_pub_quiz_exdates.ics")).events[0])
    assert schedule is not None
    assert schedule.exdates == [date(2026, 12, 23), date(2026, 12, 30)]


def test_every_other_week_rule_passes_through() -> None:
    schedule = ical.event_schedule(ical.parse_feed(raw("19_luma_founders_breakfast.ics")).events[0])
    assert schedule is not None and schedule.rrule == "FREQ=WEEKLY;INTERVAL=2;BYDAY=FR"


def test_non_ical_payload_is_rejected() -> None:
    with pytest.raises(ical.NotICalError):
        ical.parse_feed("<!DOCTYPE html><html>Sign in to Meetup</html>")


# --- Series hidden in dated events (the common real-world case) --------------


def test_infer_series_from_dated_events() -> None:
    series = {s.summary: s for s in ical.infer_series(ical.parse_feed(DATED).events)}
    assert set(series) == {"Language Exchange", "Repair Café", "Coffee Coworking"}
    # UTC times change at the end of DST; local time stays 19:00, so it's one series.
    assert series["Language Exchange"].rrule == "FREQ=WEEKLY;BYDAY=TU"
    assert series["Language Exchange"].occurrences == 5  # the cancelled date is left out
    assert series["Language Exchange"].duration_min == 120
    assert series["Repair Café"].rrule == "FREQ=MONTHLY;BYDAY=3SA"
    assert series["Coffee Coworking"].rrule == "FREQ=WEEKLY;INTERVAL=2;BYDAY=FR"


def test_summary_counts_what_a_feed_offers() -> None:
    summary = ical.summarise(ical.parse_feed(DATED), NOW)
    assert summary["events"] == 18
    assert summary["events_with_rrule"] == 1
    assert summary["inferred_series"] == 3
    assert summary["cancelled"] == 1
    assert summary["skipped_overrides"] == 1
    assert summary["sample_one_offs"] == ["Open Studio", "Startup Pitch Night"]
    assert {r["summary"] for r in summary["recurring"]} == {
        "Board Game Night",
        "Coffee Coworking",
        "Language Exchange",
        "Repair Café",
    }


# --- Probing a URL -----------------------------------------------------------


def test_probe_reports_a_useful_feed() -> None:
    result = ical.probe(mock_client(httpx.Response(200, text=DATED)), "https://x.example/cal.ics")
    assert result["is_ical"] is True
    assert result["inferred_series"] == 3


def test_probe_explains_a_login_wall() -> None:
    # e.g. Meetup's iCal links now answer with an HTML page when you are not logged in
    page = httpx.Response(200, text="<html>Log in</html>", headers={"content-type": "text/html"})
    result = ical.probe(mock_client(page), "https://x.example/events/ical/")
    assert result == {
        "url": "https://x.example/events/ical/",
        "is_ical": False,
        "error": "not an iCalendar document (content-type text/html)",
    }


def test_probe_reports_http_errors() -> None:
    result = ical.probe(mock_client(httpx.Response(404)), "https://x.example/missing.ics")
    assert result["is_ical"] is False and result["error"] == "HTTP 404"


# --- Ingestion from the registry (database) ----------------------------------


@pytest.fixture
def engine(db_engine: Engine) -> Engine:
    with session_scope(db_engine) as s:
        s.execute(delete(RawRecordRow).where(RawRecordRow.raw_record_id.startswith("ical-")))
        s.execute(delete(SourceRow).where(SourceRow.source_id.startswith("ical-test-")))
    seed_sources(db_engine)
    return db_engine


FEED = Source(
    source_id="ical-test-community",
    kind="ical",
    name="Test community calendar",
    legal_status="public_feed",
    refresh_cron="0 */6 * * *",
    reliability=0.8,
    url="https://calendar.example/community.ics",
)


@pytest.mark.db
def test_source_url_round_trips(engine: Engine) -> None:
    with session_scope(engine) as s:
        repo.upsert_source(s, FEED)
    with session_scope(engine) as s:
        assert repo.get_source(s, FEED.source_id) == FEED


@pytest.mark.db
def test_ingest_fetches_registry_feeds_and_stores_them_raw(engine: Engine) -> None:
    broken = FEED.model_copy(
        update={"source_id": "ical-test-broken", "url": "https://calendar.example/gone.ics"}
    )
    with session_scope(engine) as s:
        repo.upsert_source(s, FEED)
        repo.upsert_source(s, broken)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/gone.ics":
            return httpx.Response(404)
        return httpx.Response(200, text=DATED)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    results = {r["source_id"]: r for r in ical.ingest_feeds(engine, client, now=NOW)}

    # The family entry "ical-public-feeds" has no url and is not fetched.
    assert set(results) == {"ical-test-community", "ical-test-broken"}
    assert results["ical-test-broken"]["ok"] is False  # one broken feed doesn't stop the run
    assert results["ical-test-community"]["inferred_series"] == 3
    assert results["ical-test-community"]["new_payload"] is True

    again = ical.ingest_feeds(engine, client, now=NOW)
    assert {r["source_id"]: r.get("new_payload") for r in again}["ical-test-community"] is False
    with session_scope(engine) as s:
        record = repo.latest_raw_record(s, "ical-test-community")
        assert record is not None and record.payload == DATED


# --- Series across numbered titles, and hints from discover feeds -------------


# Real titles from the Luma "What's Happening in Munich" discover feed (12 Nov 2026).
@pytest.mark.parametrize(
    ("summary", "base", "numbered"),
    [
        ("Knight Gambit Vol.14", "Knight Gambit", True),
        ("Ambient Reading Session vol. 1 · Night 1", "Ambient Reading Session", True),
        ("Bumble x Plex Drip & Draw Vol. 2", "Bumble x Plex Drip & Draw", True),
        ("Industrial AI Night Vol. 1", "Industrial AI Night", True),
        ("Stammtisch Nr. 12 – Westend", "Stammtisch – Westend", True),
        ("Kreativabend Teil 2", "Kreativabend", True),
        ("The 3rd Edition: Poetry Slam", "The: Poetry Slam", True),
        # Not edition markers: numbers that are part of the name stay.
        (
            "Energy Stammtisch in Munich @ Proxima Fusion",
            "Energy Stammtisch in Munich @ Proxima Fusion",
            False,
        ),  # noqa: E501
        ("5k Run Club", "5k Run Club", False),
        ("Repair Café 246", "Repair Café 246", False),
        ("Industrial AI Night", "Industrial AI Night", False),
    ],
)
def test_series_title_strips_edition_markers_only(summary: str, base: str, numbered: bool) -> None:
    assert ical.series_title(summary) == base
    assert ical.has_edition_marker(summary) is numbered


def _vevent(uid: str, summary: str, start: str, extra: str = "") -> str:
    return (
        f"BEGIN:VEVENT\r\nUID:{uid}\r\nDTSTART;TZID=Europe/Berlin:{start}\r\n"
        f"DTEND;TZID=Europe/Berlin:{start[:9]}230000\r\nSUMMARY:{summary}\r\n"
        f"LOCATION:Schachcafé Test\\, Zugweg 1\\, München\r\n{extra}END:VEVENT\r\n"
    )


def _calendar(*events: str) -> str:
    return (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//test//EN\r\n"
        + "".join(events)
        + "END:VCALENDAR\r\n"
    )  # noqa: E501


def test_numbered_editions_on_the_same_weekday_form_one_series() -> None:
    feed = ical.parse_feed(
        _calendar(
            _vevent("k13", "Knight Gambit Vol.13", "20261027T190000"),
            _vevent("k14", "Knight Gambit Vol.14 ♟️", "20261103T190000"),  # emoji: same series
            _vevent("k15", "Knight Gambit Vol. 15", "20261110T190000"),
        )
    )
    [series] = ical.infer_series(feed.events)
    assert series.summary == "Knight Gambit"
    assert series.rrule == "FREQ=WEEKLY;BYDAY=TU"
    assert series.occurrences == 3


def test_numbered_titles_still_need_a_regular_rhythm() -> None:
    feed = ical.parse_feed(
        _calendar(
            _vevent("k1", "Knight Gambit Vol.1", "20261027T190000"),  # Tuesday
            _vevent("k2", "Knight Gambit Vol.2", "20261105T190000"),  # Thursday
            _vevent("k3", "Knight Gambit Vol.3", "20261110T190000"),  # Tuesday
        )
    )
    assert ical.infer_series(feed.events) == []


def test_discover_feed_gives_hints_with_links_to_follow() -> None:
    feed = ical.parse_feed(
        _calendar(
            _vevent(
                "kg",
                "Knight Gambit Vol.14",
                "20261117T190000",
                "DESCRIPTION:Get up-to-date information at: https://lu.ma/knight-14\\n\\nChess!\r\n",
            ),
            _vevent("dw", "Drip & Draw Vol. 2", "20261118T190000", "URL:https://lu.ma/dd2\r\n"),
            _vevent("es", "Energy Stammtisch in Munich", "20261119T190000"),
        )
    )
    hints = ical.summarise(feed, NOW)["series_hints"]
    assert [(h["series_title"], h["link"]) for h in hints] == [
        ("Knight Gambit", "https://lu.ma/knight-14"),
        ("Drip & Draw", "https://lu.ma/dd2"),
    ]


def test_series_are_not_listed_as_hints() -> None:
    hints = ical.summarise(ical.parse_feed(DATED), NOW)["series_hints"]
    assert hints == []
