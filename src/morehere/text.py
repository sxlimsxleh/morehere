"""Small text helpers shared by grounding, evals and tests."""

from __future__ import annotations

import re

_WHITESPACE = re.compile(r"\s+")


def normalise_whitespace(text: str) -> str:
    """Collapse every run of whitespace (spaces, tabs, newlines) to one space and trim."""
    return _WHITESPACE.sub(" ", text).strip()


def contains_span(document: str, span: str) -> bool:
    """True if `span` occurs verbatim in `document`, ignoring differences in whitespace."""
    return normalise_whitespace(span) in normalise_whitespace(document)
