"""Load the hand-labelled golden set (golden/labels.json).

The golden set is what evals compare extraction against (milestone 5). Its structure is
validated here so a typo in a label fails loudly instead of skewing accuracy numbers.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from morehere.models import DRAFT_FIELDS, Flag, ScheduleBreak, SourceKind

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
