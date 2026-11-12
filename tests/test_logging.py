from __future__ import annotations

import json
import logging

import pytest

from morehere.logging import JsonFormatter, run_context, timed_step
from morehere.sources import osm


def _capture(logger: logging.Logger) -> list[str]:
    lines: list[str] = []

    class ListHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            lines.append(JsonFormatter().format(record))

    logger.addHandler(ListHandler())
    logger.setLevel(logging.INFO)
    return lines


def test_timed_step_logs_one_json_line_with_run_id_duration_and_fields() -> None:
    logger = logging.getLogger("morehere.test.timed")
    lines = _capture(logger)
    with run_context("run-123"), timed_step(logger, "demo.step", source="x") as step:
        step["count"] = 3
    record = json.loads(lines[-1])
    assert record["event"] == "demo.step"
    assert record["run_id"] == "run-123"
    assert record["ok"] is True
    assert record["count"] == 3 and record["source"] == "x"
    assert isinstance(record["duration_ms"], int)


def test_timed_step_logs_failure_and_reraises() -> None:
    logger = logging.getLogger("morehere.test.failing")
    lines = _capture(logger)
    with pytest.raises(ValueError), timed_step(logger, "demo.fail"):
        raise ValueError("boom")
    record = json.loads(lines[-1])
    assert record["level"] == "error" and record["ok"] is False
    assert record["error"] == "ValueError: boom"


def test_source_modules_log_under_the_morehere_logger() -> None:
    # Regression: with `python -m`, a logger named __name__ is "__main__" and its lines
    # never reach the JSON handler configured on "morehere".
    assert osm.log.name.startswith("morehere.")
