"""Curator actions: approve, verify, edit, fix the place, merge, hide, reject, add from text.

Two layers:
- pure functions that take a Listing and return the changed Listing (plus, for edits, the
  raw record that is the edit's source). They're what the tests exercise.
- `Curator`, which loads a listing, applies one action, saves listing + records, and writes
  the audit log (curator_actions) in one transaction. The Streamlit app only calls this.

Rule 2 applies to people too: a curator's edit is a fact, so it is stored as a raw record
("Selim, 2026-11-15: start_time = 19:30. Confirmed by phone.") from the `curator` source,
and the new value's evidence quotes it. Drafts are never changed: they keep what the model
extracted, so corrections can be measured (curation report).

Run the report: python -m morehere.curation report
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, time
from typing import Any

from pydantic import ValidationError
from sqlalchemy import Engine

from morehere.config import CityConfig
from morehere.db import repo
from morehere.db.session import session_scope
from morehere.merge import merge
from morehere.models import Evidence, GeoPoint, Listing, RawRecord, sha256_text
from morehere.promote import finish
from morehere.recurrence import build_schedule, parse_recurrence, parse_seasonal

CURATOR_SOURCE = "curator"

EDITABLE_FIELDS = (
    "title",
    "category",
    "language",
    "price_eur",
    "price_period",
    "come_alone",
    "beginner_friendly",
    "group_size",
    "first_timer_info",
    "organiser_contact",
)


class CurationError(ValueError):
    """The action can't be done (e.g. publishing without a schedule). Message says why."""


# ---------------------------------------------------------------------------
# Curator evidence
# ---------------------------------------------------------------------------


def curator_record(curator: str, now: datetime, statement: str, note: str = "") -> RawRecord:
    """A curator's statement as a raw record, so it can be quoted as evidence."""
    payload = f"{curator}, {now.date().isoformat()}: {statement}."
    if note.strip():
        payload += f" {note.strip()}"
    digest = sha256_text(payload + now.isoformat())
    return RawRecord(
        raw_record_id=f"curator-{digest[:16]}",
        source_id=CURATOR_SOURCE,
        fetched_at=now,
        sha256=sha256_text(payload),
        content_type="text/plain",
        payload=payload,
    )


def _evidence(record: RawRecord, quote: str) -> Evidence:
    return Evidence(
        source_id=CURATOR_SOURCE,
        raw_record_id=record.raw_record_id,
        source_text=quote,
        captured_at=record.fetched_at,
    )


def _with_curator_source(listing: Listing) -> list[str]:
    return sorted(set(listing.source_ids) | {CURATOR_SOURCE})


# ---------------------------------------------------------------------------
# Pure actions
# ---------------------------------------------------------------------------


def edit_field(
    listing: Listing, field: str, value: Any, curator: str, now: datetime, note: str = ""
) -> tuple[Listing, RawRecord | None]:
    """Set (or clear, with None) one field. The value is type-checked by the Listing model."""
    if field not in EDITABLE_FIELDS:
        raise CurationError(f"{field} can't be edited here")
    evidence = dict(listing.field_evidence)
    if value is None or value == "":
        if field == "title":
            raise CurationError("a listing needs a title")
        evidence.pop(field, None)
        try:
            changed = Listing.model_validate(
                {**listing.model_dump(), field: None, "field_evidence": evidence}
            )
        except ValidationError as exc:
            raise CurationError(f"{field} can't be empty") from exc
        return changed, None
    statement = f"{field} = {value!r}"
    record = curator_record(curator, now, statement, note)
    evidence[field] = _evidence(record, statement)
    try:
        changed = Listing.model_validate(
            {
                **listing.model_dump(),
                field: value,
                "field_evidence": evidence,
                "source_ids": _with_curator_source(listing),
            }
        )
    except ValidationError as exc:
        raise CurationError(f"not a valid {field}: {value!r}") from exc
    return changed, record


def edit_schedule(
    listing: Listing,
    phrase: str,
    start: time,
    end: time | None,
    seasonal: str,
    curator: str,
    now: datetime,
    note: str = "",
) -> tuple[Listing, RawRecord]:
    """Set the schedule from a phrase ("jeden 2. Donnerstag im Monat") and times."""
    parsed = parse_recurrence(phrase)
    if parsed.rrule is None:
        raise CurationError(f"can't read {phrase!r}: {parsed.reason}")
    schedule = build_schedule(
        parsed.rrule,
        start,
        on_or_after=now.date(),
        end_time=end,
        breaks=parse_seasonal(seasonal) if seasonal.strip() else [],
    )
    times = f"{start:%H:%M}" + (f"-{end:%H:%M}" if end else "")
    statement = f"schedule = {phrase!r} at {times}" + (f", {seasonal!r}" if seasonal else "")
    record = curator_record(curator, now, statement, note)
    evidence = {**listing.field_evidence, "schedule": _evidence(record, statement)}
    notes = [n for n in listing.review_notes if not n.startswith("no schedule yet")]
    changed = listing.model_copy(
        update={
            "schedule": schedule,
            "field_evidence": evidence,
            "review_notes": notes,
            "source_ids": _with_curator_source(listing),
        }
    )
    return changed, record


def approve(listing: Listing, now: datetime) -> Listing:
    """Publish: the curator checked the listing. Counts as verification."""
    if listing.schedule is None or "schedule" not in listing.field_evidence:
        raise CurationError("set a schedule before publishing")
    try:
        return Listing.model_validate(
            {**listing.model_dump(), "status": "published", "last_verified_at": now}
        )
    except ValidationError as exc:
        raise CurationError(f"can't publish: {exc.errors()[0]['msg']}") from exc


def verify(listing: Listing, now: datetime) -> Listing:
    """ "I checked it's still on": refresh last_verified_at without other changes."""
    return listing.model_copy(update={"last_verified_at": now})


def hide(listing: Listing, reason: str, now: datetime) -> Listing:
    if not reason.strip():
        raise CurationError("say why it's hidden")
    note = f"hidden by curator on {now.date().isoformat()}: {reason.strip()}"
    return listing.model_copy(
        update={"status": "hidden", "review_notes": [*listing.review_notes, note]}
    )


def set_place(listing: Listing, place_id: str) -> Listing:
    return listing.model_copy(update={"place_id": place_id})


def merge_into(
    keep: Listing, other: Listing, reliability: dict[str, float], now: datetime
) -> tuple[Listing, Listing]:
    """Merge `other` into `keep` (the curator says they're one activity). `other` is hidden
    with a note pointing at `keep`, never deleted."""
    if keep.listing_id == other.listing_id:
        raise CurationError("can't merge a listing with itself")
    merged = merge(keep, other, reliability)
    gone = other.model_copy(
        update={
            "status": "hidden",
            "review_notes": [
                *other.review_notes,
                f"merged into {keep.listing_id} on {now.date().isoformat()}",
            ],
        }
    )
    return merged, gone


# ---------------------------------------------------------------------------
# The database layer the admin uses
# ---------------------------------------------------------------------------


@dataclass
class Curator:
    engine: Engine
    name: str
    config: CityConfig
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    def _apply(
        self,
        listing_id: str,
        action: str,
        change: Callable[[Listing, datetime], tuple[Listing, RawRecord | None]],
        details: dict[str, Any],
    ) -> Listing:
        now = self.clock()
        with session_scope(self.engine) as session:
            listing = repo.get_listing(session, listing_id)
            if listing is None:
                raise CurationError(f"no listing {listing_id}")
            changed, record = change(listing, now)
            if record is not None:
                repo.save_raw_record(session, record)
            changed = finish(changed, self.config.score_weights)
            repo.save_listing(session, changed)
            repo.log_action(session, self.name, action, listing_id, details)
        return changed

    def edit_field(self, listing_id: str, field: str, value: Any, note: str = "") -> Listing:
        return self._apply(
            listing_id,
            "edit_field",
            lambda lst, now: edit_field(lst, field, value, self.name, now, note),
            {"field": field, "value": value, "note": note},
        )

    def edit_schedule(
        self,
        listing_id: str,
        phrase: str,
        start: time,
        end: time | None,
        seasonal: str = "",
        note: str = "",
    ) -> Listing:
        return self._apply(
            listing_id,
            "edit_schedule",
            lambda lst, now: edit_schedule(lst, phrase, start, end, seasonal, self.name, now, note),
            {
                "phrase": phrase,
                "start": str(start),
                "end": str(end),
                "seasonal": seasonal,
                "note": note,
            },
        )

    def approve(self, listing_id: str) -> Listing:
        return self._apply(listing_id, "approve", lambda lst, now: (approve(lst, now), None), {})

    def verify(self, listing_id: str, note: str = "") -> Listing:
        return self._apply(
            listing_id, "verify", lambda lst, now: (verify(lst, now), None), {"note": note}
        )

    def hide(self, listing_id: str, reason: str) -> Listing:
        return self._apply(
            listing_id, "hide", lambda lst, now: (hide(lst, reason, now), None), {"reason": reason}
        )

    def set_place(self, listing_id: str, place_id: str) -> Listing:
        return self._apply(
            listing_id,
            "set_place",
            lambda lst, now: (set_place(lst, place_id), None),
            {"place_id": place_id},
        )

    def set_coordinates(self, place_id: str, lat: float, lon: float) -> None:
        with session_scope(self.engine) as session:
            place = repo.get_place(session, place_id)
            if place is None:
                raise CurationError(f"no place {place_id}")
            point = GeoPoint(lat=lat, lon=lon)
            district = repo.district_at(session, point) or place.district
            repo.save_place(session, place.model_copy(update={"geo": point, "district": district}))
            repo.log_action(
                session,
                self.name,
                "set_coordinates",
                None,
                {"place_id": place_id, "lat": lat, "lon": lon},
            )

    def merge(self, keep_id: str, other_id: str) -> Listing:
        now = self.clock()
        with session_scope(self.engine) as session:
            keep = repo.get_listing(session, keep_id)
            other = repo.get_listing(session, other_id)
            if keep is None or other is None:
                raise CurationError("both listings must exist")
            reliability = {s.source_id: s.reliability for s in repo.list_sources(session)}
            merged, gone = merge_into(keep, other, reliability, now)
            merged = finish(merged, self.config.score_weights)
            repo.save_listing(session, merged)
            repo.save_listing(session, gone)
            repo.log_action(session, self.name, "merge", keep_id, {"merged": other_id})
        return merged


# ---------------------------------------------------------------------------
# Add from text (how the first 60 get curated)
# ---------------------------------------------------------------------------


def add_from_text(
    engine: Engine,
    text: str,
    url: str | None,
    curator_name: str,
    backend: Any,
    settings: Any,
    config: CityConfig,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Store pasted text as a raw record, extract it, promote the drafts. Returns counts."""
    from morehere.extract import extract_record
    from morehere.promote import promote_pending

    if not text.strip():
        raise CurationError("paste some text first")
    now = now or datetime.now(UTC)
    digest = sha256_text(text)
    raw = RawRecord(
        raw_record_id=f"pasted-{digest[:16]}",
        source_id="pasted-links",
        fetched_at=now,
        sha256=digest,
        content_type="text/plain",
        url=url or None,
        payload=text,
    )
    with session_scope(engine) as session:
        stored, created = repo.save_raw_record(session, raw)
    if not created:
        raise CurationError("this exact text was added before")
    result = extract_record(stored, backend, settings, config)
    with session_scope(engine) as session:
        for draft in result.drafts:
            repo.save_draft(session, draft)
        repo.log_action(
            session,
            curator_name,
            "add_from_text",
            None,
            {
                "raw_record_id": stored.raw_record_id,
                "url": url,
                "drafts": len(result.drafts),
                "est_cost_usd": result.est_cost_usd,
            },
        )
    counts = promote_pending(engine, config)
    return {
        "raw_record_id": stored.raw_record_id,
        "drafts": len(result.drafts),
        "est_cost_usd": result.est_cost_usd,
        **counts,
    }


# ---------------------------------------------------------------------------
# Curation report: how often did the curator correct the extractor?
# ---------------------------------------------------------------------------

REPORT_FIELDS = (*EDITABLE_FIELDS, "schedule")


def curation_report(listings: list[Listing]) -> dict[str, Any]:
    """Per field, over published listings: kept as extracted, corrected by the curator,
    or never known. "Held out" = listings from documents outside the golden samples, the
    honest accuracy number (the labels were never tuned on them)."""

    def summarise(group: list[Listing]) -> dict[str, Any]:
        per_field: dict[str, Counter[str]] = {f: Counter() for f in REPORT_FIELDS}
        for listing in group:
            for f in REPORT_FIELDS:
                ev = listing.field_evidence.get(f)
                if ev is None:
                    per_field[f]["unknown"] += 1
                elif ev.source_id == CURATOR_SOURCE:
                    per_field[f]["corrected"] += 1
                else:
                    per_field[f]["kept"] += 1
        rows = {}
        for f, c in per_field.items():
            decided = c["kept"] + c["corrected"]
            rows[f] = {**c, "kept_rate": round(c["kept"] / decided, 3) if decided else None}
        kept = sum(r.get("kept", 0) for r in rows.values())
        corrected = sum(r.get("corrected", 0) for r in rows.values())
        return {
            "listings": len(group),
            "fields": rows,
            "kept_rate": round(kept / (kept + corrected), 3) if kept + corrected else None,
        }

    published = [lst for lst in listings if lst.status == "published"]

    def from_samples(lst: Listing) -> bool:
        return any(e.raw_record_id.startswith("sample-") for e in lst.field_evidence.values())

    return {
        "all": summarise(published),
        "held_out": summarise([lst for lst in published if not from_samples(lst)]),
    }


def main(argv: list[str] | None = None) -> None:
    from morehere.db.session import make_engine

    parser = argparse.ArgumentParser(description="Curation tools.")
    parser.add_argument("command", choices=["report"])
    parser.parse_args(argv)
    with session_scope(make_engine()) as session:
        report = curation_report(repo.list_listings(session))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
