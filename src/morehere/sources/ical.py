"""iCal feeds: parse events, build schedules, and find series hidden in dated events.

Two kinds of recurring events show up in real feeds:
- a VEVENT with an RRULE ("every Tuesday"), which is what the iCal standard intends;
- the common case on Luma and venue calendars: one VEVENT per date. `infer_series`
  groups those by title and place and asks `recurrence.infer_rrule` for the rule.

Commands:
    python -m morehere.sources.ical probe URL   # is this feed useful? stores nothing
    python -m morehere.sources.ical ingest      # every iCal feed in the source registry
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import icalendar
from sqlalchemy import Engine

from morehere import http
from morehere.db import repo
from morehere.db.session import make_engine, session_scope
from morehere.logging import configure_logging, run_context, timed_step
from morehere.models import RawRecord, Schedule, sha256_text
from morehere.recurrence import infer_rrule, parse_recurrence
from morehere.text import normalise_whitespace

log = logging.getLogger("morehere.sources.ical")

LOCAL_TZ = ZoneInfo("Europe/Berlin")


class NotICalError(ValueError):
    """The URL answered, but not with an iCalendar document."""


@dataclass
class ICalEvent:
    uid: str
    summary: str
    location: str | None
    description: str | None
    url: str | None
    start: datetime | None  # local wall-clock time; None for all-day events
    start_date: date
    end: datetime | None
    all_day: bool
    rrule: str | None
    exdates: list[date] = field(default_factory=list)
    cancelled: bool = False


@dataclass
class ParsedFeed:
    name: str | None
    events: list[ICalEvent]
    skipped_overrides: int  # RECURRENCE-ID: a changed single date of a series


@dataclass
class InferredSeries:
    summary: str
    location: str | None
    rrule: str
    first_start: datetime
    occurrences: int
    duration_min: int | None
    uids: list[str]


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _local(value: date | datetime) -> tuple[datetime | None, date, bool]:
    """(local naive datetime or None, date, all_day) for a DTSTART/DTEND value."""
    if isinstance(value, datetime):
        if value.tzinfo is not None:  # TZID or UTC: convert to Munich wall-clock time
            value = value.astimezone(LOCAL_TZ).replace(tzinfo=None)
        return value, value.date(), False
    return None, value, True  # a DATE: all-day event


def _text(component: icalendar.cal.Component, name: str) -> str | None:
    value = component.get(name)
    if value is None:
        return None
    return normalise_whitespace(str(value)) or None


def _exdates(component: icalendar.cal.Component) -> list[date]:
    raw = component.get("EXDATE")
    if raw is None:
        return []
    groups = raw if isinstance(raw, list) else [raw]
    result: list[date] = []
    for group in groups:
        for item in group.dts:
            _, day, _ = _local(item.dt)
            result.append(day)
    return sorted(set(result))


def parse_feed(payload: str) -> ParsedFeed:
    if "BEGIN:VCALENDAR" not in payload[:2000]:
        raise NotICalError("payload is not an iCalendar document")
    calendar = icalendar.Calendar.from_ical(payload)
    events: list[ICalEvent] = []
    overrides = 0
    for component in calendar.walk("VEVENT"):
        if component.get("RECURRENCE-ID") is not None:
            overrides += 1
            continue
        if component.get("DTSTART") is None:
            continue
        start, start_date, all_day = _local(component.decoded("DTSTART"))
        end = None
        if component.get("DTEND") is not None:
            end, _, _ = _local(component.decoded("DTEND"))
        rrule = component.get("RRULE")
        events.append(
            ICalEvent(
                uid=str(component.get("UID", "")),
                summary=_text(component, "SUMMARY") or "(untitled)",
                location=_text(component, "LOCATION"),
                description=_text(component, "DESCRIPTION"),
                url=_text(component, "URL"),
                start=start,
                start_date=start_date,
                end=end,
                all_day=all_day,
                rrule=rrule.to_ical().decode() if rrule is not None else None,
                exdates=_exdates(component),
                cancelled=str(component.get("STATUS", "")).upper() == "CANCELLED",
            )
        )
    name = calendar.get("X-WR-CALNAME")
    return ParsedFeed(name=str(name) if name else None, events=events, skipped_overrides=overrides)


def _duration_min(start: datetime | None, end: datetime | None) -> int | None:
    if start is None or end is None or end <= start:
        return None
    return int((end - start).total_seconds() // 60)


def event_schedule(event: ICalEvent) -> Schedule | None:
    """The Schedule of an event with an RRULE, or None (no RRULE, all-day, or unreadable)."""
    if event.rrule is None or event.start is None:
        return None
    result = parse_recurrence(event.rrule)
    if result.rrule is None:
        return None
    return Schedule(
        rrule=result.rrule,
        dtstart=event.start,
        duration_min=_duration_min(event.start, event.end),
        exdates=event.exdates,
    )


# Edition markers: the part of a title that changes from one date of a series to the
# next ("Knight Gambit Vol.14", "Brunch & Workshop #3", "Reading Session · Night 1").
# Bare numbers are NOT removed: "5k Run Club" or "Repair Café 246" mean something.
_EDITION_MARKERS = re.compile(
    r"""
    \bvol(?:ume)?\.?\s*(?:\d+|[ivx]+)\b            # Vol.14, Volume 2, vol. II
    | \#\s*\d+                                     # #3
    | \b(?:no|nr)\.?\s*\d+\b                       # No. 5, Nr. 5
    | \b(?:night|part|teil|edition|ausgabe|episode|ep|folge|round|runde|chapter|kapitel)
      \.?\s*\d+\b                                  # Night 1, Teil 2, Edition 7
    | \b\d+(?:st|nd|rd|th)\s+edition\b              # 3rd edition
    | \b\d+\.\s*(?:ausgabe|edition)                  # 7. Ausgabe
    """,
    re.IGNORECASE | re.VERBOSE,
)
_SEPARATORS = " ·-–—|:,/"


def series_title(summary: str) -> str:
    """The title without edition markers, for grouping and display.

    "Ambient Reading Session vol. 1 · Night 1" -> "Ambient Reading Session"
    """
    stripped = _EDITION_MARKERS.sub(" ", summary)
    stripped = re.sub(r"\s*([·|–—-])\s*(?:[·|–—-]\s*)+", r" \1 ", stripped)  # "a · · b"
    stripped = re.sub(r"\s+([:,])", r"\1", stripped)  # "The : Poetry" -> "The: Poetry"
    return normalise_whitespace(stripped).strip(_SEPARATORS) or summary


def has_edition_marker(summary: str) -> bool:
    return _EDITION_MARKERS.search(summary) is not None


def _series_key(event: ICalEvent) -> tuple[str, str]:
    # Letters and digits only: emoji and punctuation differences don't split a series.
    words = re.findall(r"[^\W_]+", series_title(event.summary).casefold())
    return (" ".join(words), (event.location or "").casefold())


_URL = re.compile(r"https?://[^\s<>\"']+")


def event_link(event: ICalEvent) -> str | None:
    """The event's page: its URL property, or the first link in its description/location."""
    if event.url:
        return event.url
    for text in (event.description, event.location):
        match = _URL.search(text or "")
        if match:
            return match.group(0).rstrip(".,;)")
    return None


def infer_series(events: list[ICalEvent], min_occurrences: int = 3) -> list[InferredSeries]:
    """Group dated events by (title without edition markers, place) and keep the groups
    that follow a rule: "Knight Gambit Vol.13/14/15" on three Tuesdays is one series."""
    groups: dict[tuple[str, str], list[ICalEvent]] = defaultdict(list)
    for event in events:
        if event.rrule is None and not event.cancelled and event.start is not None:
            groups[_series_key(event)].append(event)

    series: list[InferredSeries] = []
    for group in groups.values():
        group.sort(key=lambda e: e.start or datetime.min)
        starts = [e.start for e in group if e.start is not None]
        rrule = infer_rrule(starts, min_occurrences=min_occurrences)
        if rrule is None:
            continue
        series.append(
            InferredSeries(
                summary=series_title(group[0].summary),
                location=group[0].location,
                rrule=rrule,
                first_start=starts[0],
                occurrences=len(group),
                duration_min=_duration_min(group[0].start, group[0].end),
                uids=[e.uid for e in group],
            )
        )
    return sorted(series, key=lambda s: s.summary.casefold())


def summarise(feed: ParsedFeed, now: datetime | None = None) -> dict[str, Any]:
    """What a feed would give us: the numbers behind "is this source useful?"."""
    now_local = (now or datetime.now(UTC)).astimezone(LOCAL_TZ).replace(tzinfo=None)
    upcoming = [e for e in feed.events if e.start and e.start >= now_local - timedelta(days=1)]
    with_rrule = [e for e in feed.events if e.rrule]
    series = infer_series(feed.events)
    in_series = {uid for s in series for uid in s.uids}
    one_offs = [
        e for e in feed.events if not e.rrule and not e.cancelled and e.uid not in in_series
    ]
    return {
        "calendar_name": feed.name,
        "events": len(feed.events),
        "upcoming_dated_events": len(upcoming),
        "events_with_rrule": len(with_rrule),
        "inferred_series": len(series),
        "events_in_inferred_series": len(in_series),
        "one_off_events": len(one_offs),
        "cancelled": sum(e.cancelled for e in feed.events),
        "skipped_overrides": feed.skipped_overrides,
        "recurring": [
            {"summary": e.summary, "rrule": e.rrule, "location": e.location} for e in with_rrule
        ]
        + [
            {
                "summary": s.summary,
                "rrule": s.rrule,
                "location": s.location,
                "seen": s.occurrences,
            }  # fmt: skip
            for s in series
        ],
        "sample_one_offs": sorted({e.summary for e in one_offs})[:10],
        # Numbered one-offs ("Vol.14", "#3") are probably one date of a series whose other
        # dates are on the host's own calendar: follow the link and probe that calendar.
        "series_hints": [
            {
                "summary": e.summary,
                "series_title": series_title(e.summary),
                "start": e.start,
                "link": event_link(e),
            }
            for e in sorted(one_offs, key=lambda e: e.start or datetime.min)
            if has_edition_marker(e.summary)
        ],
    }


# ---------------------------------------------------------------------------
# Fetching and ingestion
# ---------------------------------------------------------------------------


def fetch_feed(
    client: httpx.Client,
    url: str,
    *,
    max_attempts: int = 4,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    for attempt in http.retrying(log, "ical.fetch.retry", max_attempts=max_attempts, sleep=sleep):
        with attempt:
            response = client.get(url, headers={"Accept": "text/calendar, */*;q=0.5"})
            response.raise_for_status()
            text = response.text
            if "BEGIN:VCALENDAR" not in text[:2000]:
                content_type = response.headers.get("content-type", "?")
                raise NotICalError(f"not an iCalendar document (content-type {content_type})")
            return text
    raise AssertionError("unreachable: retrying either returns or raises")


def probe(client: httpx.Client, url: str, now: datetime | None = None) -> dict[str, Any]:
    """Fetch a feed and report what it contains. Stores nothing."""
    try:
        payload = fetch_feed(client, url)
    except NotICalError as exc:
        return {"url": url, "is_ical": False, "error": str(exc)}
    except httpx.HTTPStatusError as exc:
        return {"url": url, "is_ical": False, "error": f"HTTP {exc.response.status_code}"}
    return {"url": url, "is_ical": True, **summarise(parse_feed(payload), now)}


def ingest_feeds(engine: Engine, client: httpx.Client, now: datetime | None = None) -> list[dict]:
    """Fetch every iCal feed in the registry, store it raw, and report what it holds.

    Turning events into listing drafts is milestone 5 (descriptions need extraction).
    """
    now = now or datetime.now(UTC)
    with session_scope(engine) as session:
        feeds = [s for s in repo.list_sources(session, kind="ical") if s.url]
    results = []
    for source in feeds:
        assert source.url is not None
        try:
            with timed_step(log, "ical.fetch", source_id=source.source_id) as step:
                payload = fetch_feed(client, source.url)
                step["bytes"] = len(payload)
        except (httpx.HTTPError, NotICalError):
            results.append({"source_id": source.source_id, "ok": False})
            continue  # logged by timed_step; one broken feed must not stop the others
        digest = sha256_text(payload)
        record = RawRecord(
            raw_record_id=f"ical-{source.source_id}-{digest[:16]}",
            source_id=source.source_id,
            fetched_at=now,
            sha256=digest,
            content_type="text/calendar",
            url=source.url,
            payload=payload,
        )
        with session_scope(engine) as session:
            stored, created = repo.save_raw_record(session, record)
        with timed_step(log, "ical.parse", source_id=source.source_id) as step:
            summary = summarise(parse_feed(stored.payload), now)
            step.update({k: v for k, v in summary.items() if isinstance(v, int)}, new=created)
        results.append({"source_id": source.source_id, "ok": True, "new_payload": created,
                        **summary})  # fmt: skip
    return results


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="iCal feeds for morehere.")
    sub = parser.add_subparsers(dest="command", required=True)
    probe_cmd = sub.add_parser("probe", help="check what a feed contains; stores nothing")
    probe_cmd.add_argument("url")
    sub.add_parser("ingest", help="fetch every iCal feed in the source registry")
    args = parser.parse_args(argv)

    configure_logging()
    with run_context(), http.make_client() as client:
        if args.command == "probe":
            result: Any = probe(client, args.url)
        else:
            result = ingest_feeds(make_engine(), client)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
