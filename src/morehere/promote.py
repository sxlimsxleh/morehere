"""Promotion: grounded drafts -> listings at places, merged across sources, scored.

    draft --(reject: one-off / cancelled)--> rejected
    draft --> place (OSM by address/name, else a new place) --> listing
          --> same activity as an existing listing? merge : new listing
          --> tags from grounded fields, Regular Score, review notes

Promotion never publishes: every listing it touches is `needs_review` (or keeps the status
a curator gave it). The core, `promote`, is a pure function over lists so evals can run it
without a database; `promote_pending` loads from and saves to Postgres.

Run it: python -m morehere.promote
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from morehere.config import CityConfig, load_city_config
from morehere.ground import outcome
from morehere.merge import merge, same_activity
from morehere.models import Evidence, Listing, ListingDraft, Place, Tag
from morehere.recurrence import build_schedule, parse_recurrence, parse_seasonal
from morehere.score import regular_score

log = logging.getLogger("morehere.promote")

# A draft's place is the OSM place at the same address, or with a very similar name in the
# same district. Below these, a new place is created rather than guessing.
NAME_MATCH_AT_ADDRESS = 0.5
NAME_MATCH_ALONE = 0.85


# ---------------------------------------------------------------------------
# Places
# ---------------------------------------------------------------------------


def address_key(address: str | None) -> str | None:
    """'Hohenzollernstr. 41' and 'Hohenzollernstraße 41' -> the same key."""
    if not address:
        return None
    a = address.casefold().replace("ß", "ss")
    a = re.sub(r"str\.|strasse", "strasse", a)
    a = re.sub(r"pl\.", "platz", a)
    return re.sub(r"[^a-z0-9äöü]", "", a) or None


def _name(text: str | None) -> str:
    return " ".join(re.findall(r"[^\W_]+", (text or "").casefold()))


def _similar(a: str | None, b: str | None) -> float:
    return difflib.SequenceMatcher(None, _name(a), _name(b)).ratio()


@dataclass
class PlaceMatch:
    place: Place
    how: str  # "address", "name", "created"


def resolve_place(draft: ListingDraft, places: list[Place]) -> PlaceMatch:
    name = draft.place_name.value
    address = draft.address.value
    key = address_key(address)
    if key:
        at_address = [p for p in places if address_key(p.address) == key]
        best = max(at_address, key=lambda p: _similar(p.name, name), default=None)
        if best and (not name or _similar(best.name, name) >= NAME_MATCH_AT_ADDRESS):
            return PlaceMatch(best, "address")
    if name:
        district = draft.district.value
        candidates = [p for p in places if district is None or p.district in (None, district)]
        best = max(candidates, key=lambda p: _similar(p.name, name), default=None)
        if best and _similar(best.name, name) >= NAME_MATCH_ALONE:
            return PlaceMatch(best, "name")
    digest = hashlib.sha256(f"{_name(name)}|{key or ''}".encode()).hexdigest()[:12]
    created = Place(
        place_id=f"draft-{digest}",
        name=name or address or "Unknown place",
        address=address,
        district=draft.district.value,
        kind="other",
    )
    return PlaceMatch(created, "created")


# ---------------------------------------------------------------------------
# Draft -> listing
# ---------------------------------------------------------------------------

COPIED_FIELDS = ("language", "price_eur", "price_period", "come_alone", "beginner_friendly",
                 "group_size", "first_timer_info", "organiser_contact")  # fmt: skip


def derive_tags(listing: Listing) -> list[Tag]:
    """User-facing tags, each from a grounded field and carrying its evidence (rule 3)."""
    ev = listing.field_evidence
    rules = [
        ("come alone OK", "come_alone", listing.come_alone is True),
        ("beginners welcome", "beginner_friendly", listing.beginner_friendly is True),
        ("English", "language", listing.language in ("en", "en+de")),
        ("free", "price_eur", listing.price_eur == 0),
        ("small group", "group_size", listing.group_size == "small"),
    ]
    return [Tag(name=name, evidence=ev[f]) for name, f, applies in rules if applies and f in ev]


def listing_from_draft(draft: ListingDraft, place: Place) -> Listing:
    notes = [f"flag: {f}" for f in draft.flags]
    evidence: dict[str, Evidence] = {}

    def ok(name: str) -> Any:
        f = getattr(draft, name)
        if f.status == "ok":
            evidence[name] = f.evidence
            return f.value
        return None

    title = ok("title") or draft.place_name.value or "Untitled"
    if draft.title.status != "ok":
        notes.append("title not stated; named after the place")
    category = ok("category")
    if category is None:
        category = "other"
        notes.append("category not stated")

    schedule = None
    rec = draft.recurrence_text
    rule = parse_recurrence(rec.value).rrule if rec.status == "ok" else None
    start = draft.start_time.value if draft.start_time.status == "ok" else None
    if rule and start:
        seasonal = draft.seasonal_text.value if draft.seasonal_text.status == "ok" else None
        schedule = build_schedule(
            rule,
            start,
            on_or_after=draft.extracted_at.date(),
            end_time=draft.end_time.value if draft.end_time.status == "ok" else None,
            breaks=parse_seasonal(seasonal) if seasonal else [],
        )
        evidence["schedule"] = rec.evidence  # type: ignore[assignment]
    else:
        notes.append("no schedule yet: " + ("no start time" if rule else "no clear rule"))

    copied = {name: ok(name) for name in COPIED_FIELDS}
    listing_id = (
        "lst-"
        + hashlib.sha256(
            f"{place.place_id}|{schedule.rrule if schedule else ''}|{_name(title)}".encode()
        ).hexdigest()[:12]
    )
    return Listing(
        listing_id=listing_id,
        title=title,
        place_id=place.place_id,
        category=category,
        schedule=schedule,
        **copied,
        field_evidence=evidence,
        status="needs_review",
        # A fact is verified when its source was fetched, unless the source is stale.
        last_verified_at=None if "stale" in draft.flags else draft.extracted_at,
        source_ids=[draft.source_id],
        review_notes=notes,
    )


def finish(listing: Listing, weights: dict[str, float]) -> Listing:
    """Tags and score always follow from the fields; recompute after every change."""
    with_tags = listing.model_copy(update={"tags": derive_tags(listing)})
    return with_tags.model_copy(update={"regular_score": regular_score(with_tags, weights)})


# ---------------------------------------------------------------------------
# The pure core
# ---------------------------------------------------------------------------


@dataclass
class Promotion:
    listings: dict[str, Listing] = field(default_factory=dict)
    new_places: dict[str, Place] = field(default_factory=dict)
    draft_to_listing: dict[int, str | None] = field(default_factory=dict)  # None: rejected
    merged: int = 0
    place_matches: dict[str, int] = field(default_factory=lambda: {"address": 0, "name": 0,
                                                                   "created": 0})  # fmt: skip


def promote(
    drafts: list[tuple[int, ListingDraft]],
    places: list[Place],
    existing: list[Listing],
    reliability: dict[str, float],
    weights: dict[str, float],
) -> Promotion:
    result = Promotion(listings={lst.listing_id: lst for lst in existing})
    known_places = list(places)
    for draft_id, draft in drafts:
        if outcome(draft) == "reject":
            result.draft_to_listing[draft_id] = None
            continue
        match = resolve_place(draft, known_places)
        result.place_matches[match.how] += 1
        if match.how == "created" and match.place.place_id not in result.new_places:
            result.new_places[match.place.place_id] = match.place
            known_places.append(match.place)  # a second draft at this venue finds it
        candidate = listing_from_draft(draft, match.place)
        if match.how == "created":
            candidate.review_notes.append("new place from the text; no coordinates yet")
        twin = next((lst for lst in result.listings.values() if same_activity(lst, candidate)),
                    None)  # fmt: skip
        if twin is not None:
            listing = merge(twin, candidate, reliability)
            result.merged += 1
        else:
            listing = candidate
        listing = finish(listing, weights)
        result.listings[listing.listing_id] = listing
        result.draft_to_listing[draft_id] = listing.listing_id
    return result


# ---------------------------------------------------------------------------
# Database wrapper and CLI
# ---------------------------------------------------------------------------


def promote_pending(engine: Any, config: CityConfig) -> dict[str, int]:
    from morehere.db import repo
    from morehere.db.session import session_scope

    with session_scope(engine) as session:
        drafts = repo.pending_drafts(session)
        places = repo.list_places(session)
        existing = repo.list_listings(session)
        reliability = {s.source_id: s.reliability for s in repo.list_sources(session)}
    result = promote(drafts, places, existing, reliability, config.score_weights)

    touched = {lid for lid in result.draft_to_listing.values() if lid}
    with session_scope(engine) as session:
        for place in result.new_places.values():
            repo.save_place(session, place)
        for listing_id in touched:
            repo.save_listing(session, result.listings[listing_id])
        for draft_id, listing_id in result.draft_to_listing.items():
            repo.set_draft_review(session, draft_id, "accepted" if listing_id else "rejected",
                                  listing_id)  # fmt: skip
    counts = {
        "drafts": len(drafts),
        "rejected": sum(1 for lid in result.draft_to_listing.values() if lid is None),
        "listings_touched": len(touched),
        "merged_into_existing": result.merged,
        "new_places": len(result.new_places),
        **{f"place_by_{k}": v for k, v in result.place_matches.items()},
    }
    log.info("promote.done", extra={"fields": counts})
    return counts


def main(argv: list[str] | None = None) -> None:
    from morehere.db.session import make_engine
    from morehere.logging import configure_logging, run_context

    argparse.ArgumentParser(description="Turn pending drafts into listings.").parse_args(argv)
    configure_logging()
    with run_context():
        counts = promote_pending(make_engine(), load_city_config())
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    main()
