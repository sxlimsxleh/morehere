"""OSM source: query building, parsing and retries. No network, no database."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from morehere.config import load_city_config
from morehere.sources import osm

FIXTURES = Path(__file__).parent / "fixtures"
PLACES_PAYLOAD = (FIXTURES / "overpass_places.json").read_text(encoding="utf-8")
DISTRICTS_PAYLOAD = (FIXTURES / "overpass_districts.json").read_text(encoding="utf-8")
CONFIG = load_city_config()


# --- Queries -----------------------------------------------------------------


def test_places_query_covers_bbox_and_every_configured_tag() -> None:
    query = osm.build_places_query(CONFIG)
    b = CONFIG.bbox
    assert f"({b.south},{b.west},{b.north},{b.east})" in query
    for tag in CONFIG.osm_place_tags:
        assert f'nwr["{tag.key}"="{tag.value}"]' in query
    assert query.startswith("[out:json]")
    assert query.endswith("out center tags;")


def test_districts_query_asks_for_admin_level_9_inside_munich() -> None:
    query = osm.build_districts_query()
    assert '"admin_level"="6"' in query and '"admin_level"="9"' in query
    assert "out geom;" in query


# --- Parsing places ----------------------------------------------------------


@pytest.mark.parametrize(
    ("tags", "kind"),
    [
        ({"amenity": "cafe"}, "cafe"),
        ({"amenity": "library"}, "library"),
        ({"amenity": "community_centre"}, "community_centre"),
        ({"amenity": "arts_centre"}, "community_centre"),
        ({"amenity": "coworking_space"}, "coworking"),
        ({"office": "coworking"}, "coworking"),
        ({"leisure": "hackerspace"}, "makerspace"),
        ({"sport": "climbing", "leisure": "sports_centre"}, "sports"),
        ({"amenity": "cafe", "leisure": "hackerspace"}, "makerspace"),  # most specific wins
        ({"amenity": "bench"}, None),
        ({}, None),
    ],
)
def test_place_kind_mapping(tags: dict[str, str], kind: str | None) -> None:
    assert osm.place_kind(tags) == kind


def test_parse_places_counts_what_it_keeps_and_skips() -> None:
    parsed = osm.parse_places(PLACES_PAYLOAD)
    assert sorted(p.place_id for p in parsed.places) == [
        "osm-node-1001",
        "osm-node-1004",
        "osm-node-1005",
        "osm-relation-3001",
        "osm-way-2001",
        "osm-way-2002",
    ]
    assert parsed.skipped_unnamed == 1
    assert parsed.skipped_unknown_kind == 1
    assert parsed.skipped_no_location == 1


def test_parse_places_builds_address_location_and_keeps_only_whitelisted_tags() -> None:
    places = {p.place_id: p for p in osm.parse_places(PLACES_PAYLOAD).places}

    cafe = places["osm-node-1001"]
    assert cafe.name == "Café Lindwurm"
    assert cafe.address == "Teststraße 1"
    assert cafe.osm_id == "node/1001"
    assert cafe.geo is not None and (cafe.geo.lat, cafe.geo.lon) == (48.1370, 11.5760)
    assert "fax" not in cafe.osm_tags
    assert cafe.osm_tags["internet_access"] == "wlan"

    library = places["osm-way-2001"]  # a way: location comes from its centre
    assert library.geo is not None and library.geo.lat == 48.1500
    assert library.address is None

    assert places["osm-relation-3001"].address == "Hofweg"  # street without number


# --- Parsing districts -------------------------------------------------------


def test_match_district_by_name_prefix_and_ref() -> None:
    assert osm.match_district(CONFIG, {"name": "Altstadt-Lehel"}) == (1, "Altstadt-Lehel")
    assert osm.match_district(CONFIG, {"name": "Stadtbezirk 03 Maxvorstadt"}) == (
        3,
        "Maxvorstadt",
    )
    assert osm.match_district(CONFIG, {"name": "Milbertshofen - Am Hart"}) == (
        11,
        "Milbertshofen-Am Hart",
    )
    assert osm.match_district(CONFIG, {"name": "Unknown", "ref": "05"}) == (5, "Au-Haidhausen")
    assert osm.match_district(CONFIG, {"name": "Irgendwo"}) is None


def test_parse_districts_collects_ways_and_reports_unmatched() -> None:
    districts, unmatched = osm.parse_districts(CONFIG, DISTRICTS_PAYLOAD)
    by_number = {d.number: d for d in districts}
    assert sorted(by_number) == [1, 3]
    assert len(by_number[1].ways_wkt) == 2  # one boundary split across two ways
    assert by_number[1].ways_wkt[0].startswith("LINESTRING(11.57 48.132")  # lon before lat
    assert unmatched == ["Irgendwo"]


# --- Fetching with retries ---------------------------------------------------


def _client(responses: list[httpx.Response], seen: list[httpx.Request]) -> httpx.Client:
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return queue.pop(0)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_retries_on_429_and_honours_retry_after() -> None:
    seen: list[httpx.Request] = []
    waits: list[float] = []
    client = _client(
        [
            httpx.Response(429, headers={"Retry-After": "7"}),
            httpx.Response(200, text=PLACES_PAYLOAD),
        ],
        seen,
    )
    assert osm.fetch_overpass(client, "q", sleep=waits.append) == PLACES_PAYLOAD
    assert len(seen) == 2
    assert waits == [7.0]
    assert seen[0].content == b"data=q"  # the query is sent as a form field


def test_fetch_retries_on_overpass_runtime_error_in_a_200() -> None:
    seen: list[httpx.Request] = []
    timeout_body = json.dumps({"elements": [], "remark": "runtime error: Query timed out"})
    client = _client(
        [httpx.Response(200, text=timeout_body), httpx.Response(200, text=PLACES_PAYLOAD)], seen
    )
    assert osm.fetch_overpass(client, "q", sleep=lambda _: None) == PLACES_PAYLOAD
    assert len(seen) == 2


def test_fetch_gives_up_after_max_attempts() -> None:
    seen: list[httpx.Request] = []
    client = _client([httpx.Response(504)] * 3, seen)
    with pytest.raises(httpx.HTTPStatusError):
        osm.fetch_overpass(client, "q", max_attempts=3, sleep=lambda _: None)
    assert len(seen) == 3


def test_fetch_does_not_retry_a_bad_query() -> None:
    seen: list[httpx.Request] = []
    client = _client([httpx.Response(400, text="parse error")], seen)
    with pytest.raises(httpx.HTTPStatusError):
        osm.fetch_overpass(client, "q", sleep=lambda _: None)
    assert len(seen) == 1
