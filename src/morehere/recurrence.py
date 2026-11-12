"""Recurrence: turn schedule phrases into iCal RRULEs, and RRULEs into dates and words.

Rule 1 (the LLM reads, code decides): extraction returns the verbatim phrase
("jeden 2. Donnerstag im Monat"); this module decides what it means. It is a small,
explicit rule-based parser. Anything it cannot read with certainty comes back without
an RRULE and with a reason, and goes to the curator.

Supported (English and German):
    every Tuesday / jeden Dienstag / dienstags / every wed      FREQ=WEEKLY;BYDAY=TU
    every Monday and Thursday                                   FREQ=WEEKLY;BYDAY=MO,TH
    every first Monday of the month / jeden 1. Montag im Monat   FREQ=MONTHLY;BYDAY=1MO
    every last Friday / jeden letzten Freitag im Monat          FREQ=MONTHLY;BYDAY=-1FR
    every other Friday / alle zwei Wochen freitags              FREQ=WEEKLY;INTERVAL=2;BYDAY=FR
    jeden zweiten Freitag (no "im Monat") / every second Friday FREQ=WEEKLY;INTERVAL=2;BYDAY=FR
    jeden zweiten Freitag im Monat                              FREQ=MONTHLY;BYDAY=2FR
    an RRULE (from iCal)                                        passed through after validation
    biweekly                                                    ambiguous: twice a week, or
                                                                every two weeks?
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from dateutil.rrule import rrulestr

from morehere.models import Schedule, ScheduleBreak

RecurrenceStatus = Literal["ok", "ambiguous", "not_recurring", "unparsed"]

WEEKDAYS: dict[str, str] = {}
# "on Tuesdays", "dienstags": a plural/adverbial weekday already means "every week".
PLURAL_WEEKDAYS: set[str] = set()
for code, names in {
    "MO": ["monday", "mon", "montag", "montags"],
    "TU": ["tuesday", "tue", "tues", "dienstag", "dienstags"],
    "WE": ["wednesday", "wed", "mittwoch", "mittwochs"],
    "TH": ["thursday", "thu", "thur", "thurs", "donnerstag", "donnerstags"],
    "FR": ["friday", "fri", "freitag", "freitags"],
    "SA": ["saturday", "sat", "samstag", "samstags", "sonnabend", "sonnabends"],
    "SU": ["sunday", "sun", "sonntag", "sonntags"],
}.items():
    for name in names:
        WEEKDAYS[name] = code
        if name.endswith("day"):  # English full names: tuesday -> tuesdays
            WEEKDAYS[name + "s"] = code
            PLURAL_WEEKDAYS.add(name + "s")
        elif name.endswith("s") and name[:-1] in names:  # German: dienstag -> dienstags
            PLURAL_WEEKDAYS.add(name)
WEEKDAY_ORDER = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]

ORDINALS: dict[str, int] = {
    "first": 1, "1st": 1, "1.": 1, "erste": 1, "ersten": 1, "erster": 1,
    "second": 2, "2nd": 2, "2.": 2, "zweite": 2, "zweiten": 2, "zweiter": 2,
    "third": 3, "3rd": 3, "3.": 3, "dritte": 3, "dritten": 3, "dritter": 3,
    "fourth": 4, "4th": 4, "4.": 4, "vierte": 4, "vierten": 4, "vierter": 4,
    "last": -1, "letzte": -1, "letzten": -1, "letzter": -1,
}  # fmt: skip

MONTHLY_MARKERS = ("of the month", "of every month", "each month", "every month", "im monat",
                   "des monats", "jeden monat", "monthly", "monatlich")  # fmt: skip
EVERY_OTHER_MARKERS = ("every other", "every two weeks", "every 2 weeks", "fortnightly",
                       "alle zwei wochen", "alle 2 wochen", "jede zweite woche",
                       "zweiwöchentlich", "14-tägig", "14tägig", "vierzehntägig")  # fmt: skip
WEEKLY_MARKERS = ("every", "each", "weekly", "jeden", "jede", "jedes", "wöchentlich")
AMBIGUOUS_MARKERS = ("biweekly", "bi-weekly", "bi weekly", "bimonthly", "bi-monthly")
ONE_OFF_MARKERS = ("one night only", "one-time", "one time event", "one-off", "einmalig",
                   "nur einmal", "nur an diesem")  # fmt: skip

_TOKEN = re.compile(r"[a-zäöüß]+|\d+(?:st|nd|rd|th|\.)?", re.IGNORECASE)


@dataclass(frozen=True)
class RecurrenceResult:
    rrule: str | None
    status: RecurrenceStatus
    reason: str | None = None


def _validate_rrule(rrule: str) -> str:
    """Raise ValueError if dateutil cannot read the rule; return it normalised."""
    rrule = rrule.strip().removeprefix("RRULE:").strip()
    rrulestr(rrule, dtstart=datetime(2026, 1, 1))
    return rrule


def parse_recurrence(text: str) -> RecurrenceResult:
    raw = text.strip()
    if raw.upper().startswith(("FREQ=", "RRULE:")):
        try:
            return RecurrenceResult(_validate_rrule(raw), "ok")
        except ValueError as exc:
            return RecurrenceResult(None, "unparsed", f"invalid RRULE: {exc}")

    t = " ".join(raw.casefold().split())
    if any(m in t for m in AMBIGUOUS_MARKERS):
        return RecurrenceResult(
            None, "ambiguous", "'biweekly' can mean twice a week or every two weeks"
        )
    if any(m in t for m in ONE_OFF_MARKERS):
        return RecurrenceResult(None, "not_recurring", "described as a one-off event")

    tokens = _TOKEN.findall(t)
    days: list[str] = []
    for token in tokens:
        day = WEEKDAYS.get(token)
        if day and day not in days:
            days.append(day)
    if not days:
        return RecurrenceResult(None, "unparsed", "no weekday found")

    # An ordinal directly before a weekday: "2. Donnerstag", "last Friday", "zweiten Freitag".
    ordinal: tuple[int, str] | None = None
    for prev, token in zip(tokens, tokens[1:], strict=False):
        if prev in ORDINALS and token in WEEKDAYS:
            ordinal = (ORDINALS[prev], WEEKDAYS[token])
            break

    monthly = any(m in t for m in MONTHLY_MARKERS)
    every_other = any(m in t for m in EVERY_OTHER_MARKERS)
    plural_day = any(token in PLURAL_WEEKDAYS for token in tokens)
    weekly_word = any(token in WEEKLY_MARKERS for token in tokens)
    byday = ",".join(sorted(days, key=WEEKDAY_ORDER.index))

    if ordinal is not None:
        n, day = ordinal
        # "every second Friday" without "of the month" means every other week (decision M4).
        if n == 2 and not monthly:
            return RecurrenceResult(f"FREQ=WEEKLY;INTERVAL=2;BYDAY={day}", "ok")
        return RecurrenceResult(f"FREQ=MONTHLY;BYDAY={n}{day}", "ok")
    if every_other:
        return RecurrenceResult(f"FREQ=WEEKLY;INTERVAL=2;BYDAY={byday}", "ok")
    if monthly:
        return RecurrenceResult(None, "unparsed", "monthly, but which week is not stated")
    if weekly_word or plural_day:
        return RecurrenceResult(f"FREQ=WEEKLY;BYDAY={byday}", "ok")
    return RecurrenceResult(None, "not_recurring", "a weekday without any word for repetition")


# ---------------------------------------------------------------------------
# Seasonal breaks
# ---------------------------------------------------------------------------

MONTHS: dict[str, int] = {}
for number, names in enumerate(
    [
        ["january", "jan", "januar", "jänner"],
        ["february", "feb", "februar"],
        ["march", "mar", "märz", "maerz", "mrz"],
        ["april", "apr"],
        ["may", "mai"],
        ["june", "jun", "juni"],
        ["july", "jul", "juli"],
        ["august", "aug"],
        ["september", "sep", "sept"],
        ["october", "oct", "oktober", "okt"],
        ["november", "nov"],
        ["december", "dec", "dezember", "dez"],
    ],
    start=1,
):
    for name in names:
        MONTHS[name] = number

_BREAK_WORDS = re.compile(
    r"(sommerpause|winterpause|ferienpause|pause|summer break|winter break|break|closed|"
    r"geschlossen)",
    re.IGNORECASE,
)
_GERMAN_HINTS = re.compile(r"\b(im|von|bis|jeden|pause|und)\b", re.IGNORECASE)


def _month_span(start: int, end: int) -> list[int]:
    months = [start]
    while months[-1] != end:
        months.append(months[-1] % 12 + 1)
    return months


def parse_seasonal(text: str) -> list[ScheduleBreak]:
    """Read a seasonal note into breaks (months when it does NOT happen).

    "Sommerpause im August"       -> [Sommerpause: 8]
    "Von April bis Oktober"       -> [Winterpause: 11, 12, 1, 2, 3]  (the complement)
    "closed in July and August"   -> [closed: 7, 8]
    Specific dates ("No quiz on 23 and 30 December") are not breaks; iCal EXDATEs cover them.
    """
    t = " ".join(text.casefold().split())
    if re.search(r"\b\d{1,2}\.?\s+(and|und|&|,)", t) or re.search(r"\bon\s+\d{1,2}\b", t):
        return []  # specific days, not whole months
    tokens = re.findall(r"[a-zäöü]+", t)
    months = [MONTHS[tok] for tok in tokens if tok in MONTHS]
    if not months:
        return []
    is_range = bool(re.search(r"\b(bis|to|until|till|through)\b|[–-]", t)) and len(months) >= 2
    german = bool(_GERMAN_HINTS.search(t))

    break_word = _BREAK_WORDS.search(text)
    if break_word:
        label = break_word.group(1)
        label = label[0].upper() + label[1:]
        span = _month_span(months[0], months[1]) if is_range else sorted(set(months))
        return [ScheduleBreak(label=label, months=span)]

    if is_range:  # an active season: the break is everything else
        active = set(_month_span(months[0], months[1]))
        # The months after the season ends, in calendar order: Oct end -> 11, 12, 1, 2, 3.
        after_end = [(months[1] + i - 1) % 12 + 1 for i in range(1, 13)]
        off = [m for m in after_end if m not in active]
        if not off:
            return []
        winter = 1 in off
        label = ("Winterpause" if german else "Winter break") if winter else (
            "Sommerpause" if german else "Summer break")  # fmt: skip
        return [ScheduleBreak(label=label, months=off)]
    return []


# ---------------------------------------------------------------------------
# Schedules and occurrences
# ---------------------------------------------------------------------------


def build_schedule(
    rrule: str,
    start_time: time,
    on_or_after: date,
    end_time: time | None = None,
    breaks: list[ScheduleBreak] | None = None,
    exdates: list[date] | None = None,
    timezone: str = "Europe/Berlin",
) -> Schedule:
    """A Schedule whose dtstart is the first occurrence on or after `on_or_after`."""
    rule = rrulestr(_validate_rrule(rrule), dtstart=datetime.combine(on_or_after, start_time))
    first = rule.after(datetime.combine(on_or_after, start_time), inc=True)
    if first is None:
        raise ValueError(f"rule {rrule!r} has no occurrence on or after {on_or_after}")
    duration = None
    if end_time is not None:
        minutes = (
            datetime.combine(date.min, end_time) - datetime.combine(date.min, start_time)
        ).total_seconds() / 60
        duration = int(minutes if minutes > 0 else minutes + 24 * 60)  # ends after midnight
    return Schedule(
        rrule=_validate_rrule(rrule),
        dtstart=first,
        duration_min=duration,
        exdates=exdates or [],
        timezone=timezone,
        breaks=breaks or [],
    )


def next_occurrences(schedule: Schedule, after: datetime, count: int = 5) -> list[datetime]:
    """The next `count` start times after `after`, as timezone-aware datetimes.

    Skips EXDATEs and months inside a break. Rules work in local wall-clock time, so
    "19:00 every Tuesday" stays 19:00 across daylight-saving changes; the UTC offset is
    attached afterwards.
    """
    tz = ZoneInfo(schedule.timezone)
    local_after = after.astimezone(tz).replace(tzinfo=None) if after.tzinfo else after
    rule = rrulestr(schedule.rrule, dtstart=schedule.dtstart)
    skipped_months = {m for b in schedule.breaks for m in b.months}
    exdates = set(schedule.exdates)

    if len(skipped_months) == 12:
        return []
    result: list[datetime] = []
    # xafter walks forward once; calling rule.after() in a loop restarts from dtstart
    # every time (quadratic). The cap guards against rules that never yield a usable date.
    for i, nxt in enumerate(rule.xafter(local_after, inc=False)):
        if i >= 5000:
            break
        if nxt.date() in exdates or nxt.month in skipped_months:
            continue
        result.append(nxt.replace(tzinfo=tz))
        if len(result) == count:
            break
    return result


# ---------------------------------------------------------------------------
# RRULE -> words (rule 6: schedules must round-trip)
# ---------------------------------------------------------------------------

_DAY_NAMES = {
    "en": dict(zip(WEEKDAY_ORDER, ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                                   "Saturday", "Sunday"], strict=True)),
    "de": dict(zip(WEEKDAY_ORDER, ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag",
                                   "Samstag", "Sonntag"], strict=True)),
}  # fmt: skip
_ORDINAL_WORDS = {
    "en": {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", -1: "last"},
    "de": {1: "1.", 2: "2.", 3: "3.", 4: "4.", -1: "letzten"},
}


def _join(items: list[str], lang: str) -> str:
    word = " and " if lang == "en" else " und "
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + word + items[-1]


def describe(rrule: str, lang: Literal["en", "de"] = "en") -> str:
    """Human words for the rules this module produces. Others fall back to the raw RRULE."""
    parts = dict(p.split("=", 1) for p in _validate_rrule(rrule).split(";"))
    freq, byday, interval = parts.get("FREQ"), parts.get("BYDAY", ""), parts.get("INTERVAL", "1")
    names = _DAY_NAMES[lang]
    if freq == "WEEKLY" and byday and set(parts) <= {"FREQ", "BYDAY", "INTERVAL"}:
        days = [names[d] for d in byday.split(",") if d in names]
        if len(days) != len(byday.split(",")):
            return rrule
        if interval == "1":
            return f"every {_join(days, lang)}" if lang == "en" else f"jeden {_join(days, lang)}"
        if interval == "2":
            return (
                f"every other {_join(days, lang)}"
                if lang == "en"
                else f"jeden zweiten {_join(days, lang)}"
            )
    if freq == "MONTHLY" and set(parts) == {"FREQ", "BYDAY"}:
        match = re.fullmatch(r"(-?\d)([A-Z]{2})", byday)
        if match and int(match.group(1)) in _ORDINAL_WORDS[lang] and match.group(2) in names:
            ordinal = _ORDINAL_WORDS[lang][int(match.group(1))]
            day = names[match.group(2)]
            if lang == "en":
                return f"every {ordinal} {day} of the month"
            return f"jeden {ordinal} {day} im Monat"
    return rrule


# ---------------------------------------------------------------------------
# Inferring a rule from dated occurrences (what most real calendar feeds contain)
# ---------------------------------------------------------------------------


def _nth_weekday_of_month(d: date) -> tuple[int, bool]:
    """(n, is_last): 2nd Thursday -> (2, False); also flags the month's last such weekday."""
    n = (d.day - 1) // 7 + 1
    return n, (d + timedelta(days=7)).month != d.month


def infer_rrule(starts: list[datetime], min_occurrences: int = 3) -> str | None:
    """Find the rule behind a series of dated occurrences, or None if there isn't one.

    Requires the same weekday and start time every time. Tolerates a skipped week (a
    holiday) but not irregular gaps.
    """
    if len(starts) < min_occurrences:
        return None
    starts = sorted(starts)
    if len({s.weekday() for s in starts}) != 1 or len({s.time() for s in starts}) != 1:
        return None
    day = WEEKDAY_ORDER[starts[0].weekday()]
    gaps = [(b.date() - a.date()).days for a, b in zip(starts, starts[1:], strict=False)]
    if 0 in gaps:
        return None

    if min(gaps) >= 28:  # monthly: same nth (or last) weekday every time
        nths = {_nth_weekday_of_month(s.date())[0] for s in starts}
        if len(nths) == 1 and next(iter(nths)) <= 4:
            return f"FREQ=MONTHLY;BYDAY={next(iter(nths))}{day}"
        if all(_nth_weekday_of_month(s.date())[1] for s in starts):
            return f"FREQ=MONTHLY;BYDAY=-1{day}"
        return None
    for step, rule in ((7, f"FREQ=WEEKLY;BYDAY={day}"),
                       (14, f"FREQ=WEEKLY;INTERVAL=2;BYDAY={day}")):  # fmt: skip
        if min(gaps) == step and all(g % step == 0 and g <= 3 * step for g in gaps):
            return rule
    return None
