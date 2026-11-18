"""morehere. curator admin (Streamlit). Run with `make admin`.

Local / Codespace use only: there is no login. Your name for the audit log comes from
CURATOR_NAME in .env. All decisions go through morehere.curation.Curator; this file only
draws the screens.
"""

from __future__ import annotations

import html
import os
from datetime import UTC, datetime, time
from typing import Any

import streamlit as st
from dotenv import load_dotenv

from morehere.config import load_city_config
from morehere.curation import (
    EDITABLE_FIELDS,
    CurationError,
    Curator,
    add_from_text,
    curation_report,
)
from morehere.db import repo
from morehere.db.session import make_engine, session_scope
from morehere.recurrence import describe, next_occurrences

load_dotenv()
st.set_page_config(page_title="morehere. curator", layout="wide")

PAGES = ["Queue", "Listing", "Add from text", "Report", "Activity"]


@st.cache_resource
def engine():  # type: ignore[no-untyped-def]
    return make_engine()


CONFIG = load_city_config()
CURATOR = Curator(engine(), os.environ.get("CURATOR_NAME") or "curator", CONFIG)


def go(page: str, listing_id: str | None = None) -> None:
    st.session_state.page = page
    if listing_id is not None:
        st.session_state.listing_id = listing_id


def run_action(action: Any, success: str) -> None:
    """Call a curator action; show its error instead of crashing."""
    try:
        action()
    except CurationError as exc:
        st.session_state.flash = ("error", str(exc))
    else:
        st.session_state.flash = ("success", success)
    st.rerun()


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------


def queue_page() -> None:
    st.header("Queue")
    status = st.radio("Status", ["needs_review", "published", "hidden"], horizontal=True)
    with session_scope(engine()) as session:
        listings = repo.list_listings(session, status)
    listings.sort(key=lambda lst: -(lst.regular_score.total if lst.regular_score else 0))
    st.caption(f"{len(listings)} listings, highest Regular Score first")
    for listing in listings:
        score = f"{listing.regular_score.total:.2f}" if listing.regular_score else "–"
        cols = st.columns([1, 6, 3, 1])
        cols[0].markdown(f"**{score}**")
        cols[1].markdown(f"{listing.title}  \n:gray[{', '.join(t.name for t in listing.tags)}]")
        n = len(listing.review_notes)
        cols[2].markdown(f":orange[{n} note{'' if n == 1 else 's'}]" if n else ":green[no notes]")
        cols[3].button(
            "Open",
            key=f"open-{listing.listing_id}",
            on_click=go,
            args=("Listing", listing.listing_id),
        )


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


def highlighted(text: str, quotes: list[str]) -> str:
    """The raw document with every quoted span marked, safe to render as HTML."""
    out = html.escape(text)
    for quote in sorted(set(quotes), key=len, reverse=True):
        q = html.escape(quote)
        out = out.replace(q, f"<mark>{q}</mark>")
    return f"<pre style='white-space:pre-wrap'>{out}</pre>"


def parse_value(field: str, raw: str) -> Any:
    raw = raw.strip()
    if raw == "":
        return None
    if field == "price_eur":
        return float(raw.replace(",", "."))
    if field in ("come_alone", "beginner_friendly"):
        return raw.lower() in ("true", "yes", "ja", "1")
    return raw


def listing_page() -> None:
    listing_id = st.session_state.get("listing_id")
    if not listing_id:
        st.info("Open a listing from the queue.")
        return
    with session_scope(engine()) as session:
        listing = repo.get_listing(session, listing_id)
        if listing is None:
            st.error("Listing not found.")
            return
        place = repo.get_place(session, listing.place_id)
        others = [
            lst
            for lst in repo.list_listings(session)
            if lst.listing_id != listing_id and lst.status != "hidden"
        ]
        raw_ids = sorted(
            {e.raw_record_id for e in listing.field_evidence.values()}
            | {t.evidence.raw_record_id for t in listing.tags}
        )
        raws = [r for r in (repo.get_raw_record(session, rid) for rid in raw_ids) if r]
        actions = repo.list_actions(session, listing_id)

    score = listing.regular_score.total if listing.regular_score else None
    st.header(listing.title)
    st.markdown(
        f"**{listing.status}** · Regular Score **{score:.2f}**"
        if score is not None
        else f"**{listing.status}**"
    )
    if place:
        where = ", ".join(x for x in [place.name, place.address, place.district] if x)
        coords = f"{place.geo.lat:.5f}, {place.geo.lon:.5f}" if place.geo else "no coordinates"
        st.markdown(f"📍 {where} · {coords}")
    verified = listing.last_verified_at.date().isoformat() if listing.last_verified_at else "never"
    st.markdown(f"Last verified: **{verified}** · Sources: {', '.join(listing.source_ids)}")
    if listing.schedule:
        dates = next_occurrences(listing.schedule, datetime.now(UTC), 3)
        st.markdown(
            f"🗓 {describe(listing.schedule.rrule, 'en')} · next: "
            + ", ".join(d.strftime("%a %d %b %H:%M") for d in dates)
        )
    for note in listing.review_notes:
        st.warning(note)

    # Actions
    c1, c2, c3 = st.columns(3)
    if c1.button("✅ Approve & publish", key="approve", disabled=listing.status == "published"):
        run_action(lambda: CURATOR.approve(listing_id), "Published.")
    if c2.button("🔁 Verify (still on)", key="verify"):
        run_action(lambda: CURATOR.verify(listing_id), "Verified today.")
    with c3.popover("🙈 Hide"):
        reason = st.text_input("Why?", key="hide-reason")
        if st.button("Hide listing", key="hide"):
            run_action(lambda: CURATOR.hide(listing_id, reason), "Hidden.")

    # Facts with their evidence
    st.subheader("Facts and where they come from")
    rows = []
    for field in ("schedule", *EDITABLE_FIELDS):
        value = (
            describe(listing.schedule.rrule, "en")
            if field == "schedule" and listing.schedule
            else getattr(listing, field, None)
        )
        ev = listing.field_evidence.get(field)
        rows.append(
            {
                "field": field,
                "value": "" if value is None else str(value),
                "quote": ev.source_text if ev else "",
                "source": ev.source_id if ev else "",
            }
        )
    st.dataframe(rows, hide_index=True, use_container_width=True)

    if listing.regular_score:
        with st.expander("Score breakdown"):
            st.dataframe(
                [
                    {
                        "component": c,
                        "score": v,
                        "based on": ", ".join(listing.regular_score.based_on.get(c, [])),
                    }
                    for c, v in listing.regular_score.components.items()
                ],
                hide_index=True,
                use_container_width=True,
            )

    # Edits
    st.subheader("Correct something")
    with st.form("edit-field"):
        field = st.selectbox("Field", EDITABLE_FIELDS)
        value = st.text_input("New value (empty clears it; true/false for yes/no fields)")
        note = st.text_input("How do you know? (saved as the source)")
        if st.form_submit_button("Save field"):
            try:
                parsed = parse_value(field, value)
            except ValueError:
                st.error(f"Not a number: {value!r}")
            else:
                run_action(lambda: CURATOR.edit_field(listing_id, field, parsed, note), "Saved.")
    with st.form("edit-schedule"):
        phrase = st.text_input(
            "Schedule phrase", placeholder="every Tuesday / jeden 2. Donnerstag im Monat"
        )
        start = st.time_input(
            "Start", value=listing.schedule.dtstart.time() if listing.schedule else time(19, 0)
        )
        has_end = st.checkbox("Has an end time")
        end = st.time_input("End", value=time(21, 0))
        seasonal = st.text_input("Seasonal break (optional)", placeholder="Sommerpause im August")
        snote = st.text_input("How do you know?", key="schedule-note")
        if st.form_submit_button("Save schedule"):
            run_action(
                lambda: CURATOR.edit_schedule(
                    listing_id, phrase, start, end if has_end else None, seasonal, snote
                ),
                "Schedule saved.",
            )

    # Place
    st.subheader("Place")
    query = st.text_input("Search places (name or street)")
    if query:
        with session_scope(engine()) as session:
            matches = repo.search_places(session, query)
        if matches:
            chosen = st.selectbox(
                "Matches",
                matches,
                format_func=lambda p: (
                    f"{p.name} – {p.address or 'no address'} ({p.district or '?'})"
                ),
            )
            if st.button("Use this place", key="use-place"):
                run_action(lambda: CURATOR.set_place(listing_id, chosen.place_id), "Place set.")
        else:
            st.caption("No match.")
    if place is not None:
        lat_col, lon_col, btn_col = st.columns([2, 2, 1])
        lat = lat_col.number_input(
            "Latitude", value=place.geo.lat if place.geo else 48.137, format="%.6f"
        )
        lon = lon_col.number_input(
            "Longitude", value=place.geo.lon if place.geo else 11.575, format="%.6f"
        )
        if btn_col.button("Set coordinates", key="coords"):
            run_action(
                lambda: CURATOR.set_coordinates(place.place_id, lat, lon), "Coordinates set."
            )

    # Merge
    if others:
        st.subheader("Same activity as another listing?")
        other = st.selectbox(
            "Other listing", others, format_func=lambda lst: f"{lst.title} ({lst.status})"
        )
        if st.button("Merge it into this one", key="merge"):
            run_action(lambda: CURATOR.merge(listing_id, other.listing_id), "Merged.")

    # Sources
    st.subheader("Source documents")
    quotes = [e.source_text for e in listing.field_evidence.values()]
    for raw in raws:
        with st.expander(
            f"{raw.source_id} · {raw.raw_record_id}" + (f" · {raw.url}" if raw.url else "")
        ):
            st.markdown(highlighted(raw.payload, quotes), unsafe_allow_html=True)

    if actions:
        st.subheader("History")
        st.dataframe(
            [{k: v for k, v in a.items() if k != "listing_id"} for a in actions],
            hide_index=True,
            use_container_width=True,
        )


# ---------------------------------------------------------------------------
# Add from text, report, activity
# ---------------------------------------------------------------------------


def add_page() -> None:
    st.header("Add from text")
    st.caption(
        "Paste the text of a page, post or email that describes a recurring activity "
        "in Munich. It's extracted (about 2 cents), checked against the text, and "
        "lands in the queue for you to review."
    )
    url = st.text_input("Where it's from (URL, optional)")
    text = st.text_area("Text", height=300)
    if st.button("Extract", key="extract", type="primary"):
        from morehere.extract import AnthropicBackend, MissingCredentials, load_llm_settings

        try:
            with st.spinner("Extracting..."):
                result = add_from_text(
                    engine(),
                    text,
                    url,
                    CURATOR.name,
                    AnthropicBackend(),
                    load_llm_settings(),
                    CONFIG,
                )
        except (CurationError, MissingCredentials) as exc:
            st.error(str(exc))
        else:
            st.success(
                f"{result['drafts']} draft(s); {result['listings_touched']} listing(s) "
                f"in the queue; {result['rejected']} rejected (one-off or cancelled). "
                f"Cost about ${result['est_cost_usd'] or 0:.3f}."
            )


def report_page() -> None:
    st.header("How often did you correct the extractor?")
    with session_scope(engine()) as session:
        report = curation_report(repo.list_listings(session))
    for name, label in (
        ("held_out", "Held out (documents outside the golden samples)"),
        ("all", "All published listings"),
    ):
        part = report[name]
        rate = f"{part['kept_rate']:.1%}" if part["kept_rate"] is not None else "–"
        st.subheader(f"{label}: {part['listings']} listings, {rate} of facts kept as extracted")
        st.dataframe(
            [{"field": f, **row} for f, row in part["fields"].items()],
            hide_index=True,
            use_container_width=True,
        )


def activity_page() -> None:
    st.header("Activity")
    with session_scope(engine()) as session:
        st.dataframe(
            repo.list_actions(session, limit=200), hide_index=True, use_container_width=True
        )


# ---------------------------------------------------------------------------

st.session_state.setdefault("page", "Queue")
with st.sidebar:
    st.title("morehere.")
    st.caption(f"Curator: {CURATOR.name}")
    for name in PAGES:
        st.button(
            name,
            key=f"nav-{name}",
            on_click=go,
            args=(name,),
            use_container_width=True,
            type="primary" if st.session_state.page == name else "secondary",
        )
if flash := st.session_state.pop("flash", None):
    getattr(st, flash[0])(flash[1])

page: dict[str, Any] = {
    "Queue": queue_page,
    "Listing": listing_page,
    "Add from text": add_page,
    "Report": report_page,
    "Activity": activity_page,
}
page[st.session_state.page]()
