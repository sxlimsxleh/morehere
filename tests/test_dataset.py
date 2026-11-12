"""Keep the golden set honest: every label must match its raw file and the data contracts.

If one of these fails after editing data/raw/ or golden/labels.json, fix the data, not
the test: evals in milestone 5 are only as good as these labels.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from morehere.config import load_city_config
from morehere.golden import DEFAULT_RAW_DIR, GoldenFile, GoldenListing, load_golden
from morehere.models import DRAFT_FIELDS, Evidence, ListingDraft
from morehere.text import contains_span

GOLDEN = load_golden()
ALL_LISTINGS = GOLDEN.all_listings()
LISTING_IDS = [listing.key for _, listing in ALL_LISTINGS]


def raw_text(golden_file: GoldenFile) -> str:
    return (DEFAULT_RAW_DIR / golden_file.file).read_text(encoding="utf-8")


def to_draft(golden_file: GoldenFile, listing: GoldenListing) -> ListingDraft:
    """Build the ListingDraft a perfect extractor would return for this label."""
    captured_at = datetime.fromisoformat(GOLDEN.as_of)
    data: dict[str, object] = {
        "raw_record_id": golden_file.file,
        "source_id": f"golden-{golden_file.source_kind}",
        "extracted_at": captured_at,
        "flags": listing.flags,
    }
    for name in DRAFT_FIELDS:
        label = listing.fields.get(name)
        evidence = None
        if label is not None and label.source_text:
            evidence = Evidence(
                source_id=f"golden-{golden_file.source_kind}",
                raw_record_id=golden_file.file,
                source_text=label.source_text,
                captured_at=captured_at,
            )
        if label is None:
            data[name] = {"status": "flagged", "reason": "not stated"}
        elif label.flagged is not None:
            data[name] = {"status": "flagged", "reason": label.flagged, "evidence": evidence}
        else:
            data[name] = {"status": "ok", "value": label.value, "evidence": evidence}
    return ListingDraft.model_validate(data)


# --- Files and labels line up ------------------------------------------------


def test_every_raw_file_has_exactly_one_label() -> None:
    on_disk = sorted(p.name for p in Path(DEFAULT_RAW_DIR).iterdir() if p.is_file())
    labelled = sorted(f.file for f in GOLDEN.files)
    assert on_disk == labelled


def test_listing_keys_are_unique() -> None:
    assert len(LISTING_IDS) == len(set(LISTING_IDS))


def test_dataset_size_is_in_range() -> None:
    assert 20 <= len(GOLDEN.files) <= 30


# --- Each label is grounded and valid ----------------------------------------


@pytest.mark.parametrize(("golden_file", "listing"), ALL_LISTINGS, ids=LISTING_IDS)
def test_every_source_text_occurs_in_its_raw_file(
    golden_file: GoldenFile, listing: GoldenListing
) -> None:
    text = raw_text(golden_file)
    missing = [
        f"{name}: {label.source_text!r}"
        for name, label in listing.fields.items()
        if label.source_text and not contains_span(text, label.source_text)
    ]
    if listing.injection_text and not contains_span(text, listing.injection_text):
        missing.append(f"injection_text: {listing.injection_text!r}")
    assert not missing, "source_text not found in raw file:\n" + "\n".join(missing)


@pytest.mark.parametrize(("golden_file", "listing"), ALL_LISTINGS, ids=LISTING_IDS)
def test_every_label_builds_a_valid_listing_draft(
    golden_file: GoldenFile, listing: GoldenListing
) -> None:
    draft = to_draft(golden_file, listing)
    assert draft.flags == listing.flags


@pytest.mark.parametrize(("golden_file", "listing"), ALL_LISTINGS, ids=LISTING_IDS)
def test_district_labels_follow_the_config(golden_file: GoldenFile, listing: GoldenListing) -> None:
    config = load_city_config()
    canonical = {d.name for d in config.districts}
    label = listing.fields.get("district")
    if label is None:
        return
    if label.flagged is None:
        assert label.value in canonical
    else:
        assert label.source_text is not None
        # A flagged district must really be ambiguous: some alias in the span maps to 2+.
        words = label.source_text.replace(",", " ").split()
        assert any(len(config.districts_for(w)) > 1 for w in words)


@pytest.mark.parametrize(("golden_file", "listing"), ALL_LISTINGS, ids=LISTING_IDS)
def test_outcome_matches_flags(golden_file: GoldenFile, listing: GoldenListing) -> None:
    flags = set(listing.flags)
    if listing.expected_outcome == "publishable":
        assert not flags
        assert listing.fields["place_name"].flagged is None
        assert listing.fields["recurrence_text"].flagged is None
        assert listing.expected_rrule is not None
    elif listing.expected_outcome == "reject":
        assert flags & {"not_recurring", "cancelled"}
    else:
        assert flags


@pytest.mark.parametrize(("golden_file", "listing"), ALL_LISTINGS, ids=LISTING_IDS)
def test_expected_rrules_are_well_formed(golden_file: GoldenFile, listing: GoldenListing) -> None:
    if listing.expected_rrule is not None:
        assert listing.expected_rrule.startswith("FREQ=")
    if "not_recurring" in listing.flags or "ambiguous_recurrence" in listing.flags:
        assert listing.expected_rrule is None
    for exdate in listing.expected_exdates:
        TypeAdapter(datetime).validate_python(f"{exdate}T00:00:00")


# --- The dataset covers what CLAUDE.md milestone 1 asks for ------------------


def test_dataset_covers_required_cases() -> None:
    flags = {flag for _, listing in ALL_LISTINGS for flag in listing.flags}
    assert {"suspected_injection", "not_recurring", "stale", "missing_time"} <= flags

    rrules = {listing.expected_rrule for _, listing in ALL_LISTINGS}
    assert "FREQ=MONTHLY;BYDAY=2TH" in rrules  # jeden 2. Donnerstag
    assert "FREQ=MONTHLY;BYDAY=1MO" in rrules  # every first Monday

    assert any(listing.expected_breaks for _, listing in ALL_LISTINGS)

    prices = {
        listing.fields["price_eur"].value
        for _, listing in ALL_LISTINGS
        if "price_eur" in listing.fields and listing.fields["price_eur"].flagged is None
    }
    assert 0 in prices and any(p > 0 for p in prices)

    kinds = {f.source_kind for f in GOLDEN.files}
    assert {"ical", "email", "submission", "tip", "web_page"} <= kinds

    groups: dict[str, set[str]] = {}
    for golden_file, listing in ALL_LISTINGS:
        if listing.merge_group:
            groups.setdefault(listing.merge_group, set()).add(golden_file.source_kind)
    assert any({"ical", "email"} <= kinds_in_group for kinds_in_group in groups.values())


def test_dataset_has_german_and_english_inputs() -> None:
    languages = {
        listing.fields["language"].value
        for _, listing in ALL_LISTINGS
        if "language" in listing.fields and listing.fields["language"].flagged is None
    }
    assert {"de", "en", "en+de"} <= languages
