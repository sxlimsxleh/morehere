"""Load the hand-labelled golden set (golden/labels.json).

The golden set is what evals compare extraction against (milestone 5). Its structure is
validated here so a typo in a label fails loudly instead of skewing accuracy numbers.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from morehere.models import DRAFT_FIELDS, Evidence, Flag, ListingDraft, ScheduleBreak, SourceKind

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LABELS_PATH = REPO_ROOT / "golden" / "labels.json"
DEFAULT_RAW_DIR = REPO_ROOT / "data" / "raw"

ExpectedOutcome = Literal["publishable", "needs_review", "reject"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GoldenField(_Strict):
    """Either a stated value with its source span, or a reason the field must be flagged."""

    value: Any = None
    source_text: str | None = None
    flagged: str | None = None
    # Other values that are also right for a judgement call (e.g. a photo walk is
    # "outdoors" or "arts_crafts"). Scored as correct; never used as the expected draft.
    also_ok: list[Any] = Field(default_factory=list)

    @model_validator(mode="after")
    def _value_xor_flagged(self) -> GoldenField:
        if (self.value is None) == (self.flagged is None):
            raise ValueError("a golden field has either 'value' or 'flagged', not both or neither")
        if self.value is not None and not self.source_text:
            raise ValueError("a golden value needs its source_text")
        return self


class GoldenListing(_Strict):
    key: str
    expected_outcome: ExpectedOutcome
    merge_group: str | None
    flags: list[Flag]
    expected_rrule: str | None
    expected_breaks: list[ScheduleBreak] = Field(default_factory=list)
    expected_exdates: list[str] = Field(default_factory=list)
    injection_text: str | None = None
    # Spans a correct extraction quotes for model-reported flags, e.g. {"cancelled": "..."}.
    observations: dict[str, str] = Field(default_factory=dict)
    fields: dict[str, GoldenField]

    @model_validator(mode="after")
    def _known_fields(self) -> GoldenListing:
        unknown = set(self.fields) - set(DRAFT_FIELDS)
        if unknown:
            raise ValueError(f"unknown field(s) in label {self.key}: {sorted(unknown)}")
        return self


class GoldenFile(_Strict):
    file: str
    source_kind: SourceKind
    content_type: str
    notes: str
    listings: list[GoldenListing] = Field(min_length=1)


class GoldenSet(_Strict):
    version: int
    as_of: str
    conventions: dict[str, str]
    files: list[GoldenFile]

    def all_listings(self) -> list[tuple[GoldenFile, GoldenListing]]:
        return [(f, listing) for f in self.files for listing in f.listings]


def load_golden(path: Path = DEFAULT_LABELS_PATH) -> GoldenSet:
    return GoldenSet.model_validate(json.loads(path.read_text(encoding="utf-8")))


def golden_draft(
    golden: GoldenSet,
    golden_file: GoldenFile,
    listing: GoldenListing,
    source_id: str | None = None,
    raw_record_id: str | None = None,
) -> ListingDraft:
    """The ListingDraft a perfect extractor would return for this label.

    Used by tests (to check labels fit the contracts) and by evals (as the expected value).
    Pass source_id/raw_record_id to get a draft that fits real database rows: they are set
    on the draft *and* on every piece of its evidence.
    """
    captured_at = datetime.fromisoformat(golden.as_of).replace(tzinfo=UTC)  # all times are UTC
    source_id = source_id or f"golden-{golden_file.source_kind}"
    raw_record_id = raw_record_id or golden_file.file
    data: dict[str, object] = {
        "raw_record_id": raw_record_id,
        "source_id": source_id,
        "extracted_at": captured_at,
        "flags": listing.flags,
    }
    for name in DRAFT_FIELDS:
        label = listing.fields.get(name)
        if label is None:
            data[name] = {"status": "flagged", "reason": "not stated"}
            continue
        evidence = None
        if label.source_text:
            evidence = Evidence(
                source_id=source_id,
                raw_record_id=raw_record_id,
                source_text=label.source_text,
                captured_at=captured_at,
            )
        if label.flagged is not None:
            data[name] = {"status": "flagged", "reason": label.flagged, "evidence": evidence}
        else:
            data[name] = {"status": "ok", "value": label.value, "evidence": evidence}
    return ListingDraft.model_validate(data)
