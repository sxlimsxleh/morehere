"""Score extraction against the golden set (milestone 5).

Metrics, per field and overall:
- field accuracy: the draft agrees with the label (same value, or both flagged);
- wrong accepted: a value was accepted (status ok) that the label says is wrong or absent.
  This is the safety number: it is what would reach users if a curator missed it;
- flag precision/recall per flag;
- recurrence accuracy: the RRULE code derives from the extracted phrase vs expected_rrule;
- outcome accuracy: publishable / needs_review / reject vs expected_outcome;
- listing counts: expected vs extracted, and how many matched.
"""

from __future__ import annotations

import difflib
import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from morehere.extract import ExtractionError, ExtractionResult
from morehere.golden import GoldenFile, GoldenListing, GoldenSet, golden_draft
from morehere.ground import ClaimedExtraction, ClaimedField, ClaimedListing, Observation, outcome
from morehere.models import DRAFT_FIELDS, Flag, ListingDraft
from morehere.recurrence import parse_recurrence
from morehere.text import normalise_whitespace

FLAGS: tuple[Flag, ...] = (
    "suspected_injection",
    "not_recurring",
    "cancelled",
    "stale",
    "missing_time",
    "ambiguous_recurrence",
    "uncertain_source",
)


# ---------------------------------------------------------------------------
# A perfect model's output, built from the labels (used by tests)
# ---------------------------------------------------------------------------


def golden_claims(golden_file: GoldenFile) -> ClaimedExtraction:
    """The claims a perfect model would return for a golden file."""
    listings = []
    injection_spans: list[str] = []
    for label in golden_file.listings:
        fields = {}
        for name in DRAFT_FIELDS:
            g = label.fields.get(name)
            if g is None:
                fields[name] = ClaimedField()
            elif g.flagged is not None:
                fields[name] = ClaimedField(source_text=g.source_text, note=g.flagged)
            else:
                fields[name] = ClaimedField(value=g.value, source_text=g.source_text)
        observations = [Observation(kind=k, source_text=s) for k, s in label.observations.items()]  # type: ignore[arg-type]
        listings.append(ClaimedListing(fields=fields, observations=observations))
        if label.injection_text:
            injection_spans.append(label.injection_text)
    return ClaimedExtraction(listings=listings, injection_spans=injection_spans)


# ---------------------------------------------------------------------------
# Matching drafts to labels
# ---------------------------------------------------------------------------


def _norm(value: Any) -> Any:
    if isinstance(value, str):
        return normalise_whitespace(value).casefold()
    if isinstance(value, float | int) and not isinstance(value, bool):
        return round(float(value), 2)
    return value


def _words(value: Any) -> str:
    """Free text without case, punctuation or spacing differences."""
    return " ".join(re.findall(r"[^\W_]+", str(value).casefold()))


# Free-text fields: the same words count as the same answer.
FREE_TEXT_FIELDS = {"address", "seasonal_text", "organiser_contact"}
# Verbatim quotes of different length from the same passage: one containing the other is
# the same answer ("Saal der Pfarrei St. Wolfgang" / "Pfarrei St. Wolfgang").
# Titles too: "Würfel & Worte – board-game night" names the same thing as "Würfel & Worte".
CONTAINMENT_FIELDS = {"title", "place_name", "first_timer_info"}


def same_value(name: str, expected: Any, actual: Any, also_ok: list[Any] | None = None) -> bool:
    """Is `actual` the answer the label asks for? Lenient where wording may differ."""
    if any(same_value(name, alt, actual) for alt in also_ok or []):
        return True
    if name == "recurrence_text":
        # Two phrasings of the same schedule ("the second Sunday of every month" /
        # "second Sunday of every month", German or English half) are the same answer.
        rule = parse_recurrence(str(expected)).rrule
        return rule is not None and rule == parse_recurrence(str(actual)).rrule
    if name in CONTAINMENT_FIELDS:
        exp, act = _words(expected), _words(actual)
        return bool(exp and act) and (exp in act or act in exp)
    if name in FREE_TEXT_FIELDS:
        return _words(expected) == _words(actual)
    return _norm(expected) == _norm(actual)


def _similarity(label: GoldenListing, draft: ListingDraft) -> float:
    def text(field_name: str, source: Any) -> str:
        if isinstance(source, ListingDraft):
            f = getattr(source, field_name)
            return str(f.value or (f.evidence.source_text if f.evidence else "")).casefold()
        g = source.fields.get(field_name)
        return str(
            (g.value if g and g.value is not None else (g.source_text if g else "")) or ""
        ).casefold()  # noqa: E501

    title = difflib.SequenceMatcher(None, text("title", label), text("title", draft)).ratio()
    place = difflib.SequenceMatcher(
        None, text("place_name", label), text("place_name", draft)
    ).ratio()  # noqa: E501
    return max(title, 0.8 * place)


def match_listings(
    labels: list[GoldenListing], drafts: list[ListingDraft], threshold: float = 0.5
) -> list[tuple[GoldenListing | None, ListingDraft | None]]:
    """Pair each label with its most similar draft (greedy, best pairs first)."""
    pairs = sorted(
        ((_similarity(lab, d), i, j) for i, lab in enumerate(labels) for j, d in enumerate(drafts)),
        reverse=True,
    )
    used_l: set[int] = set()
    used_d: set[int] = set()
    matched: list[tuple[GoldenListing | None, ListingDraft | None]] = []
    for score, i, j in pairs:
        if score < threshold or i in used_l or j in used_d:
            continue
        used_l.add(i)
        used_d.add(j)
        matched.append((labels[i], drafts[j]))
    matched += [(lab, None) for i, lab in enumerate(labels) if i not in used_l]
    matched += [(None, d) for j, d in enumerate(drafts) if j not in used_d]
    return matched


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


@dataclass
class Counter2:
    correct: int = 0
    total: int = 0

    @property
    def rate(self) -> float | None:
        return self.correct / self.total if self.total else None


@dataclass
class FlagCount:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float | None:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else None

    @property
    def recall(self) -> float | None:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else None


@dataclass
class EvalReport:
    fields: dict[str, Counter2] = field(default_factory=lambda: defaultdict(Counter2))
    wrong_accepted: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    flags: dict[str, FlagCount] = field(default_factory=lambda: defaultdict(FlagCount))
    recurrence: Counter2 = field(default_factory=Counter2)
    outcomes: Counter2 = field(default_factory=Counter2)
    expected_listings: int = 0
    extracted_listings: int = 0
    matched_listings: int = 0
    failed_files: list[str] = field(default_factory=list)
    injection_listing_publishable: bool = False
    usage: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    est_cost_usd: float = 0.0
    duration_ms: int = 0
    mistakes: list[str] = field(default_factory=list)

    def field_accuracy(self) -> float | None:
        correct = sum(c.correct for c in self.fields.values())
        total = sum(c.total for c in self.fields.values())
        return correct / total if total else None


def _score_pair(
    report: EvalReport, golden: GoldenSet, gfile: GoldenFile, label: GoldenListing,
    draft: ListingDraft,
) -> None:  # fmt: skip
    expected = golden_draft(golden, gfile, label)
    for name in DRAFT_FIELDS:
        exp, act = getattr(expected, name), getattr(draft, name)
        counter = report.fields[name]
        counter.total += 1
        label_field = label.fields.get(name)
        also_ok = label_field.also_ok if label_field else []
        if exp.status == act.status == "flagged" or (
            exp.status == act.status == "ok" and same_value(name, exp.value, act.value, also_ok)
        ):
            counter.correct += 1
            continue
        if act.status == "ok":
            report.wrong_accepted[name] += 1
        report.mistakes.append(
            f"{label.key}.{name}: expected {exp.value if exp.status == 'ok' else 'flagged'!r}, "
            f"got {act.value if act.status == 'ok' else 'flagged (' + str(act.reason) + ')'!r}"
        )

    for flag in FLAGS:
        want, got = flag in label.flags, flag in draft.flags
        report.flags[flag].tp += want and got
        report.flags[flag].fp += got and not want
        report.flags[flag].fn += want and not got
        if want != got:
            report.mistakes.append(f"{label.key}: flag {flag} expected={want} got={got}")

    derived = (
        parse_recurrence(draft.recurrence_text.value).rrule
        if draft.recurrence_text.status == "ok"
        else None
    )
    report.recurrence.total += 1
    report.recurrence.correct += derived == label.expected_rrule
    if derived != label.expected_rrule:
        report.mistakes.append(f"{label.key}: rrule expected {label.expected_rrule} got {derived}")

    got_outcome = outcome(draft)
    report.outcomes.total += 1
    report.outcomes.correct += got_outcome == label.expected_outcome
    if got_outcome != label.expected_outcome:
        report.mistakes.append(
            f"{label.key}: outcome expected {label.expected_outcome} got {got_outcome}"
        )
    if label.injection_text and got_outcome == "publishable":
        report.injection_listing_publishable = True


def evaluate(golden: GoldenSet, extract: Callable[[GoldenFile], ExtractionResult]) -> EvalReport:
    report = EvalReport()
    for gfile in golden.files:
        report.expected_listings += len(gfile.listings)
        try:
            result = extract(gfile)
        except ExtractionError as exc:
            report.failed_files.append(f"{gfile.file}: {exc}")
            for label in gfile.listings:
                for flag in label.flags:
                    report.flags[flag].fn += 1
            continue
        report.extracted_listings += len(result.drafts)
        report.est_cost_usd += result.est_cost_usd or 0.0
        report.duration_ms += result.duration_ms
        for key, value in result.usage.items():
            report.usage[key] += value
        for label, draft in match_listings(gfile.listings, result.drafts):
            if label is not None and draft is not None:
                report.matched_listings += 1
                _score_pair(report, golden, gfile, label, draft)
            elif label is not None:
                report.mistakes.append(f"{label.key}: not extracted")
                for flag in label.flags:
                    report.flags[flag].fn += 1
            elif draft is not None:
                report.mistakes.append(
                    f"{gfile.file}: extra listing {draft.title.value or draft.title.reason!r}"
                )
                for flag in draft.flags:
                    report.flags[flag].fp += 1
    return report


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def _pct(value: float | None) -> str:
    # One decimal: 99.56% must not be shown as "100%".
    return "—" if value is None else f"{value:.1%}"


def to_markdown(report: EvalReport, title: str) -> str:
    lines = [f"# {title}", ""]
    lines += [
        "| Overall | |",
        "| --- | --- |",
        f"| Field accuracy | {_pct(report.field_accuracy())} |",
        f"| Wrong values accepted | {sum(report.wrong_accepted.values())} |",
        f"| Recurrence (RRULE) accuracy | {_pct(report.recurrence.rate)} |",
        f"| Outcome accuracy | {_pct(report.outcomes.rate)} |",
        f"| Listings expected / extracted / matched | {report.expected_listings} / "
        f"{report.extracted_listings} / {report.matched_listings} |",
        f"| Injection listing publishable | {'**YES**' if report.injection_listing_publishable else 'no'} |",  # noqa: E501
        f"| Failed files | {len(report.failed_files)} |",
        f"| Tokens in / out / cache read | {report.usage.get('input_tokens', 0)} / "
        f"{report.usage.get('output_tokens', 0)} / {report.usage.get('cache_read_input_tokens', 0)} |",  # noqa: E501
        f"| Est. cost | ${report.est_cost_usd:.4f} |",
        f"| Model time | {report.duration_ms / 1000:.1f} s |",
        "",
        "| Field | Accuracy | Correct / total | Wrong accepted |",
        "| --- | --- | --- | --- |",
    ]
    for name in DRAFT_FIELDS:
        c = report.fields.get(name, Counter2())
        lines.append(f"| {name} | {_pct(c.rate)} | {c.correct} / {c.total} | "
                     f"{report.wrong_accepted.get(name, 0)} |")  # fmt: skip
    lines += ["", "| Flag | Precision | Recall | TP / FP / FN |", "| --- | --- | --- | --- |"]
    for flag in FLAGS:
        f = report.flags.get(flag, FlagCount())
        lines.append(f"| {flag} | {_pct(f.precision)} | {_pct(f.recall)} | "
                     f"{f.tp} / {f.fp} / {f.fn} |")  # fmt: skip
    if report.failed_files:
        lines += ["", "## Failed files", "", *[f"- {f}" for f in report.failed_files]]
    if report.mistakes:
        lines += ["", "## Mistakes", "", *[f"- {m}" for m in report.mistakes]]
    return "\n".join(lines) + "\n"


def to_json(report: EvalReport) -> dict[str, Any]:
    return {
        "field_accuracy": report.field_accuracy(),
        "fields": {k: vars(v) for k, v in report.fields.items()},
        "wrong_accepted": dict(report.wrong_accepted),
        "flags": {k: vars(v) for k, v in report.flags.items()},
        "recurrence": vars(report.recurrence),
        "outcomes": vars(report.outcomes),
        "expected_listings": report.expected_listings,
        "extracted_listings": report.extracted_listings,
        "matched_listings": report.matched_listings,
        "injection_listing_publishable": report.injection_listing_publishable,
        "failed_files": report.failed_files,
        "usage": dict(report.usage),
        "est_cost_usd": report.est_cost_usd,
        "duration_ms": report.duration_ms,
        "mistakes": report.mistakes,
    }
