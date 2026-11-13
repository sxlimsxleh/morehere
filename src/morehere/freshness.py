"""Freshness (rule 7): published listings not verified recently are hidden, not deleted.

A listing is verified when one of its sources was fetched with the facts (and the source
isn't stale itself), or when a curator approves it (milestone 7). `apply_freshness` hides
published listings older than the window and shows them again once re-verified. Only
listings hidden *for staleness* come back: a curator's own "hidden" stays hidden.

Run it: python -m morehere.freshness
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import UTC, datetime

from morehere.models import Listing

log = logging.getLogger("morehere.freshness")

STALE_NOTE = "stale: hidden because not verified since "


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def is_stale(listing: Listing, now: datetime, freshness_days: int) -> bool:
    if listing.last_verified_at is None:
        return True
    return (_utc(now) - _utc(listing.last_verified_at)).days > freshness_days


def apply_freshness(
    listings: list[Listing], now: datetime, freshness_days: int
) -> tuple[list[Listing], list[Listing]]:
    """Returns (newly hidden, shown again). Other listings are untouched."""
    hidden, restored = [], []
    for listing in listings:
        stale = is_stale(listing, now, freshness_days)
        if listing.status == "published" and stale:
            since = listing.last_verified_at.date().isoformat() if listing.last_verified_at else "-"
            hidden.append(listing.model_copy(update={
                "status": "hidden",
                "review_notes": [*listing.review_notes, STALE_NOTE + since],
            }))  # fmt: skip
        elif (
            listing.status == "hidden"
            and not stale
            and any(n.startswith(STALE_NOTE) for n in listing.review_notes)
        ):
            restored.append(listing.model_copy(update={
                "status": "published",
                "review_notes": [n for n in listing.review_notes if not n.startswith(STALE_NOTE)],
            }))  # fmt: skip
    return hidden, restored


def main(argv: list[str] | None = None) -> None:
    from morehere.config import load_city_config
    from morehere.db import repo
    from morehere.db.session import make_engine, session_scope
    from morehere.logging import configure_logging, run_context

    argparse.ArgumentParser(description="Hide stale listings, show re-verified ones.").parse_args(
        argv
    )
    configure_logging()
    config = load_city_config()
    engine = make_engine()
    with run_context(), session_scope(engine) as session:
        listings = repo.list_listings(session, "published") + repo.list_listings(session, "hidden")
        hidden, restored = apply_freshness(listings, datetime.now(UTC), config.freshness_days)
        for listing in hidden + restored:
            repo.save_listing(session, listing)
        counts = {"hidden": len(hidden), "shown_again": len(restored)}
        log.info("freshness.done", extra={"fields": counts})
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    main()
