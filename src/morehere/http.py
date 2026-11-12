"""Shared HTTP retry policy for every source that fetches over the network.

Retries: 429, 502, 503, 504, network errors, and any exception a caller marks as
retryable. Never retries other 4xx (the request itself is wrong). Honours Retry-After.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

import httpx
from tenacity import RetryCallState, Retrying, retry_if_exception, stop_after_attempt
from tenacity import wait_exponential as _wait_exponential

RETRY_STATUSES = frozenset({429, 502, 503, 504})
# Identifies us to the APIs we call; no personal details.
USER_AGENT = "morehere/0.1 (Munich third-places scout)"

_backoff = _wait_exponential(multiplier=2, min=2, max=60)


def make_client(timeout_s: float = 60.0) -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT}, timeout=httpx.Timeout(timeout_s), follow_redirects=True
    )


def is_retryable(exc: BaseException, extra: tuple[type[BaseException], ...] = ()) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRY_STATUSES
    return isinstance(exc, (httpx.TransportError, *extra))


def wait_with_retry_after(retry_state: RetryCallState) -> float:
    """Use the server's Retry-After (capped at 2 min) if it sent one, else back off."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, httpx.HTTPStatusError):
        retry_after = exc.response.headers.get("Retry-After", "")
        if retry_after.isdigit():
            return min(float(retry_after), 120.0)
    return _backoff(retry_state)


def retrying(
    logger: logging.Logger,
    event: str,
    *,
    max_attempts: int = 4,
    sleep: Callable[[float], None] = time.sleep,
    extra_retryable: tuple[type[BaseException], ...] = (),
) -> Retrying:
    """A tenacity Retrying object; use as `for attempt in retrying(...): with attempt: ...`."""
    return Retrying(
        retry=retry_if_exception(lambda e: is_retryable(e, extra_retryable)),
        wait=wait_with_retry_after,
        stop=stop_after_attempt(max_attempts),
        sleep=sleep,
        reraise=True,
        before_sleep=lambda rs: logger.warning(
            event,
            extra={
                "fields": {
                    "attempt": rs.attempt_number,
                    "error": repr(rs.outcome.exception() if rs.outcome else None),
                }
            },
        ),
    )
