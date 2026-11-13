"""Small text helpers shared by grounding, extraction, evals and tests."""

from __future__ import annotations

import re
import unicodedata
from html.parser import HTMLParser

_WHITESPACE = re.compile(r"\s+")


def normalise_whitespace(text: str) -> str:
    """Collapse every run of whitespace (spaces, tabs, newlines) to one space and trim."""
    return _WHITESPACE.sub(" ", text).strip()


def _canonical(text: str) -> str:
    # NFC: "é" typed as one character or as "e" + accent compares equal.
    return normalise_whitespace(unicodedata.normalize("NFC", text))


def contains_span(document: str, span: str) -> bool:
    """True if `span` occurs verbatim in `document`, ignoring differences in whitespace."""
    span = _canonical(span)
    return bool(span) and span in _canonical(document)


# ---------------------------------------------------------------------------
# Document text: what the model reads, and what grounding checks against
# ---------------------------------------------------------------------------

_BLOCK_TAGS = {
    "p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "td", "th",
    "table", "section", "article", "header", "footer", "main", "title", "small", "blockquote",
}  # fmt: skip
_SKIPPED_TAGS = {"script", "style", "noscript", "template"}


class _TextCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)  # &amp; -> &
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIPPED_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    """Visible text of a page, one block per line.

    Text hidden with CSS (display:none) is KEPT on purpose: hidden prompt-injection text
    must reach the injection checks, and the model must see what we check.
    """
    collector = _TextCollector()
    collector.feed(html)
    collector.close()
    lines = (normalise_whitespace(line) for line in "".join(collector.parts).split("\n"))
    return "\n".join(line for line in lines if line)


def document_text(payload: str, content_type: str) -> str:
    """The text extraction sees and grounding checks: HTML as text, everything else as is.

    iCal and email stay raw so property lines ("RRULE:...", "From: ...") remain quotable.
    """
    if "html" in content_type:
        return html_to_text(payload)
    return payload
