"""Grounding: decide which of the model's claims are accepted (rules 1 and 2).

The model returns claims: for each field a value, the verbatim span it came from, and an
optional note. This module turns claims into a ListingDraft:

1. The span must occur in the document text (whitespace-insensitive).
2. The value must be supported by the span, by field type:
   - times and prices are parsed out of the span (German and English formats);
   - dates are parsed out of the span;
   - names, addresses, contacts and schedule phrases must appear in the span;
   - district names are mapped to a Stadtbezirk via config aliases; ambiguous -> flagged;
   - judgement fields (category, language, booleans, group size, price period,
     first-timer info) need a grounded span; their value can't be string-matched.
3. Flags are set here, by code, from grounded evidence (never taken on the model's word).

Anything that fails is flagged with a reason and value None. Never guess.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from morehere.config import CityConfig
from morehere.models import (
    DRAFT_FIELDS,
    Evidence,
    Flag,
    ListingDraft,
)
from morehere.recurrence import MONTHS, parse_recurrence
from morehere.text import contains_span, normalise_whitespace

# ---------------------------------------------------------------------------
# What the model returns (validated before anything else happens)
# ---------------------------------------------------------------------------

ObservationKind = Literal["suspected_injection", "cancelled", "uncertain_source", "one_off"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClaimedField(_Strict):
    value: Any = None
    source_text: str | None = None
    note: str | None = None

    @field_validator("value", "source_text", "note", mode="before")
    @classmethod
    def _empty_is_none(cls, v: Any) -> Any:
        # The schema has no nulls (API limit on union types): "" means "nothing".
        return None if isinstance(v, str) and not v.strip() else v


class Observation(_Strict):
    kind: ObservationKind
    source_text: str


class ClaimedListing(_Strict):
    fields: dict[str, ClaimedField]
    observations: list[Observation] = []


class ClaimedExtraction(_Strict):
    listings: list[ClaimedListing]
    # Instruction-like text anywhere in the document, quoted.
    injection_spans: list[str] = []


# ---------------------------------------------------------------------------
# Parsing values out of spans
# ---------------------------------------------------------------------------

_HHMM = re.compile(r"(?<![\d.,])(\d{1,2})[:.](\d{2})(?!\d)\s*(am|pm|uhr|h\b)?", re.IGNORECASE)
_H_AMPM = re.compile(r"(?<![\d:.])(\d{1,2})\s*(am|pm)\b", re.IGNORECASE)
_H_UHR = re.compile(r"(?<![\d:.])(\d{1,2})\s*(?:uhr|h)\b", re.IGNORECASE)
_RANGE_UHR = re.compile(r"(?<![\d:.])(\d{1,2})\s*(?:bis|-|–|to)\s*(\d{1,2})\s*uhr", re.IGNORECASE)
_ICAL_TIME = re.compile(r"T(\d{2})(\d{2})(\d{2})")


def _to_time(hour: int, minute: int = 0, ampm: str | None = None) -> time | None:
    if ampm:
        ampm = ampm.lower()
        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
    if 0 <= hour < 24 and 0 <= minute < 60:
        return time(hour, minute)
    return None


def times_in(text: str) -> set[time]:
    """Every clock time written in the text: 19:30, 7pm, 5:30pm, 19 Uhr, 18h, 14 bis 17 Uhr,
    and iCal's T190000."""
    found: set[time | None] = set()
    for h, m, suffix in _HHMM.findall(text):
        found.add(_to_time(int(h), int(m), suffix if suffix.lower() in ("am", "pm") else None))
    for h, ampm in _H_AMPM.findall(text):
        found.add(_to_time(int(h), 0, ampm))
    for h in _H_UHR.findall(text):
        found.add(_to_time(int(h)))
    for start, end in _RANGE_UHR.findall(text):
        found.update({_to_time(int(start)), _to_time(int(end))})
    for h, m, _ in _ICAL_TIME.findall(text):
        found.add(_to_time(int(h), int(m)))
    return {t for t in found if t is not None}


_AMOUNT = re.compile(
    r"(?:(\d+(?:[.,]\d{1,2})?)\s*(?:€|eur\b|euro\b))|(?:(?:€|eur\b)\s*(\d+(?:[.,]\d{1,2})?))",
    re.IGNORECASE,
)
_FREE_WORDS = re.compile(
    r"\b(free|kostenlos|kostenfrei|gratis|umsonst|eintritt frei|no entry fee|"
    r"donation|spende|spenden)\b",
    re.IGNORECASE,
)


def prices_in(text: str) -> set[float]:
    """Amounts in euros (15 €, 5 EUR, € 8, 12,50 €), and 0 for "free"/"kostenlos"/donation."""
    found = {float((a or b).replace(",", ".")) for a, b in _AMOUNT.findall(text)}
    if _FREE_WORDS.search(text):
        found.add(0.0)
    return found


_DATE_NUMERIC = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b")
_DATE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DATE_WORDS = re.compile(r"\b(\d{1,2})\.?\s+([a-zäöü]+)\.?\s+(\d{4})\b", re.IGNORECASE)


def dates_in(text: str) -> set[date]:
    """Dates written as 14.03.2026, 2026-03-14, 14 March 2026 or 14. März 2026."""
    found: set[date] = set()
    candidates = [(int(y), int(m), int(d)) for d, m, y in _DATE_NUMERIC.findall(text)]
    candidates += [(int(y), int(m), int(d)) for y, m, d in _DATE_ISO.findall(text)]
    for d, month, y in _DATE_WORDS.findall(text):
        if month.casefold() in MONTHS:
            candidates.append((int(y), MONTHS[month.casefold()], int(d)))
    for y, m, d in candidates:
        try:
            found.add(date(y, m, d))
        except ValueError:
            continue
    return found


def _norm(text: str) -> str:
    return normalise_whitespace(text).casefold()


# ---------------------------------------------------------------------------
# Field checks
# ---------------------------------------------------------------------------

# Values that must appear word for word in their quote. first_timer_info is here too: it
# is shown to users as advice, so the model may not paraphrase or add to it (rule 2).
TEXT_FIELDS = {"title", "place_name", "address", "recurrence_text", "seasonal_text",
               "organiser_contact", "first_timer_info"}  # fmt: skip
JUDGEMENT_FIELDS = {"category", "language", "come_alone", "beginner_friendly", "group_size",
                    "price_period"}  # fmt: skip
TIME_FIELDS = {"start_time", "end_time"}


class Unsupported(ValueError):
    """The value is not supported by its span (the reason is the message)."""


def _support(name: str, value: Any, span: str, config: CityConfig) -> Any:
    """Return the accepted (typed) value, or raise Unsupported with a reason."""
    if name in TEXT_FIELDS:
        # A full stop added at the end ("Bring your own mat.") doesn't change the words.
        if not isinstance(value, str) or _norm(value.strip(" .,;:!?")) not in _norm(span):
            raise Unsupported("value does not appear in its source_text")
        return value
    if name in TIME_FIELDS:
        try:
            parsed = time.fromisoformat(str(value))
        except ValueError as exc:
            raise Unsupported(f"not a time: {value!r}") from exc
        if parsed not in times_in(span):
            raise Unsupported("time not found in its source_text")
        return parsed
    if name == "price_eur":
        try:
            amount = float(value)
        except (TypeError, ValueError) as exc:
            raise Unsupported(f"not a price: {value!r}") from exc
        if amount not in prices_in(span):
            raise Unsupported("price not found in its source_text")
        return amount
    if name == "source_updated_at":
        try:
            parsed_date = date.fromisoformat(str(value))
        except ValueError as exc:
            raise Unsupported(f"not a date: {value!r}") from exc
        if parsed_date not in dates_in(span):
            raise Unsupported("date not found in its source_text")
        return parsed_date
    if name == "district":
        districts = config.districts_for(str(value))
        if len(districts) > 1:
            names = " or ".join(d.name for d in districts)
            raise Unsupported(f"'{value}' could be {names}")
        if not districts:
            raise Unsupported(f"'{value}' is not a known district or neighbourhood")
        district = districts[0]
        if not any(_norm(n) in _norm(span) for n in [district.name, *district.aliases]):
            raise Unsupported("district name does not appear in its source_text")
        return district.name
    if name in ("come_alone", "beginner_friendly") and isinstance(value, str):
        # The schema sends booleans as "true"/"false" (no union types allowed).
        if value.lower() not in ("true", "false"):
            raise Unsupported(f"not true/false: {value!r}")
        return value.lower() == "true"
    if name in JUDGEMENT_FIELDS:
        return value  # span grounding only; type checked by ListingDraft
    raise Unsupported(f"unknown field {name}")


def _evidence(span: str, ctx: GroundingContext) -> Evidence:
    return Evidence(
        source_id=ctx.source_id,
        raw_record_id=ctx.raw_record_id,
        source_text=span,
        url=ctx.url,
        captured_at=ctx.captured_at,
    )


class GroundingContext(BaseModel):
    """Everything grounding needs besides the claims."""

    document: str
    source_id: str
    raw_record_id: str
    url: str | None = None
    captured_at: datetime
    config: CityConfig


def ground_field(name: str, claim: ClaimedField | None, ctx: GroundingContext) -> dict[str, Any]:
    """One field -> ExtractedField data (ok with evidence, or flagged with a reason)."""
    if claim is None or (claim.value is None and not claim.source_text):
        return {"status": "flagged", "reason": "not stated"}
    span = claim.source_text
    if not span or not contains_span(ctx.document, span):
        return {"status": "flagged", "reason": "source_text not found in the document"}
    evidence = _evidence(span, ctx)
    if claim.value is None:
        return {"status": "flagged", "reason": claim.note or "stated but unclear",
                "evidence": evidence}  # fmt: skip
    try:
        value = _support(name, claim.value, span, ctx.config)
    except Unsupported as exc:
        return {"status": "flagged", "reason": str(exc), "evidence": evidence}
    return {"status": "ok", "value": value, "evidence": evidence}


# ---------------------------------------------------------------------------
# Flags, decided by code
# ---------------------------------------------------------------------------

# Instruction-like text aimed at a system (EN + DE). A backstop for the model's own report.
INJECTION_PATTERNS = re.compile(
    r"ignore\s+(?:all\s+|any\s+)?(?:previous|prior|above|earlier)\s+instructions"
    r"|disregard\s+(?:all\s+|the\s+)?(?:previous|prior|above)"
    r"|(?:rate|score|rank)\s+this\s+(?:listing|event|place)"
    r"|put\s+it\s+first|mark\s+it\s+as\s+verified"
    r"|system\s+prompt|you\s+are\s+now\s+"
    r"|ignorier(?:e|en)?\s+(?:alle\s+)?(?:vorherigen|bisherigen|obigen)\s+anweisungen",
    re.IGNORECASE,
)
# Flags are listed in the order models.Flag declares them, so drafts compare stably.
FLAG_ORDER: tuple[Flag, ...] = get_args(Flag)


def _grounded(observations: list[Observation], kind: str, document: str) -> bool:
    return any(o.kind == kind and contains_span(document, o.source_text) for o in observations)


def ground_listing(
    claim: ClaimedListing,
    injection_spans: list[str],
    ctx: GroundingContext,
    freshness_days: int,
) -> ListingDraft:
    fields = {name: ground_field(name, claim.fields.get(name), ctx) for name in DRAFT_FIELDS}
    flags: set[Flag] = set()

    # Recurrence: code reads the phrase (recurrence.py), not the model.
    rec = fields["recurrence_text"]
    phrase = rec.get("value") or (rec["evidence"].source_text if rec.get("evidence") else None)
    if phrase is None:
        flags.add("not_recurring")  # nothing says it repeats
    else:
        parsed = parse_recurrence(phrase)
        if parsed.status == "not_recurring" or _grounded(claim.observations, "one_off",
                                                         ctx.document):  # fmt: skip
            flags.add("not_recurring")
        elif parsed.status in ("ambiguous", "unparsed"):
            flags.add("ambiguous_recurrence")
        if parsed.status != "ok" and rec["status"] == "ok":
            fields["recurrence_text"] = {"status": "flagged", "reason": parsed.reason,
                                         "evidence": rec["evidence"]}  # fmt: skip

    if fields["start_time"]["status"] != "ok":
        flags.add("missing_time")

    updated = fields["source_updated_at"]
    if updated["status"] == "ok":
        if (ctx.captured_at.date() - updated["value"]).days > freshness_days:
            flags.add("stale")

    if (
        INJECTION_PATTERNS.search(ctx.document)
        or any(contains_span(ctx.document, s) for s in injection_spans)
        or _grounded(claim.observations, "suspected_injection", ctx.document)
    ):
        flags.add("suspected_injection")
    if _grounded(claim.observations, "cancelled", ctx.document):
        flags.add("cancelled")
    if _grounded(claim.observations, "uncertain_source", ctx.document):
        flags.add("uncertain_source")

    draft_flags = [f for f in FLAG_ORDER if f in flags]
    try:
        return _build_draft(fields, draft_flags, ctx)
    except ValidationError as exc:
        # A value of the wrong type (e.g. category "party"): flag that field, keep the rest.
        for err in exc.errors():
            name = str(err["loc"][0]) if err["loc"] else ""
            if name in fields:
                fields[name] = {"status": "flagged", "reason": "value has the wrong type",
                                "evidence": fields[name].get("evidence")}  # fmt: skip
        return _build_draft(fields, draft_flags, ctx)


def _build_draft(
    fields: dict[str, dict[str, Any]], flags: list[Flag], ctx: GroundingContext
) -> ListingDraft:
    return ListingDraft.model_validate(
        {
            "raw_record_id": ctx.raw_record_id,
            "source_id": ctx.source_id,
            "extracted_at": ctx.captured_at,
            **fields,
            "flags": flags,
        }
    )


ListingOutcome = Literal["publishable", "needs_review", "reject"]


def outcome(draft: ListingDraft) -> ListingOutcome:
    """Where a draft goes: rejected (out of scope), curator queue, or ready for a curator's
    quick approval. Nothing is published automatically in any case."""
    if {"not_recurring", "cancelled"} & set(draft.flags):
        return "reject"
    if draft.flags or draft.place_name.status != "ok" or draft.recurrence_text.status != "ok":
        return "needs_review"
    return "publishable"


__all__ = [
    "ClaimedExtraction",
    "ClaimedField",
    "ClaimedListing",
    "GroundingContext",
    "Observation",
    "dates_in",
    "ground_listing",
    "outcome",
    "prices_in",
    "times_in",
]
