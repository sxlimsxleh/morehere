"""What the API returns. Deliberately separate from the internal models in morehere.models:
the app's contract stays stable when internals change, and internal fields (review notes,
raw record ids, drafts) can't leak out."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class TagOut(BaseModel):
    name: str
    quote: str = Field(description="The words in the source this tag is based on.")


class ScoreOut(BaseModel):
    total: float = Field(ge=0, le=1)
    components: dict[str, float]
    based_on: dict[str, list[str]]


class PlaceSummary(BaseModel):
    name: str
    district: str | None
    has_coordinates: bool


class ListingCard(BaseModel):
    """One listing in the feed or in search results."""

    id: str
    title: str
    category: str
    place: PlaceSummary
    schedule_text: str | None = Field(description="e.g. 'every 2nd Thursday of the month'")
    next_occurrence: datetime | None = Field(description="Local time, with UTC offset.")
    tags: list[TagOut]
    language: str | None
    price_eur: float | None
    score: ScoreOut
    distance_m: float | None = Field(description="Only when lat/lon were given.")
    last_verified_at: datetime


class FactOut(BaseModel):
    field: str
    value: Any
    quote: str
    source: str = Field(description="Name of the source, e.g. 'Public iCal feeds'.")
    source_url: str | None


class ScheduleOut(BaseModel):
    rrule: str
    text_en: str
    text_de: str
    duration_min: int | None
    breaks: list[str] = Field(description="e.g. 'Sommerpause: August'")
    next: list[datetime]


class PlaceOut(BaseModel):
    name: str
    address: str | None
    district: str | None
    lat: float | None
    lon: float | None
    attribution: str | None = Field(description="Must be shown, e.g. for OpenStreetMap data.")


class ListingDetail(BaseModel):
    id: str
    title: str
    category: str
    place: PlaceOut
    schedule: ScheduleOut | None
    first_timer_info: str | None
    organiser_contact: str | None
    language: str | None
    price_eur: float | None
    price_period: str | None
    come_alone: bool | None
    beginner_friendly: bool | None
    group_size: str | None
    tags: list[TagOut]
    facts: list[FactOut] = Field(description="Every shown fact with the words it comes from.")
    score: ScoreOut
    last_verified_at: datetime


class FeedPage(BaseModel):
    items: list[ListingCard]
    total: int
    offset: int
    limit: int


class MapFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: dict[str, Any]
    properties: dict[str, Any]


class MapCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[MapFeature]
    attribution: str = "© OpenStreetMap contributors"


class Health(BaseModel):
    status: Literal["ok"]
    published_listings: int
