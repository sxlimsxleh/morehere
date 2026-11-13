"""Milestone 6: drafts -> listings, places, merging, tags, Regular Score, freshness."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

import pytest
from sqlalchemy import Engine, delete

from morehere.config import load_city_config
from morehere.db.seed import load_sources
from morehere.freshness import STALE_NOTE, apply_freshness, is_stale
from morehere.golden import golden_draft, load_golden
from morehere.merge import merge, same_activity
from morehere.models import Evidence, GeoPoint, Listing, ListingDraft, Place
from morehere.promote import (
    address_key,
    derive_tags,
    listing_from_draft,
    promote,
    resolve_place,
)
from morehere.score import regular_score

GOLDEN = load_golden()
CONFIG = load_city_config()
WEIGHTS = CONFIG.score_weights
RELIABILITY = {s.source_id: s.reliability for s in load_sources()}
REGISTRY = {"ical": "ical-public-feeds", "email": "email-inbox", "web_page": "pasted-links",
            "tip": "community-tips", "submission": "organiser-form"}  # fmt: skip
NOW = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)


def golden_drafts() -> tuple[list[tuple[int, ListingDraft]], dict[int, str]]:
    drafts, keys = [], {}
    for i, (f, label) in enumerate(GOLDEN.all_listings()):
        draft = golden_draft(GOLDEN, f, label, source_id=REGISTRY[f.source_kind],
                             raw_record_id=f"sample-{f.file}")  # fmt: skip
        drafts.append((i, draft))
        keys[i] = label.key
    return drafts, keys


def draft_for(key: str) -> ListingDraft:
    drafts, keys = golden_drafts()
    return next(d for i, d in drafts if keys[i] == key)


# --- Places ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Hohenzollernstraße 41", "Hohenzollernstr. 41"),
        ("Hohenzollernstrasse 41", "Hohenzollernstr. 41"),
        ("Weißenburger Platz 3", "Weißenburger Pl. 3"),
        ("Landsberger Str. 290", "Landsberger Straße 290"),
    ],
)
def test_address_key_ignores_spelling_variants(a: str, b: str) -> None:
    assert address_key(a) == address_key(b)


def test_address_key_keeps_house_numbers_apart() -> None:
    assert address_key("Hohenzollernstraße 41") != address_key("Hohenzollernstraße 14")


OSM_LINDWURM = Place(place_id="osm-node-1", name="Cafe Lindwurm", address="Hohenzollernstraße 41",
                     district="Schwabing-West", geo=GeoPoint(lat=48.16, lon=11.57),
                     osm_id="node/1", kind="cafe")  # fmt: skip


def test_draft_resolves_to_the_osm_place_at_its_address() -> None:
    match = resolve_place(draft_for("tandem-tuesday-newsletter"), [OSM_LINDWURM])
    assert (match.how, match.place.place_id) == ("address", "osm-node-1")


def test_unknown_venue_becomes_a_new_place_without_coordinates() -> None:
    match = resolve_place(draft_for("clay-and-chat"), [OSM_LINDWURM])
    assert match.how == "created"
    assert match.place.name == "Tonwerk Giesing" and match.place.geo is None
    assert match.place.place_id.startswith("draft-")


def test_a_different_cafe_at_the_same_address_is_not_matched() -> None:
    bakery = OSM_LINDWURM.model_copy(update={"place_id": "osm-node-2", "name": "Bäckerei Zuckerl"})
    assert resolve_place(draft_for("tandem-tuesday-newsletter"), [bakery]).how == "created"


# --- Promotion of the golden set --------------------------------------------------


def test_golden_drafts_become_21_listings_with_tandem_merged() -> None:
    drafts, keys = golden_drafts()
    result = promote(drafts, [], [], RELIABILITY, WEIGHTS)

    rejected = sorted(keys[i] for i, lid in result.draft_to_listing.items() if lid is None)
    assert rejected == ["christmas-market-meetup", "lantern-walk", "thursday-knit-club"]
    assert len(result.listings) == 21
    assert result.merged == 1

    by_key = {keys[i]: lid for i, lid in result.draft_to_listing.items()}
    assert by_key["tandem-tuesday-luma"] == by_key["tandem-tuesday-newsletter"]
    assert by_key["language-cafe-haidhausen"] != by_key["tandem-tuesday-luma"]  # the decoy

    tandem = result.listings[by_key["tandem-tuesday-luma"]]
    assert tandem.source_ids == ["email-inbox", "ical-public-feeds"]
    assert tandem.title.startswith("Tandem Tuesday –")  # iCal (0.85) beats email (0.6)


def test_promotion_never_publishes() -> None:
    drafts, _ = golden_drafts()
    result = promote(drafts, [], [], RELIABILITY, WEIGHTS)
    assert {lst.status for lst in result.listings.values()} == {"needs_review"}


def test_every_tag_carries_the_evidence_of_its_field() -> None:
    drafts, _ = golden_drafts()
    for listing in promote(drafts, [], [], RELIABILITY, WEIGHTS).listings.values():
        for tag in listing.tags:
            assert tag.evidence in listing.field_evidence.values()


def test_schedule_is_built_from_the_phrase_time_and_season() -> None:
    choir = listing_from_draft(draft_for("chor-haidhausen"), OSM_LINDWURM)
    assert choir.schedule is not None
    assert choir.schedule.rrule == "FREQ=WEEKLY;BYDAY=WE"
    assert choir.schedule.dtstart.time() == time(19, 30)
    assert choir.schedule.duration_min == 90
    assert [b.months for b in choir.schedule.breaks] == [[8]]
    assert choir.field_evidence["schedule"].source_text.startswith("Wir proben jeden Mittwoch")


def test_missing_time_means_no_schedule_and_a_note() -> None:
    games = listing_from_draft(draft_for("wuerfel-und-worte"), OSM_LINDWURM)
    assert games.schedule is None
    assert "no schedule yet: no start time" in games.review_notes
    assert "flag: missing_time" in games.review_notes


def test_stale_source_does_not_count_as_verification() -> None:
    assert listing_from_draft(draft_for("photo-walk-club"), OSM_LINDWURM).last_verified_at is None
    assert listing_from_draft(draft_for("clay-and-chat"), OSM_LINDWURM).last_verified_at is not None


# --- Merging -----------------------------------------------------------------------


def _listing(**update: object) -> Listing:
    base = listing_from_draft(draft_for("tandem-tuesday-luma"), OSM_LINDWURM)
    return base.model_copy(update=update)


def test_same_activity_needs_same_place_rule_and_close_start() -> None:
    a = _listing()
    assert same_activity(a, _listing())
    later = a.schedule.model_copy(update={"dtstart": a.schedule.dtstart + timedelta(minutes=45)})
    assert not same_activity(a, _listing(schedule=later))
    other_rule = a.schedule.model_copy(update={"rrule": "FREQ=WEEKLY;BYDAY=WE"})
    assert not same_activity(a, _listing(schedule=other_rule))
    assert not same_activity(a, _listing(place_id="elsewhere"))


def test_conflicting_values_keep_the_more_reliable_source_and_leave_a_note() -> None:
    def ev(source: str) -> Evidence:
        return Evidence(source_id=source, raw_record_id="r", source_text="x", captured_at=NOW)

    from_email = _listing(price_eur=5.0, field_evidence={"price_eur": ev("email-inbox")})
    from_form = _listing(price_eur=0.0, field_evidence={"price_eur": ev("organiser-form")})
    merged = merge(from_email, from_form, RELIABILITY)
    assert merged.price_eur == 0.0  # organiser form (0.9) beats email (0.6)
    assert any(n.startswith("conflict on price_eur") for n in merged.review_notes)


def test_a_conflict_sends_a_published_listing_back_to_review() -> None:
    def ev(source: str) -> Evidence:
        return Evidence(source_id=source, raw_record_id="r", source_text="x", captured_at=NOW)

    published = _listing(status="published", last_verified_at=NOW, language="en",
                         field_evidence={**_listing().field_evidence,
                                         "language": ev("ical-public-feeds")})  # fmt: skip
    newer = _listing(language="de", field_evidence={"language": ev("email-inbox")})
    assert merge(published, newer, RELIABILITY).status == "needs_review"


# --- Regular Score -----------------------------------------------------------------


def _scored(**update: object) -> float:
    listing = _listing(**update)
    listing = listing.model_copy(update={"tags": derive_tags(listing)})
    return regular_score(listing, WEIGHTS).total


def test_score_prefers_what_helps_newcomers_become_regulars() -> None:
    monthly = _listing().schedule.model_copy(update={"rrule": "FREQ=MONTHLY;BYDAY=2TU"})
    easy = _scored(price_eur=0.0, language="en", group_size="small", come_alone=True)
    hard = _scored(price_eur=25.0, language="de", group_size="large", come_alone=False,
                   beginner_friendly=False, schedule=monthly)  # fmt: skip
    assert easy > hard


def test_unknown_counts_as_neutral_and_is_named() -> None:
    listing = _listing(language=None, group_size=None)
    score = regular_score(listing, WEIGHTS)
    assert score.components["english"] == 0.5
    assert score.based_on["english"] == ["unknown: language"]
    assert score.components["group_size"] == 0.5


def test_distance_only_counts_when_given() -> None:
    listing = _listing()
    without = regular_score(listing, WEIGHTS)
    near = regular_score(listing, WEIGHTS, distance_m=500)
    far = regular_score(listing, WEIGHTS, distance_m=20_000)
    assert "distance" not in without.components
    assert near.total > far.total


def test_a_summer_break_lowers_recurrence_a_little() -> None:
    from morehere.models import ScheduleBreak

    plain = _listing()
    summer = [ScheduleBreak(label="Sommerpause", months=[8])]
    with_break = plain.schedule.model_copy(update={"breaks": summer})
    assert regular_score(_listing(schedule=with_break), WEIGHTS).components["recurrence"] == round(
        11 / 12, 3
    )
    assert regular_score(plain, WEIGHTS).components["recurrence"] == 1.0


def test_score_total_stays_between_0_and_1() -> None:
    drafts, _ = golden_drafts()
    for listing in promote(drafts, [], [], RELIABILITY, WEIGHTS).listings.values():
        assert listing.regular_score is not None
        assert 0.0 <= listing.regular_score.total <= 1.0


# --- Freshness --------------------------------------------------------------------


def test_stale_published_listing_is_hidden_and_comes_back_when_reverified() -> None:
    old = _listing(status="published", last_verified_at=NOW - timedelta(days=61))
    hidden, restored = apply_freshness([old], NOW, CONFIG.freshness_days)
    assert restored == [] and hidden[0].status == "hidden"
    assert any(n.startswith(STALE_NOTE) for n in hidden[0].review_notes)

    reverified = hidden[0].model_copy(update={"last_verified_at": NOW})
    hidden2, restored2 = apply_freshness([reverified], NOW, CONFIG.freshness_days)
    assert hidden2 == [] and restored2[0].status == "published"
    assert not any(n.startswith(STALE_NOTE) for n in restored2[0].review_notes)


def test_a_curators_hidden_listing_stays_hidden() -> None:
    hidden_by_curator = _listing(status="hidden", last_verified_at=NOW)
    assert apply_freshness([hidden_by_curator], NOW, CONFIG.freshness_days) == ([], [])


def test_never_verified_counts_as_stale() -> None:
    assert is_stale(_listing(last_verified_at=None), NOW, 60)
    assert not is_stale(_listing(last_verified_at=NOW - timedelta(days=59)), NOW, 60)


# --- Database: the whole flow -----------------------------------------------------


@pytest.fixture
def clean_db(db_engine: Engine):  # type: ignore[no-untyped-def]
    """These tests commit; leave no listings or draft places behind for other tests."""
    from morehere.db.session import session_scope
    from morehere.db.tables import (
        EvidenceRow,
        ListingDraftRow,
        ListingRow,
        PlaceRow,
        RawRecordRow,
    )

    def wipe() -> None:
        with session_scope(db_engine) as s:
            s.execute(delete(ListingDraftRow))
            s.execute(delete(ListingRow))  # cascades to field-evidence links and tags...
            s.execute(  # ...but not to the evidence rows they pointed at
                delete(EvidenceRow).where(EvidenceRow.raw_record_id.startswith("sample-"))
            )
            s.execute(delete(PlaceRow).where(PlaceRow.place_id.startswith("draft-")))
            s.execute(delete(RawRecordRow).where(RawRecordRow.raw_record_id.startswith("sample-")))

    wipe()
    yield db_engine
    wipe()


@pytest.mark.db
def test_promote_pending_end_to_end(clean_db: Engine) -> None:
    db_engine = clean_db
    from morehere.db import repo
    from morehere.db.seed import seed_sources
    from morehere.db.session import session_scope
    from morehere.extract import golden_raw_record
    from morehere.promote import promote_pending

    seed_sources(db_engine)
    as_of = datetime.fromisoformat(GOLDEN.as_of)
    with session_scope(db_engine) as s:
        for f, label in GOLDEN.all_listings():
            raw = golden_raw_record(f.file, f.source_kind, f.content_type, as_of)
            repo.save_raw_record(s, raw)
            draft = golden_draft(GOLDEN, f, label, source_id=raw.source_id,
                                 raw_record_id=raw.raw_record_id)  # fmt: skip
            repo.save_draft(s, draft)

    counts = promote_pending(db_engine, CONFIG)
    assert counts["drafts"] == 25 and counts["rejected"] == 3
    assert counts["merged_into_existing"] == 1

    with session_scope(db_engine) as s:
        listings = repo.list_listings(s)
        assert len(listings) == 21
        assert all(lst.regular_score is not None and lst.review_notes is not None
                   for lst in listings)  # fmt: skip
        assert repo.pending_drafts(s) == []

    again = promote_pending(db_engine, CONFIG)  # nothing pending: nothing changes
    assert again["drafts"] == 0


@pytest.mark.db
def test_listing_with_score_and_notes_round_trips(clean_db: Engine) -> None:
    db_engine = clean_db
    from morehere.db import repo
    from morehere.db.seed import seed_sources
    from morehere.db.session import session_scope
    from morehere.extract import golden_raw_record

    seed_sources(db_engine)
    drafts, _ = golden_drafts()
    listing = next(iter(promote(drafts[:1], [], [], RELIABILITY, WEIGHTS).listings.values()))
    f = GOLDEN.files[0]
    with session_scope(db_engine) as s:
        repo.save_place(s, Place(place_id=listing.place_id, name="x", kind="other"))
        repo.save_raw_record(s, golden_raw_record(f.file, f.source_kind, f.content_type, NOW))
        repo.save_listing(s, listing)
    with session_scope(db_engine) as s:
        assert repo.get_listing(s, listing.listing_id) == listing


def test_first_occurrence_is_on_or_after_the_source_date() -> None:
    listing = listing_from_draft(draft_for("brettspielabend-westend"), OSM_LINDWURM)
    assert listing.schedule is not None
    # Source fetched on Thu 12 Nov 2026, which is itself the 2nd Thursday of November.
    assert listing.schedule.dtstart.date() == datetime(2026, 11, 12).date()
