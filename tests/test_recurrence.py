"""Recurrence parsing, seasonal breaks, occurrences and round trips."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pytest

from morehere.golden import load_golden
from morehere.models import Schedule, ScheduleBreak
from morehere.recurrence import (
    build_schedule,
    describe,
    infer_rrule,
    next_occurrences,
    parse_recurrence,
    parse_seasonal,
)

GOLDEN = load_golden()


# --- Phrases -> RRULE --------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "rrule"),
    [
        ("every Tuesday", "FREQ=WEEKLY;BYDAY=TU"),
        ("jeden Dienstag", "FREQ=WEEKLY;BYDAY=TU"),
        ("dienstags", "FREQ=WEEKLY;BYDAY=TU"),
        ("on Tuesdays", "FREQ=WEEKLY;BYDAY=TU"),
        ("every wed", "FREQ=WEEKLY;BYDAY=WE"),
        ("wöchentlich am Donnerstag", "FREQ=WEEKLY;BYDAY=TH"),
        ("every Monday and Thursday", "FREQ=WEEKLY;BYDAY=MO,TH"),
        ("jeden Donnerstag und Montag", "FREQ=WEEKLY;BYDAY=MO,TH"),
        ("every first Monday of the month", "FREQ=MONTHLY;BYDAY=1MO"),
        ("jeden 1. Montag im Monat", "FREQ=MONTHLY;BYDAY=1MO"),
        ("Jeden 2. Donnerstag im Monat", "FREQ=MONTHLY;BYDAY=2TH"),
        ("jeden zweiten Freitag im Monat", "FREQ=MONTHLY;BYDAY=2FR"),
        ("the second Sunday of every month", "FREQ=MONTHLY;BYDAY=2SU"),
        ("every third Saturday", "FREQ=MONTHLY;BYDAY=3SA"),
        ("every last Friday of the month", "FREQ=MONTHLY;BYDAY=-1FR"),
        ("jeden letzten Freitag im Monat", "FREQ=MONTHLY;BYDAY=-1FR"),
        # decision M4: "second" without "of the month" means every other week
        ("jeden zweiten Freitag", "FREQ=WEEKLY;INTERVAL=2;BYDAY=FR"),
        ("every second Friday", "FREQ=WEEKLY;INTERVAL=2;BYDAY=FR"),
        ("every other Friday", "FREQ=WEEKLY;INTERVAL=2;BYDAY=FR"),
        ("alle zwei Wochen freitags", "FREQ=WEEKLY;INTERVAL=2;BYDAY=FR"),
        ("zweiwöchentlich am Mittwoch", "FREQ=WEEKLY;INTERVAL=2;BYDAY=WE"),
        ("RRULE:FREQ=WEEKLY;BYDAY=WE", "FREQ=WEEKLY;BYDAY=WE"),
    ],
)
def test_parse_recurrence(text: str, rrule: str) -> None:
    result = parse_recurrence(text)
    assert (result.status, result.rrule) == ("ok", rrule)


@pytest.mark.parametrize(
    ("text", "status"),
    [
        ("We play biweekly on Saturdays at 14:00", "ambiguous"),
        ("One night only: Saturday 21 November, 5:30pm", "not_recurring"),
        ("This is a one-time event.", "not_recurring"),
        ("Saturday 12 December 2026, 6pm", "not_recurring"),
        ("monthly meetup", "unparsed"),
        ("every month on a Friday", "unparsed"),  # which Friday?
        ("RRULE:FREQ=SOMETIMES", "unparsed"),
    ],
)
def test_unclear_phrases_get_no_rule_and_a_reason(text: str, status: str) -> None:
    result = parse_recurrence(text)
    assert result.rrule is None
    assert result.status == status
    assert result.reason


def test_every_golden_recurrence_phrase_gives_its_expected_rrule() -> None:
    checked = 0
    for _, listing in GOLDEN.all_listings():
        label = listing.fields.get("recurrence_text")
        if label is None:
            continue
        result = parse_recurrence(label.value if label.flagged is None else label.source_text)
        assert result.rrule == listing.expected_rrule, listing.key
        checked += 1
    assert checked == 25


# --- Seasonal text -> breaks -------------------------------------------------


def test_golden_seasonal_text_gives_expected_breaks() -> None:
    for _, listing in GOLDEN.all_listings():
        label = listing.fields.get("seasonal_text")
        if label is None or label.flagged is not None:
            continue
        assert parse_seasonal(label.value) == listing.expected_breaks, listing.key


@pytest.mark.parametrize(
    ("text", "breaks"),
    [
        ("Sommerpause im August.", [ScheduleBreak(label="Sommerpause", months=[8])]),
        ("closed in July and August", [ScheduleBreak(label="Closed", months=[7, 8])]),
        ("summer break July to August", [ScheduleBreak(label="Summer break", months=[7, 8])]),
        (
            "Von April bis Oktober",
            [ScheduleBreak(label="Winterpause", months=[11, 12, 1, 2, 3])],
        ),
        (
            "from October to March",
            [ScheduleBreak(label="Summer break", months=[4, 5, 6, 7, 8, 9])],
        ),
        ("No quiz on 23 and 30 December.", []),  # specific dates are EXDATEs, not breaks
        ("Bring your own mat.", []),
    ],
)
def test_parse_seasonal(text: str, breaks: list[ScheduleBreak]) -> None:
    assert parse_seasonal(text) == breaks


# --- Schedules and occurrences -----------------------------------------------


def test_build_schedule_starts_at_first_occurrence_and_computes_duration() -> None:
    schedule = build_schedule(
        "FREQ=MONTHLY;BYDAY=2TH", time(19, 0), on_or_after=date(2026, 11, 13), end_time=time(22)
    )
    assert schedule.dtstart == datetime(2026, 12, 10, 19, 0)  # 2nd Thursday of December
    assert schedule.duration_min == 180


def test_duration_past_midnight() -> None:
    schedule = build_schedule(
        "FREQ=WEEKLY;BYDAY=FR", time(22, 0), on_or_after=date(2026, 11, 1), end_time=time(1, 0)
    )
    assert schedule.duration_min == 180


def test_occurrences_keep_wall_clock_time_across_daylight_saving() -> None:
    schedule = build_schedule("FREQ=WEEKLY;BYDAY=TU", time(19, 0), on_or_after=date(2026, 10, 1))
    before, after = next_occurrences(schedule, datetime(2026, 10, 19, tzinfo=UTC), count=2)
    # DST ends on 25 Oct 2026: 19:00 local is 17:00 UTC before, 18:00 UTC after.
    assert (before.hour, before.astimezone(UTC).hour) == (19, 17)
    assert (after.hour, after.astimezone(UTC).hour) == (19, 18)


def test_occurrences_skip_exdates_and_break_months() -> None:
    schedule = Schedule(
        rrule="FREQ=WEEKLY;BYDAY=WE",
        dtstart=datetime(2026, 7, 1, 19, 30),
        exdates=[date(2026, 9, 2)],
        breaks=[ScheduleBreak(label="Sommerpause", months=[8])],
    )
    dates = [d.date() for d in next_occurrences(schedule, datetime(2026, 7, 25), count=3)]
    assert dates == [date(2026, 7, 29), date(2026, 9, 9), date(2026, 9, 16)]


def test_occurrences_terminate_when_every_month_is_a_break() -> None:
    schedule = Schedule(
        rrule="FREQ=WEEKLY;BYDAY=WE",
        dtstart=datetime(2026, 1, 7, 19, 0),
        breaks=[ScheduleBreak(label="never", months=list(range(1, 13)))],
    )
    assert next_occurrences(schedule, datetime(2026, 1, 1), count=3) == []


def test_seasonal_garden_has_no_saturdays_in_november() -> None:
    schedule = build_schedule(
        "FREQ=WEEKLY;BYDAY=SA",
        time(10, 0),
        on_or_after=date(2026, 4, 1),
        breaks=parse_seasonal("Von April bis Oktober"),
    )
    first = next_occurrences(schedule, datetime(2026, 11, 12), count=1)[0]
    assert first.date() == date(2027, 4, 3)


# --- RRULE -> words -> RRULE (rule 6) ----------------------------------------

ROUND_TRIP_RULES = [
    "FREQ=WEEKLY;BYDAY=TU",
    "FREQ=WEEKLY;BYDAY=MO,TH",
    "FREQ=WEEKLY;INTERVAL=2;BYDAY=FR",
    "FREQ=MONTHLY;BYDAY=1MO",
    "FREQ=MONTHLY;BYDAY=2TH",
    "FREQ=MONTHLY;BYDAY=3SA",
    "FREQ=MONTHLY;BYDAY=-1FR",
]


@pytest.mark.parametrize("rrule", ROUND_TRIP_RULES)
@pytest.mark.parametrize("lang", ["en", "de"])
def test_describe_round_trips(rrule: str, lang: str) -> None:
    words = describe(rrule, lang)  # type: ignore[arg-type]
    assert words != rrule
    assert parse_recurrence(words).rrule == rrule


def test_describe_examples() -> None:
    assert describe("FREQ=MONTHLY;BYDAY=2TH", "de") == "jeden 2. Donnerstag im Monat"
    assert describe("FREQ=MONTHLY;BYDAY=-1FR", "en") == "every last Friday of the month"
    assert describe("FREQ=WEEKLY;INTERVAL=2;BYDAY=FR", "en") == "every other Friday"
    assert describe("FREQ=DAILY", "en") == "FREQ=DAILY"  # unsupported: shown as is


# --- Inferring a rule from dated occurrences ---------------------------------


def _series(first: datetime, step_days: int, n: int) -> list[datetime]:
    return [first + timedelta(days=step_days * i) for i in range(n)]


def test_infer_weekly_biweekly_and_monthly() -> None:
    tue = datetime(2026, 10, 13, 19, 0)
    assert infer_rrule(_series(tue, 7, 4)) == "FREQ=WEEKLY;BYDAY=TU"
    assert infer_rrule(_series(tue, 14, 4)) == "FREQ=WEEKLY;INTERVAL=2;BYDAY=TU"
    third_saturdays = [datetime(2026, m, d, 14) for m, d in [(9, 19), (10, 17), (11, 21)]]
    assert infer_rrule(third_saturdays) == "FREQ=MONTHLY;BYDAY=3SA"
    last_fridays = [datetime(2026, m, d, 19) for m, d in [(9, 25), (10, 30), (11, 27)]]
    assert infer_rrule(last_fridays) == "FREQ=MONTHLY;BYDAY=-1FR"


def test_infer_tolerates_one_skipped_week() -> None:
    starts = [datetime(2026, 10, d, 19) for d in (6, 13, 27)] + [datetime(2026, 11, 3, 19)]
    assert infer_rrule(starts) == "FREQ=WEEKLY;BYDAY=TU"


def test_infer_refuses_irregular_or_too_short_series() -> None:
    assert infer_rrule(_series(datetime(2026, 10, 13, 19), 7, 2)) is None  # only twice
    assert infer_rrule([datetime(2026, 10, d, 18) for d in (5, 14, 22)]) is None  # weekdays vary
    varying_time = [
        datetime(2026, 10, 6, 19),
        datetime(2026, 10, 13, 20),
        datetime(2026, 10, 20, 19),
    ]
    assert infer_rrule(varying_time) is None
