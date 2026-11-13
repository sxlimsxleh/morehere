"""Data contracts for morehere.

Two rules from CLAUDE.md are enforced here, at the type level, so no later step can
skip them:

- Grounded or flagged (rule 2): an `ExtractedField` with status "ok" must carry
  evidence; a "flagged" one must have no value and a reason.
- Every tag shows its evidence (rule 3): a `Tag` cannot be built without `Evidence`.

Times are local Munich wall-clock times (naive `datetime`/`time`); the time zone lives
on `Schedule.timezone`. Recurrence is stored as an iCal RRULE string here and parsed in
`recurrence.py` (milestone 4).
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ---------------------------------------------------------------------------
# Shared vocabularies
# ---------------------------------------------------------------------------

SourceKind = Literal["osm", "ical", "submission", "email", "tip", "places_api", "web_page"]

# How we are allowed to use a source (see "Data sources" in the plan).
LegalStatus = Literal[
    "open_licence",  # e.g. OSM under ODbL: use with attribution
    "public_feed",  # published for subscription, e.g. a public iCal URL
    "first_party",  # organisers/venues submit it to us directly
    "user_provided",  # a user pasted or forwarded it to us
    "licensed_api",  # API with terms that limit storage (Google Places)
]

PlaceKind = Literal[
    "cafe",
    "library",
    "community_centre",
    "coworking",
    "makerspace",
    "studio",
    "sports",
    "park",
    "pub",
    "meeting_point",
    "other",
]

Category = Literal[
    "language_exchange",
    "running",
    "sport",
    "board_games",
    "choir_music",
    "arts_crafts",
    "study_cowork",
    "makerspace",
    "outdoors",
    "social",
    "film",
    "volunteering",
    "other",
]

Language = Literal["en", "de", "en+de"]
PricePeriod = Literal["per_visit", "monthly", "per_term", "donation"]
# small: under 10 people, medium: 10-30, large: over 30
GroupSize = Literal["small", "medium", "large"]

# Problems a draft can carry. Any flag sends the draft to the curator queue.
Flag = Literal[
    "suspected_injection",  # text that looks like instructions to the system
    "not_recurring",  # a one-off event; out of scope
    "cancelled",  # the source says it no longer happens
    "stale",  # the source itself is older than the freshness window
    "missing_time",  # no start time stated
    "ambiguous_recurrence",  # e.g. "biweekly"
    "uncertain_source",  # the author hedges ("I think", "sometimes")
]

ListingStatus = Literal["draft", "needs_review", "published", "hidden"]


class _Strict(BaseModel):
    # Reject unknown keys so typos in data or labels fail loudly.
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


class Evidence(_Strict):
    """Where a fact came from: a verbatim span of a stored raw record."""

    source_id: str
    raw_record_id: str
    source_text: str = Field(min_length=1)
    url: str | None = None
    captured_at: datetime


class ExtractedField[T](_Strict):
    """A single extracted value: grounded in evidence, or flagged with a reason."""

    value: T | None = None
    evidence: Evidence | None = None
    status: Literal["ok", "flagged"]
    reason: str | None = None

    @model_validator(mode="after")
    def _grounded_or_flagged(self) -> ExtractedField[T]:
        if self.status == "ok":
            if self.value is None:
                raise ValueError("status 'ok' needs a value")
            if self.evidence is None:
                raise ValueError("status 'ok' needs evidence")
        else:
            if self.value is not None:
                raise ValueError("a flagged field must not keep a value (never guess)")
            if not self.reason:
                raise ValueError("a flagged field needs a reason")
        return self


class Source(_Strict):
    """An entry in the source registry."""

    source_id: str
    kind: SourceKind
    name: str
    legal_status: LegalStatus
    licence: str | None = None  # e.g. "ODbL-1.0"
    attribution: str | None = None  # text we must show, e.g. "© OpenStreetMap contributors"
    refresh_cron: str | None = None  # None: not fetched on a schedule (pushed to us)
    reliability: float = Field(ge=0.0, le=1.0)
    # Where we fetch from, for sources we pull (one iCal feed = one source). None for
    # source families and for sources that push data to us.
    url: str | None = None


class RawRecord(_Strict):
    """A raw payload exactly as received. Kept so extraction can be re-run."""

    raw_record_id: str
    source_id: str
    fetched_at: datetime
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_type: str  # MIME type, e.g. "text/calendar"
    url: str | None = None
    payload: str

    @model_validator(mode="after")
    def _hash_matches_payload(self) -> RawRecord:
        if self.sha256 != sha256_text(self.payload):
            raise ValueError("sha256 does not match payload")
        return self


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Places and schedules
# ---------------------------------------------------------------------------


class GeoPoint(_Strict):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class Place(_Strict):
    """A physical venue or meeting point, mostly from OpenStreetMap."""

    place_id: str
    name: str
    address: str | None = None
    district: str | None = None
    geo: GeoPoint | None = None
    osm_id: str | None = None  # e.g. "node/123456"
    kind: PlaceKind
    # Raw OSM key/value tags (wifi, opening_hours, ...). These are map data,
    # not user-facing `Tag`s, so they do not carry `Evidence`.
    osm_tags: dict[str, str] = Field(default_factory=dict)


class ScheduleBreak(_Strict):
    """A recurring pause, e.g. a summer break in August or a winter season off."""

    label: str
    months: list[int] = Field(min_length=1)

    @model_validator(mode="after")
    def _valid_months(self) -> ScheduleBreak:
        if any(m < 1 or m > 12 for m in self.months):
            raise ValueError("months must be 1-12")
        return self


class Schedule(_Strict):
    rrule: str  # iCal RRULE without the "RRULE:" prefix, e.g. "FREQ=MONTHLY;BYDAY=2TH"
    dtstart: datetime  # local wall-clock time of the first occurrence
    duration_min: int | None = Field(default=None, gt=0)
    exdates: list[date] = Field(default_factory=list)
    timezone: str = "Europe/Berlin"
    breaks: list[ScheduleBreak] = Field(default_factory=list)

    @model_validator(mode="after")
    def _looks_like_rrule(self) -> Schedule:
        # Full parsing is milestone 4; here we only catch obvious mistakes.
        if not self.rrule.startswith("FREQ="):
            raise ValueError("rrule must start with 'FREQ=' (no 'RRULE:' prefix)")
        if self.dtstart.tzinfo is not None:
            raise ValueError("dtstart is local wall-clock time; keep it naive")
        return self


# ---------------------------------------------------------------------------
# Extraction output (milestone 5 fills this; the LLM never builds a Listing)
# ---------------------------------------------------------------------------


class ListingDraft(_Strict):
    """What extraction produces from one raw record, before any code decides.

    Every content field is an ExtractedField. A field that the source does not mention
    is flagged with reason "not stated". The schedule is not extracted directly: the
    LLM returns the verbatim `recurrence_text` and `start_time`, and code turns them
    into an RRULE (rule 1: the LLM reads, code decides).
    """

    raw_record_id: str
    source_id: str
    extracted_at: datetime

    title: ExtractedField[str]
    place_name: ExtractedField[str]
    address: ExtractedField[str]
    district: ExtractedField[str]
    category: ExtractedField[Category]
    recurrence_text: ExtractedField[str]
    start_time: ExtractedField[time]
    end_time: ExtractedField[time]
    seasonal_text: ExtractedField[str]
    language: ExtractedField[Language]
    price_eur: ExtractedField[float]
    price_period: ExtractedField[PricePeriod]
    come_alone: ExtractedField[bool]
    beginner_friendly: ExtractedField[bool]
    group_size: ExtractedField[GroupSize]
    first_timer_info: ExtractedField[str]
    organiser_contact: ExtractedField[str]
    source_updated_at: ExtractedField[date]

    tags: list[Tag] = Field(default_factory=list)
    flags: list[Flag] = Field(default_factory=list)


# Fields of ListingDraft that hold ExtractedFields; shared by evals and tests.
DRAFT_FIELDS: tuple[str, ...] = (
    "title",
    "place_name",
    "address",
    "district",
    "category",
    "recurrence_text",
    "start_time",
    "end_time",
    "seasonal_text",
    "language",
    "price_eur",
    "price_period",
    "come_alone",
    "beginner_friendly",
    "group_size",
    "first_timer_info",
    "organiser_contact",
    "source_updated_at",
)


# ---------------------------------------------------------------------------
# Curated, user-facing objects
# ---------------------------------------------------------------------------


class Tag(_Strict):
    """A user-facing tag such as "beginners welcome". No evidence, no tag."""

    name: str
    evidence: Evidence


class Listing(_Strict):
    """A recurring thing at a place, after code and a curator have decided.

    Values are plain here; `field_evidence` maps a field name to the evidence it was
    accepted on, so the app can show "says *beginners welcome* on the organiser page".
    """

    listing_id: str
    title: str
    place_id: str
    category: Category
    schedule: Schedule | None = None
    language: Language | None = None
    price_eur: float | None = Field(default=None, ge=0)
    price_period: PricePeriod | None = None
    come_alone: bool | None = None
    beginner_friendly: bool | None = None
    group_size: GroupSize | None = None
    first_timer_info: str | None = None
    organiser_contact: str | None = None
    tags: list[Tag] = Field(default_factory=list)
    field_evidence: dict[str, Evidence] = Field(default_factory=dict)
    status: ListingStatus = "draft"
    last_verified_at: datetime | None = None
    source_ids: list[str] = Field(default_factory=list)
    # Things a curator should look at: merge conflicts, flags, missing facts (milestone 6).
    review_notes: list[str] = Field(default_factory=list)
    # Computed by score.py without the user's location (distance is added at query time).
    regular_score: RegularScore | None = None

    @model_validator(mode="after")
    def _publishable(self) -> Listing:
        if self.status != "published":
            return self
        if self.schedule is None or "schedule" not in self.field_evidence:
            raise ValueError("a published listing needs a schedule backed by evidence")
        if self.last_verified_at is None:
            raise ValueError("a published listing needs last_verified_at")
        if not self.source_ids:
            raise ValueError("a published listing needs at least one source")
        return self


class RegularScore(_Strict):
    """How well a listing supports becoming a regular. Computed by code (milestone 6)."""

    total: float = Field(ge=0.0, le=1.0)
    # component name -> score in [0, 1], e.g. "recurrence", "newcomer_welcome"
    components: dict[str, float]
    # component name -> field or tag names it was computed from
    based_on: dict[str, list[str]] = Field(default_factory=dict)


# ListingDraft refers to Tag and Listing to RegularScore, both defined after them.
ListingDraft.model_rebuild()
Listing.model_rebuild()
