"""The data contracts enforce rules 2 and 3 of CLAUDE.md at construction time."""

from __future__ import annotations

from datetime import datetime, time

import pytest
from pydantic import ValidationError

from morehere.models import (
    Evidence,
    ExtractedField,
    Listing,
    RawRecord,
    Schedule,
    ScheduleBreak,
    Tag,
    sha256_text,
)

NOW = datetime(2026, 11, 12, 9, 0)


def make_evidence(text: str = "Every Tuesday from 7pm") -> Evidence:
    return Evidence(source_id="src-test", raw_record_id="raw-1", source_text=text, captured_at=NOW)


# --- ExtractedField: grounded or flagged -----------------------------------


def test_ok_field_with_value_and_evidence_is_valid() -> None:
    field = ExtractedField[str](value="Café Lindwurm", evidence=make_evidence(), status="ok")
    assert field.value == "Café Lindwurm"


def test_ok_field_without_evidence_is_rejected() -> None:
    with pytest.raises(ValidationError, match="needs evidence"):
        ExtractedField[str](value="Café Lindwurm", status="ok")


def test_ok_field_without_value_is_rejected() -> None:
    with pytest.raises(ValidationError, match="needs a value"):
        ExtractedField[str](evidence=make_evidence(), status="ok")


def test_flagged_field_must_not_keep_a_value() -> None:
    with pytest.raises(ValidationError, match="never guess"):
        ExtractedField[str](value="19:00", status="flagged", reason="ambiguous")


def test_flagged_field_needs_a_reason() -> None:
    with pytest.raises(ValidationError, match="needs a reason"):
        ExtractedField[str](status="flagged")


def test_flagged_field_may_point_at_the_problem_text() -> None:
    field = ExtractedField[str](
        status="flagged", reason="contributor is unsure", evidence=make_evidence("free i think?")
    )
    assert field.value is None


def test_typed_field_parses_its_value() -> None:
    field = ExtractedField[time](value="19:30", evidence=make_evidence(), status="ok")
    assert field.value == time(19, 30)


def test_typed_field_rejects_a_value_of_the_wrong_type() -> None:
    with pytest.raises(ValidationError):
        ExtractedField[time](value="seven-ish", evidence=make_evidence(), status="ok")


# --- Tag: no evidence, no tag ----------------------------------------------


def test_tag_requires_evidence() -> None:
    with pytest.raises(ValidationError):
        Tag(name="beginners welcome")  # type: ignore[call-arg]


def test_tag_with_evidence_is_valid() -> None:
    tag = Tag(name="beginners welcome", evidence=make_evidence("Beginners welcome"))
    assert tag.evidence.source_text == "Beginners welcome"


# --- RawRecord ---------------------------------------------------------------


def test_raw_record_hash_must_match_payload() -> None:
    payload = "BEGIN:VCALENDAR\nEND:VCALENDAR\n"
    record = RawRecord(
        raw_record_id="raw-1",
        source_id="src-test",
        fetched_at=NOW,
        sha256=sha256_text(payload),
        content_type="text/calendar",
        payload=payload,
    )
    assert record.sha256 == sha256_text(payload)

    with pytest.raises(ValidationError, match="does not match"):
        RawRecord(
            raw_record_id="raw-1",
            source_id="src-test",
            fetched_at=NOW,
            sha256=sha256_text("something else"),
            content_type="text/calendar",
            payload=payload,
        )


# --- Schedule ----------------------------------------------------------------


def test_schedule_rejects_rrule_prefix() -> None:
    with pytest.raises(ValidationError, match="FREQ="):
        Schedule(rrule="RRULE:FREQ=WEEKLY;BYDAY=TU", dtstart=datetime(2026, 9, 8, 19, 0))


def test_schedule_rejects_timezone_aware_dtstart() -> None:
    from datetime import UTC

    with pytest.raises(ValidationError, match="naive"):
        Schedule(rrule="FREQ=WEEKLY;BYDAY=TU", dtstart=datetime(2026, 9, 8, 19, 0, tzinfo=UTC))


def test_schedule_break_months_must_be_valid() -> None:
    assert ScheduleBreak(label="Sommerpause", months=[8]).months == [8]
    with pytest.raises(ValidationError):
        ScheduleBreak(label="bad", months=[13])


# --- Listing -----------------------------------------------------------------


def _listing(**overrides: object) -> Listing:
    base: dict[str, object] = {
        "listing_id": "lst-1",
        "title": "Tandem Tuesday",
        "place_id": "plc-1",
        "category": "language_exchange",
    }
    base.update(overrides)
    return Listing.model_validate(base)


def test_draft_listing_needs_little() -> None:
    assert _listing().status == "draft"


def test_published_listing_needs_evidenced_schedule_and_verification() -> None:
    schedule = Schedule(rrule="FREQ=WEEKLY;BYDAY=TU", dtstart=datetime(2026, 9, 8, 19, 0))

    with pytest.raises(ValidationError, match="schedule backed by evidence"):
        _listing(status="published", schedule=schedule, last_verified_at=NOW, source_ids=["s"])

    with pytest.raises(ValidationError, match="last_verified_at"):
        _listing(
            status="published",
            schedule=schedule,
            field_evidence={"schedule": make_evidence()},
            source_ids=["s"],
        )

    published = _listing(
        status="published",
        schedule=schedule,
        field_evidence={"schedule": make_evidence()},
        last_verified_at=NOW,
        source_ids=["src-test"],
    )
    assert published.status == "published"


def test_unknown_keys_are_rejected() -> None:
    with pytest.raises(ValidationError):
        _listing(colour="blue")
