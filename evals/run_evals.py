"""Run extraction over the golden set and write a report to evals/results/.

    make evals            # live: calls the API (needs ANTHROPIC_API_KEY), records responses
    make evals-recorded   # replay: uses evals/recordings/, no key or network

Options: --model, --effort (default from .env / config/llm.yaml), --tag (added to the
file name, e.g. "baseline").
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from morehere.config import load_city_config
from morehere.evaluation import evaluate, to_json, to_markdown
from morehere.extract import (
    AnthropicBackend,
    Backend,
    MissingCredentials,
    RecordingBackend,
    ReplayBackend,
    extract_record,
    golden_raw_record,
    load_llm_settings,
)
from morehere.golden import GoldenFile, load_golden
from morehere.logging import configure_logging, run_context

RESULTS_DIR = Path(__file__).parent / "results"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--mode", choices=["live", "replay"], default="replay")
    parser.add_argument("--model")
    parser.add_argument("--effort")
    parser.add_argument("--tag", default="")
    args = parser.parse_args()

    load_dotenv()
    configure_logging()
    settings = load_llm_settings(model=args.model, effort=args.effort)
    config = load_city_config()
    golden = load_golden()
    as_of = datetime.fromisoformat(golden.as_of)
    try:
        backend: Backend = (
            RecordingBackend(AnthropicBackend()) if args.mode == "live" else ReplayBackend()
        )
    except MissingCredentials as exc:
        raise SystemExit(f"Error: {exc}") from None

    def extract(gfile: GoldenFile):  # type: ignore[no-untyped-def]
        raw = golden_raw_record(gfile.file, gfile.source_kind, gfile.content_type, as_of)
        return extract_record(raw, backend, settings, config)

    import anthropic

    with run_context() as run_id:
        try:
            report = evaluate(golden, extract)
        except anthropic.APIStatusError as exc:
            # 400/401/403/404: the request itself is wrong, so every document would fail.
            raise SystemExit(f"Error: the API rejected the request ({exc.status_code}): "
                             f"{exc.message}") from None  # fmt: skip

    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    name = "_".join(p for p in [stamp, settings.model, settings.effort, args.mode, args.tag] if p)
    title = (
        f"Extraction eval: {settings.model}, effort {settings.effort} ({args.mode}, run {run_id})"
    )
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / f"{name}.md").write_text(to_markdown(report, title), encoding="utf-8")
    (RESULTS_DIR / f"{name}.json").write_text(
        json.dumps(to_json(report), indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    print(to_markdown(report, title))
    print(f"Saved to {RESULTS_DIR / name}.md")


if __name__ == "__main__":
    main()
