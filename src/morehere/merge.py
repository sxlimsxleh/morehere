"""Duplicates across sources: when two listings are one activity, and how to merge them.

Same activity (decision M6): same place, same schedule rule, start times within 30
minutes. Titles don't decide: the Luma feed says "Tandem Tuesday – English/German
Language Café", the newsletter "Tandem Tuesdays".

Merging keeps, per field, the value from the more reliable source (config/sources.yaml).
Where two sources disagree, the listing gets a review note so a curator sees it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from morehere.models import Evidence, Listing

MAX_START_DIFFERENCE_MIN = 30

# Fields that merge value by value. Title is chosen by reliability too, but differing
# titles are normal and don't produce a review note.
MERGED_FIELDS = (
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
QUIET_FIELDS = {"title", "category"}


def same_activity(a: Listing, b: Listing) -> bool:
    if a.place_id != b.place_id or a.schedule is None or b.schedule is None:
        return False
    if a.schedule.rrule != b.schedule.rrule:
        return False
    minutes = lambda dt: dt.hour * 60 + dt.minute  # noqa: E731
    return abs(minutes(a.schedule.dtstart) - minutes(b.schedule.dtstart)) <= (
        MAX_START_DIFFERENCE_MIN
    )


def _reliability(evidence: Evidence | None, reliability: dict[str, float]) -> float:
    return reliability.get(evidence.source_id, 0.0) if evidence else -1.0


def merge(existing: Listing, new: Listing, reliability: dict[str, float]) -> Listing:
    """One listing from two of the same activity. `existing` keeps its id and status,
    unless a conflict sends it back to review."""
    data = existing.model_dump()
    evidence = dict(existing.field_evidence)
    notes = list(dict.fromkeys(existing.review_notes + new.review_notes))
    conflict = False

    for field in MERGED_FIELDS:
        old_value, new_value = getattr(existing, field), getattr(new, field)
        old_ev, new_ev = existing.field_evidence.get(field), new.field_evidence.get(field)
        if new_value is None:
            continue
        if old_value is None:
            data[field], evidence[field] = new_value, new_ev
            continue
        if old_value == new_value:
            continue
        keep_new = _reliability(new_ev, reliability) > _reliability(old_ev, reliability)
        if field not in QUIET_FIELDS:
            conflict = True
            kept = new_ev if keep_new else old_ev
            notes.append(
                f"conflict on {field}: {old_value!r} ({old_ev.source_id if old_ev else '?'}) vs "
                f"{new_value!r} ({new_ev.source_id if new_ev else '?'}); kept "
                f"{kept.source_id if kept else '?'}"
            )
        if keep_new:
            data[field], evidence[field] = new_value, new_ev

    # The more reliable source's schedule wins too (same rule; dtstart/duration may differ).
    if _reliability(new.field_evidence.get("schedule"), reliability) > _reliability(
        existing.field_evidence.get("schedule"), reliability
    ):
        data["schedule"], evidence["schedule"] = new.schedule, new.field_evidence["schedule"]

    data["field_evidence"] = evidence
    data["source_ids"] = sorted(set(existing.source_ids) | set(new.source_ids))
    data["review_notes"] = notes
    verified = [d for d in (existing.last_verified_at, new.last_verified_at) if d is not None]
    data["last_verified_at"] = max(verified, key=_as_utc) if verified else None
    if conflict and existing.status == "published":
        data["status"] = "needs_review"
    data["tags"], data["regular_score"] = [], None  # recomputed by the caller
    return Listing.model_validate(data)


def _as_utc(value: datetime) -> datetime:
    # Naive times are UTC (as the repository stores them); mixing kinds would raise.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value
