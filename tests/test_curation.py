"""Milestone 7: curator actions, their evidence and audit log, add-from-text, the report,
and a headless run of the Streamlit admin."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, time
from pathlib import Path

import pytest
from sqlalchemy import Engine, delete, select

from morehere.config import load_city_config
from morehere.curation import (
    CURATOR_SOURCE,
    CurationError,
    Curator,
    add_from_text,
    approve,
    curation_report,
    edit_field,
    edit_schedule,
    hide,
    merge_into,
)
from morehere.db.seed import load_sources
from morehere.golden import golden_draft, load_golden
from morehere.models import Listing
from morehere.promote import promote
from morehere.text import contains_span

GOLDEN = load_golden()
CONFIG = load_city_config()
RELIABILITY = {s.source_id: s.reliability for s in load_sources()}
NOW = datetime(2026, 11, 15, 10, 0, tzinfo=UTC)
REGISTRY = {
    "ical": "ical-public-feeds",
    "email": "email-inbox",
    "web_page": "pasted-links",
    "tip": "community-tips",
    "submission": "organiser-form",
}


def golden_listings() -> dict[str, Listing]:
    """Golden drafts promoted; keyed by the label key of the (first) draft."""
    drafts, keys = [], {}
    for i, (f, label) in enumerate(GOLDEN.all_listings()):
        drafts.append(
            (
                i,
                golden_draft(
                    GOLDEN,
                    f,
                    label,
                    source_id=REGISTRY[f.source_kind],
                    raw_record_id=f"sample-{f.file}",
                ),
            )
        )
        keys[i] = label.key
    result = promote(drafts, [], [], RELIABILITY, CONFIG.score_weights)
    out: dict[str, Listing] = {}
    for i, lid in result.draft_to_listing.items():
        if lid and keys[i] not in out:
            out[keys[i]] = result.listings[lid]
    return out


LISTINGS = golden_listings()


# --- Pure actions ------------------------------------------------------------------


def test_edit_keeps_rule_2_the_curator_is_the_source() -> None:
    runners = LISTINGS["isar-morning-runners"]
    changed, record = edit_field(
        runners, "title", "Isar Morning Runners", "Selim", NOW, "Their website writes it this way."
    )
    assert changed.title == "Isar Morning Runners"
    assert record is not None and record.source_id == CURATOR_SOURCE
    assert record.payload.startswith("Selim, 2026-11-15: title = 'Isar Morning Runners'.")
    ev = changed.field_evidence["title"]
    assert ev.source_id == CURATOR_SOURCE and contains_span(record.payload, ev.source_text)
    assert CURATOR_SOURCE in changed.source_ids


def test_edit_is_type_checked() -> None:
    with pytest.raises(CurationError, match="not a valid category"):
        edit_field(LISTINGS["clay-and-chat"], "category", "party", "Selim", NOW)
    with pytest.raises(CurationError, match="can't be edited"):
        edit_field(LISTINGS["clay-and-chat"], "status", "published", "Selim", NOW)


def test_clearing_a_field_removes_its_evidence() -> None:
    pottery = LISTINGS["clay-and-chat"]
    assert "price_eur" in pottery.field_evidence
    changed, record = edit_field(pottery, "price_eur", None, "Selim", NOW)
    assert record is None and changed.price_eur is None
    assert "price_eur" not in changed.field_evidence


def test_schedule_from_a_phrase_makes_a_missing_time_publishable() -> None:
    games = LISTINGS["wuerfel-und-worte"]  # the source never says when it starts
    with pytest.raises(CurationError, match="set a schedule"):
        approve(games, NOW)
    fixed, record = edit_schedule(
        games, "every Friday", time(19, 0), time(23, 0), "", "Selim", NOW, "Asked at the café."
    )
    assert fixed.schedule is not None and fixed.schedule.rrule == "FREQ=WEEKLY;BYDAY=FR"
    assert not any(n.startswith("no schedule yet") for n in fixed.review_notes)
    assert record.payload.endswith("Asked at the café.")
    published = approve(fixed, NOW)
    assert published.status == "published" and published.last_verified_at == NOW


def test_unclear_schedule_phrase_is_refused() -> None:
    with pytest.raises(CurationError, match="biweekly"):
        edit_schedule(
            LISTINGS["chess-in-the-park"], "biweekly on Saturdays", time(14), None, "", "Selim", NOW
        )


def test_hide_needs_a_reason() -> None:
    with pytest.raises(CurationError):
        hide(LISTINGS["clay-and-chat"], "  ", NOW)
    hidden = hide(LISTINGS["clay-and-chat"], "studio closed", NOW)
    assert hidden.status == "hidden" and hidden.review_notes[-1].endswith("studio closed")


def test_manual_merge_hides_the_other_listing_with_a_pointer() -> None:
    keep, other = LISTINGS["tandem-tuesday-luma"], LISTINGS["language-cafe-haidhausen"]
    merged, gone = merge_into(keep, other, RELIABILITY, NOW)
    assert gone.status == "hidden"
    assert gone.review_notes[-1].startswith(f"merged into {keep.listing_id}")
    with pytest.raises(CurationError):
        merge_into(keep, keep, RELIABILITY, NOW)


# --- The report --------------------------------------------------------------------


def test_report_counts_kept_and_corrected_facts() -> None:
    pottery = approve(LISTINGS["clay-and-chat"], NOW)
    corrected, _ = edit_field(pottery, "title", "Clay & Chat", "Selim", NOW)
    report = curation_report([corrected, LISTINGS["isar-morning-runners"]])  # 2nd isn't published
    assert report["all"]["listings"] == 1
    assert report["all"]["fields"]["title"]["corrected"] == 1
    assert report["all"]["fields"]["price_eur"]["kept"] == 1
    assert report["held_out"]["listings"] == 0  # golden samples are never "held out"


# --- Database ----------------------------------------------------------------------


@pytest.fixture
def curated_db(db_engine: Engine) -> Iterator[Engine]:
    from morehere.db import repo
    from morehere.db.seed import seed_sources
    from morehere.db.session import session_scope
    from morehere.db.tables import (
        CuratorActionRow,
        EvidenceRow,
        ListingDraftRow,
        ListingRow,
        PlaceRow,
        RawRecordRow,
    )
    from morehere.extract import golden_raw_record

    def wipe() -> None:
        with session_scope(db_engine) as s:
            s.execute(delete(CuratorActionRow))
            s.execute(delete(ListingDraftRow))
            s.execute(delete(ListingRow))
            s.execute(
                delete(EvidenceRow).where(
                    EvidenceRow.raw_record_id.like("sample-%")
                    | EvidenceRow.raw_record_id.like("curator-%")
                    | EvidenceRow.raw_record_id.like("pasted-%")
                )
            )
            s.execute(delete(PlaceRow).where(PlaceRow.place_id.startswith("draft-")))
            s.execute(
                delete(RawRecordRow).where(
                    RawRecordRow.raw_record_id.like("sample-%")
                    | RawRecordRow.raw_record_id.like("curator-%")
                    | RawRecordRow.raw_record_id.like("pasted-%")
                )
            )

    wipe()
    seed_sources(db_engine)
    as_of = datetime.fromisoformat(GOLDEN.as_of)
    with session_scope(db_engine) as s:
        for f in GOLDEN.files:
            repo.save_raw_record(s, golden_raw_record(f.file, f.source_kind, f.content_type, as_of))
        for listing in LISTINGS.values():
            if listing.place_id.startswith("draft-"):
                from morehere.models import Place

                repo.save_place(
                    s, Place(place_id=listing.place_id, name=listing.title, kind="other")
                )
            repo.save_listing(s, listing)
    yield db_engine
    wipe()


def _curator(engine: Engine) -> Curator:
    return Curator(engine, "Selim", CONFIG, clock=lambda: NOW)


@pytest.mark.db
def test_curator_actions_are_saved_and_logged(curated_db: Engine) -> None:
    from morehere.db import repo
    from morehere.db.session import session_scope

    curator = _curator(curated_db)
    lid = LISTINGS["isar-morning-runners"].listing_id
    curator.edit_field(lid, "title", "Isar Morning Runners", "Website spelling.")
    curator.approve(lid)

    with session_scope(curated_db) as s:
        saved = repo.get_listing(s, lid)
        assert saved is not None
        assert (saved.title, saved.status) == ("Isar Morning Runners", "published")
        assert saved.last_verified_at == NOW
        record = repo.get_raw_record(s, saved.field_evidence["title"].raw_record_id)
        assert record is not None and "Website spelling." in record.payload
        assert [a["action"] for a in repo.list_actions(s, lid)] == ["approve", "edit_field"]


@pytest.mark.db
def test_failed_action_changes_nothing(curated_db: Engine) -> None:
    from morehere.db import repo
    from morehere.db.session import session_scope

    lid = LISTINGS["wuerfel-und-worte"].listing_id  # no schedule
    with pytest.raises(CurationError):
        _curator(curated_db).approve(lid)
    with session_scope(curated_db) as s:
        assert repo.get_listing(s, lid).status == "needs_review"  # type: ignore[union-attr]
        assert repo.list_actions(s, lid) == []


@pytest.mark.db
def test_coordinates_also_set_the_district_when_boundaries_are_loaded(curated_db: Engine) -> None:
    from morehere.db import repo
    from morehere.db.session import session_scope

    place_id = LISTINGS["clay-and-chat"].place_id
    _curator(curated_db).set_coordinates(place_id, 48.1173, 11.5824)
    with session_scope(curated_db) as s:
        place = repo.get_place(s, place_id)
        assert place is not None and place.geo is not None
        assert round(place.geo.lat, 4) == 48.1173


@pytest.mark.db
def test_add_from_text_extracts_promotes_and_logs(curated_db: Engine) -> None:
    from test_extract import SETTINGS, FakeBackend  # pytest puts tests/ on the path

    from morehere.db import repo
    from morehere.db.session import session_scope
    from morehere.evaluation import golden_claims

    f = next(g for g in GOLDEN.files if g.file.startswith("07_run_club"))
    # The fixture already stored this sample as a raw record of the same source; identical
    # text from the same source is stored once, so the curator pastes a newer copy.
    sample = (Path(__file__).parents[1] / "data" / "raw" / f.file).read_text(encoding="utf-8")
    text = sample + "\nUpdated November 2026.\n"
    result = add_from_text(
        curated_db,
        text,
        "https://runners.example",
        "Selim",
        FakeBackend(golden_claims(f)),
        SETTINGS,
        CONFIG,
        now=NOW,
    )
    assert result["drafts"] == 1 and result["listings_touched"] == 1
    with session_scope(curated_db) as s:
        assert repo.get_raw_record(s, result["raw_record_id"]).url == "https://runners.example"  # type: ignore[union-attr]
        assert repo.list_actions(s)[0]["action"] == "add_from_text"
    with pytest.raises(CurationError, match="added before"):
        add_from_text(
            curated_db,
            text,
            None,
            "Selim",
            FakeBackend(golden_claims(f)),
            SETTINGS,
            CONFIG,
            now=NOW,
        )


@pytest.mark.db
def test_admin_app_runs_and_publishes(curated_db: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    from conftest import TEST_DATABASE_URL
    from streamlit.testing.v1 import AppTest

    from morehere.db.session import session_scope
    from morehere.db.tables import ListingRow

    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setenv("CURATOR_NAME", "Selim")
    app = AppTest.from_file(
        str(Path(__file__).parents[1] / "admin" / "curate.py"), default_timeout=30
    )
    app.run()
    assert not app.exception
    assert any("Tandem Tuesday" in m.value for m in app.markdown)

    lid = LISTINGS["tandem-tuesday-luma"].listing_id
    app.session_state.page = "Listing"
    app.session_state.listing_id = lid
    app.run()
    assert not app.exception
    app.button(key="approve").click().run()
    assert not app.exception
    with session_scope(curated_db) as s:
        status = s.scalar(select(ListingRow.status).where(ListingRow.listing_id == lid))
    assert status == "published"
