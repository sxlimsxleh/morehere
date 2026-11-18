"""The API's logic, without HTTP: load published listings, filter, rank, shape responses.

The catalogue is small (tens to hundreds of curated listings), so filtering and ranking run
in Python over the published set: simple to read and to test. When it grows to thousands,
move the filters into SQL; the functions' inputs and outputs stay the same.
"""

from __future__ import annotations

import math
import string
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import Engine

from morehere.api.schemas import (
    FactOut,
    ListingCard,
    ListingDetail,
    MapCollection,
    MapFeature,
    PlaceOut,
    PlaceSummary,
    ScheduleOut,
    ScoreOut,
    TagOut,
)
from morehere.config import CityConfig
from morehere.db import repo
from morehere.db.session import session_scope
from morehere.models import GeoPoint, Listing, Place, Source
from morehere.recurrence import describe, next_occurrences
from morehere.score import regular_score

LOCAL = ZoneInfo("Europe/Berlin")
When = str  # "tonight" | "weekend" | "week"

SHOWN_FACTS = (
    "schedule",
    "language",
    "price_eur",
    "price_period",
    "come_alone",
    "beginner_friendly",
    "group_size",
    "first_timer_info",
    "organiser_contact",
)


@dataclass
class Item:
    listing: Listing
    place: Place


@dataclass
class Catalogue:
    items: list[Item]
    sources: dict[str, Source]


def load_catalogue(engine: Engine) -> Catalogue:
    """Published listings with their places. Listings at places with coordinates outside
    every Munich district are left out (the OSM bounding box reaches beyond the city)."""
    with session_scope(engine) as session:
        listings = repo.list_listings(session, "published")
        places = {
            p.place_id: p
            for lid in {lst.place_id for lst in listings}
            if (p := repo.get_place(session, lid))
        }
        sources = {s.source_id: s for s in repo.list_sources(session)}
    items = [
        Item(lst, places[lst.place_id])
        for lst in listings
        if lst.place_id in places
        and not (places[lst.place_id].geo is not None and places[lst.place_id].district is None)
    ]
    return Catalogue(items, sources)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def display_title(title: str) -> str:
    """'ISAR MORNING RUNNERS' -> 'Isar Morning Runners'. Other titles are left as written."""
    letters = [c for c in title if c.isalpha()]
    if len(letters) > 3 and all(c.isupper() for c in letters):
        return string.capwords(title.lower())
    return title


def distance_m(a: GeoPoint, b: GeoPoint) -> float:
    """Great-circle distance in metres (haversine). Plenty precise within a city."""
    lat1, lon1, lat2, lon2 = map(math.radians, (a.lat, a.lon, b.lat, b.lon))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * 6_371_000 * math.asin(math.sqrt(h))


def window(when: When, now: datetime) -> tuple[datetime, datetime]:
    """[start, end) in local time for tonight / this weekend / the next 7 days."""
    local = now.astimezone(LOCAL)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if when == "tonight":
        return local, midnight + timedelta(days=1)
    if when == "weekend":
        saturday = midnight + timedelta(days=(5 - local.weekday()) % 7)
        if local.weekday() == 6:  # Sunday: the weekend is today
            saturday = midnight - timedelta(days=1)
        return max(local, saturday), saturday + timedelta(days=2)
    if when == "week":
        return local, local + timedelta(days=7)
    raise ValueError(f"unknown 'when': {when}")


def next_in(listing: Listing, start: datetime, end: datetime) -> datetime | None:
    if listing.schedule is None:
        return None
    for occurrence in next_occurrences(listing.schedule, start - timedelta(seconds=1), 10):
        if occurrence >= end:
            return None
        if occurrence >= start:
            return occurrence
    return None


def _score(listing: Listing, config: CityConfig, distance: float | None) -> ScoreOut:
    s = regular_score(listing, config.score_weights, distance_m=distance)
    return ScoreOut(total=s.total, components=s.components, based_on=s.based_on)


def _tags(listing: Listing) -> list[TagOut]:
    return [TagOut(name=t.name, quote=t.evidence.source_text) for t in listing.tags]


def _schedule_text(listing: Listing) -> str | None:
    return describe(listing.schedule.rrule, "en") if listing.schedule else None


# ---------------------------------------------------------------------------
# Feed, search, detail, map
# ---------------------------------------------------------------------------


@dataclass
class Filters:
    category: str | None = None
    english: bool = False
    free: bool = False
    district: str | None = None
    when: When | None = None


def _passes(item: Item, f: Filters, now: datetime) -> bool:
    lst = item.listing
    if f.category and lst.category != f.category:
        return False
    if f.english and lst.language not in ("en", "en+de"):
        return False
    if f.free and lst.price_eur != 0:
        return False
    if f.district and item.place.district != f.district:
        return False
    if f.when:
        start, end = window(f.when, now)
        if next_in(lst, start, end) is None:
            return False
    return True


def card(item: Item, config: CityConfig, now: datetime, here: GeoPoint | None) -> ListingCard:
    lst, place = item.listing, item.place
    distance = distance_m(here, place.geo) if here and place.geo else None
    nxt = next_occurrences(lst.schedule, now, 1) if lst.schedule else []
    return ListingCard(
        id=lst.listing_id,
        title=display_title(lst.title),
        category=lst.category,
        place=PlaceSummary(
            name=place.name, district=place.district, has_coordinates=place.geo is not None
        ),
        schedule_text=_schedule_text(lst),
        next_occurrence=nxt[0] if nxt else None,
        tags=_tags(lst),
        language=lst.language,
        price_eur=lst.price_eur,
        score=_score(lst, config, distance),
        distance_m=round(distance) if distance is not None else None,
        last_verified_at=lst.last_verified_at,  # type: ignore[arg-type]  # published => set
    )


def feed(
    catalogue: Catalogue,
    config: CityConfig,
    now: datetime,
    filters: Filters,
    here: GeoPoint | None = None,
    query: str | None = None,
) -> list[ListingCard]:
    """Matching listings, best Regular Score first (distance included when `here` is given)."""
    words = query.casefold().split() if query else []
    cards = []
    for item in catalogue.items:
        if not _passes(item, filters, now):
            continue
        if words and not all(w in _haystack(item) for w in words):
            continue
        cards.append(card(item, config, now, here))
    return sorted(cards, key=lambda c: (-c.score.total, c.title))


def _haystack(item: Item) -> str:
    lst = item.listing
    parts = [
        lst.title,
        lst.category.replace("_", " "),
        item.place.name,
        item.place.district or "",
        lst.first_timer_info or "",
        *(t.name for t in lst.tags),
    ]
    return " ".join(parts).casefold()


def detail(item: Item, catalogue: Catalogue, config: CityConfig, now: datetime) -> ListingDetail:
    lst, place = item.listing, item.place
    facts = []
    for name in SHOWN_FACTS:
        ev = lst.field_evidence.get(name)
        if ev is None:
            continue
        value = _schedule_text(lst) if name == "schedule" else getattr(lst, name)
        source = catalogue.sources.get(ev.source_id)
        facts.append(
            FactOut(
                field=name,
                value=value,
                quote=ev.source_text,
                source=source.name if source else ev.source_id,
                source_url=ev.url,
            )
        )
    schedule = None
    if lst.schedule:
        months = {m: datetime(2000, m, 1).strftime("%B") for m in range(1, 13)}
        schedule = ScheduleOut(
            rrule=lst.schedule.rrule,
            text_en=describe(lst.schedule.rrule, "en"),
            text_de=describe(lst.schedule.rrule, "de"),
            duration_min=lst.schedule.duration_min,
            breaks=[
                f"{b.label}: {', '.join(months[m] for m in b.months)}" for b in lst.schedule.breaks
            ],
            next=next_occurrences(lst.schedule, now, 5),
        )
    osm = catalogue.sources.get("osm-overpass")
    return ListingDetail(
        id=lst.listing_id,
        title=display_title(lst.title),
        category=lst.category,
        place=PlaceOut(
            name=place.name,
            address=place.address,
            district=place.district,
            lat=place.geo.lat if place.geo else None,
            lon=place.geo.lon if place.geo else None,
            attribution=(osm.attribution if osm else "© OpenStreetMap contributors")
            if place.osm_id
            else None,
        ),
        schedule=schedule,
        first_timer_info=lst.first_timer_info,
        organiser_contact=lst.organiser_contact,
        language=lst.language,
        price_eur=lst.price_eur,
        price_period=lst.price_period,
        come_alone=lst.come_alone,
        beginner_friendly=lst.beginner_friendly,
        group_size=lst.group_size,
        tags=_tags(lst),
        facts=facts,
        score=_score(lst, config, None),
        last_verified_at=lst.last_verified_at,  # type: ignore[arg-type]
    )


def map_collection(
    catalogue: Catalogue, config: CityConfig, now: datetime, filters: Filters
) -> MapCollection:
    features = []
    for item in catalogue.items:
        if item.place.geo is None or not _passes(item, filters, now):
            continue
        c = card(item, config, now, None)
        features.append(
            MapFeature(
                geometry={"type": "Point", "coordinates": [item.place.geo.lon, item.place.geo.lat]},
                properties={
                    "id": c.id,
                    "title": c.title,
                    "category": c.category,
                    "score": c.score.total,
                    "next_occurrence": c.next_occurrence.isoformat() if c.next_occurrence else None,
                },
            )
        )
    return MapCollection(features=features)
