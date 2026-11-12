"""Structured JSON logs with a run_id (rule 9).

Every ingestion or extraction job runs inside `run_context()`, and every log line it
writes carries the same run_id, so one run can be followed end to end:

    with run_context() as run_id, timed_step(log, "osm.fetch") as step:
        ...
        step["elements"] = 1234      # added to the log line

Each line is one JSON object on stderr: ts, level, logger, run_id, event, plus fields.
"""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

_run_id: ContextVar[str | None] = ContextVar("run_id", default=None)


def current_run_id() -> str | None:
    return _run_id.get()


@contextmanager
def run_context(run_id: str | None = None) -> Iterator[str]:
    """Set the run_id for everything logged inside the block."""
    value = run_id or uuid.uuid4().hex[:12]
    token = _run_id.set(value)
    try:
        yield value
    finally:
        _run_id.reset(token)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "run_id": current_run_id(),
            "event": record.getMessage(),
        }
        line.update(getattr(record, "fields", {}))
        if record.exc_info:
            line["error"] = self.formatException(record.exc_info)
        return json.dumps(line, ensure_ascii=False, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    """Send morehere.* logs to stderr as JSON. Safe to call more than once."""
    root = logging.getLogger("morehere")
    root.setLevel(level)
    if not any(isinstance(h.formatter, JsonFormatter) for h in root.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(JsonFormatter())
        root.addHandler(handler)


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    logger.info(event, extra={"fields": fields})


@contextmanager
def timed_step(logger: logging.Logger, step: str, **fields: Any) -> Iterator[dict[str, Any]]:
    """Log one line when the step ends, with duration_ms and any fields added to the dict.

    If the block raises, the line is logged at error level with ok=false, then re-raised.
    """
    extra: dict[str, Any] = dict(fields)
    start = time.perf_counter()
    try:
        yield extra
    except Exception as exc:
        extra.update(ok=False, error=f"{type(exc).__name__}: {exc}")
        extra["duration_ms"] = round((time.perf_counter() - start) * 1000)
        logger.error(step, extra={"fields": extra})
        raise
    extra.setdefault("ok", True)
    extra["duration_ms"] = round((time.perf_counter() - start) * 1000)
    logger.info(step, extra={"fields": extra})
