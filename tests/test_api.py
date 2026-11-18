"""Milestone 8: the read-only API. Only published listings, every fact with its quote."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from test_curation import CONFIG, LISTINGS, curated_db  # noqa: F401  (fixture)

from morehere.api.export_openapi import OPENAPI_PATH, openapi_json
from morehere.api.service import display_title, window
from morehere.models import GeoPoint, Place

# Wednesday 18 Nov 2026, 11:00 in Munich.
NOW = datetime(2026, 11, 18, 10, 0, tzinfo=UTC)


# --- Pure helpers ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "shown"),
    [
        ("ISAR MORNING RUNNERS", "Isar Morning Runners"),
        ("NEW FACES WEDNESDAY", "New Faces Wednesday"),
        (
            "Tandem Tuesday – English/German Language Café",
            "Tandem Tuesday – English/German Language Café",
        ),  # noqa: E501
        ("FabLab Open Night", "FabLab Open Night"),  # mixed case is left alone
        ("WG", "WG"),  # too short to be shouting
    ],
)
def test_display_title(title: str, shown: str) -> None:
    assert display_title(title) == shown


def test_windows_in_local_time() -> None:
    start, end = window("tonight", NOW)
    assert (start.hour, end.day, end.hour) == (11, 19, 0)
    sat, sun_end = window("weekend", NOW)
    assert (sat.day, sat.hour, sun_end.day) == (21, 0, 23)
    sunday = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
    start, end = window("weekend", sunday)
    assert (start.day, end.day) == (22, 23)  # on Sunday, the weekend is what's left of today


def test_committed_openapi_is_up_to_date() -> None:
    # The app's TypeScript types are generated from app/openapi.json; if this fails,
    # run `make openapi` and commit both files.
    assert OPENAPI_PATH.read_text(encoding="utf-8") == openapi_json()


# --- Against the database ----------------------------------------------------------

PUBLISHED = {
    # key: (district, coordinates, osm_id)
    "tandem-tuesday-luma": ("Schwabing-West", GeoPoint(lat=48.1610, lon=11.5750), "node/1"),
    "isar-morning-runners": (
        "Ludwigsvorstadt-Isarvorstadt",
        GeoPoint(lat=48.1350, lon=11.5830),
        None,
    ),
    "chor-haidhausen": ("Au-Haidhausen", None, None),
    "garten-laim": ("Laim", GeoPoint(lat=48.1370, lon=11.5030), None),
    "clay-and-chat": (None, GeoPoint(lat=48.30, lon=11.40), None),  # outside every district
}


@pytest.fixture
def client(curated_db: Engine) -> TestClient:  # noqa: F811
    from morehere.db import repo
    from morehere.db.session import session_scope

    with session_scope(curated_db) as s:
        for key, (district, geo, osm_id) in PUBLISHED.items():
            listing = LISTINGS[key]
            repo.save_place(
                s,
                Place(
                    place_id=listing.place_id,
                    name=f"Place of {key}",
                    district=district,
                    geo=geo,
                    osm_id=osm_id,
                    kind="other",
                ),
            )
            update = {"status": "published", "last_verified_at": NOW}
            if key == "isar-morning-runners":
                update["title"] = "ISAR MORNING RUNNERS"
            repo.save_listing(s, listing.model_copy(update=update))
    from morehere.api.app import create_app

    return TestClient(create_app(engine=curated_db, config=CONFIG, clock=lambda: NOW))


def ids(response) -> list[str]:  # type: ignore[no-untyped-def]
    return [item["id"] for item in response.json()["items"]]


def lid(key: str) -> str:
    return LISTINGS[key].listing_id


@pytest.mark.db
def test_feed_shows_only_published_listings_inside_munich(client: TestClient) -> None:
    feed = client.get("/listings")
    assert feed.status_code == 200
    assert set(ids(feed)) == {
        lid("tandem-tuesday-luma"),
        lid("isar-morning-runners"),
        lid("chor-haidhausen"),
        lid("garten-laim"),
    }
    assert feed.json()["total"] == 4
    scores = [i["score"]["total"] for i in feed.json()["items"]]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.db
def test_unpublished_listing_is_not_found(client: TestClient) -> None:
    assert client.get(f"/listings/{lid('book-swap-sendling')}").status_code == 404
    assert client.get("/listings/does-not-exist").status_code == 404


@pytest.mark.db
def test_card_has_display_title_next_date_and_tag_quotes(client: TestClient) -> None:
    cards = {c["id"]: c for c in client.get("/listings").json()["items"]}
    runners = cards[lid("isar-morning-runners")]
    assert runners["title"] == "Isar Morning Runners"
    assert runners["next_occurrence"].startswith("2026-11-21T09:00:00+01:00")  # Saturday 9:00
    assert runners["distance_m"] is None
    tandem = cards[lid("tandem-tuesday-luma")]
    assert {"name": "come alone OK", "quote": "Most people come alone, so don't be shy!"} in (
        tandem["tags"]
    )


@pytest.mark.db
def test_location_adds_distance_to_the_score(client: TestClient) -> None:
    at_the_bridge = {"lat": 48.1350, "lon": 11.5830}
    cards = {c["id"]: c for c in client.get("/listings", params=at_the_bridge).json()["items"]}
    runners, tandem = cards[lid("isar-morning-runners")], cards[lid("tandem-tuesday-luma")]
    assert runners["distance_m"] == 0
    assert 2500 < tandem["distance_m"] < 3500
    assert runners["score"]["components"]["distance"] > tandem["score"]["components"]["distance"]
    assert cards[lid("chor-haidhausen")]["distance_m"] is None  # no coordinates
    assert client.get("/listings", params={"lat": 48.1}).status_code == 422


@pytest.mark.db
@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"english": True}, {"tandem-tuesday-luma", "isar-morning-runners"}),
        ({"free": True}, {"tandem-tuesday-luma", "isar-morning-runners", "garten-laim"}),
        ({"category": "choir_music"}, {"chor-haidhausen"}),
        ({"district": "Laim"}, {"garten-laim"}),
        ({"when": "tonight"}, {"chor-haidhausen"}),  # Wednesday 19:30
        ({"when": "weekend"}, {"isar-morning-runners"}),  # the garden is in its winter break
        ({"when": "week"}, {"tandem-tuesday-luma", "isar-morning-runners", "chor-haidhausen"}),
    ],
)
def test_filters(client: TestClient, params: dict, expected: set[str]) -> None:  # type: ignore[type-arg]
    assert set(ids(client.get("/listings", params=params))) == {lid(k) for k in expected}


@pytest.mark.db
def test_search(client: TestClient) -> None:
    assert ids(client.get("/search", params={"q": "chor"})) == [lid("chor-haidhausen")]
    assert ids(client.get("/search", params={"q": "come alone"})) == [lid("tandem-tuesday-luma")]
    assert ids(client.get("/search", params={"q": "zzzz"})) == []
    assert client.get("/search", params={"q": "x"}).status_code == 422


@pytest.mark.db
def test_detail_shows_every_fact_with_its_quote(client: TestClient) -> None:
    detail = client.get(f"/listings/{lid('chor-haidhausen')}").json()
    assert detail["facts"], "a published listing has facts"
    assert all(f["quote"] and f["source"] for f in detail["facts"])
    assert detail["schedule"]["text_de"] == "jeden Mittwoch"
    assert detail["schedule"]["breaks"] == ["Sommerpause: August"]
    assert len(detail["schedule"]["next"]) == 5
    assert detail["place"]["attribution"] is None  # not an OSM place
    assert "review_notes" not in detail and "field_evidence" not in detail


@pytest.mark.db
def test_osm_places_carry_the_attribution(client: TestClient) -> None:
    detail = client.get(f"/listings/{lid('tandem-tuesday-luma')}").json()
    assert detail["place"]["attribution"] == "© OpenStreetMap contributors"


@pytest.mark.db
def test_map_is_geojson_of_located_listings(client: TestClient) -> None:
    geo = client.get("/map").json()
    assert geo["type"] == "FeatureCollection"
    by_id = {f["properties"]["id"]: f for f in geo["features"]}
    assert set(by_id) == {
        lid("tandem-tuesday-luma"),
        lid("isar-morning-runners"),
        lid("garten-laim"),
    }
    assert by_id[lid("garten-laim")]["geometry"]["coordinates"] == [11.5030, 48.1370]  # lon, lat


@pytest.mark.db
def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok", "published_listings": 4}
