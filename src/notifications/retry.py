"""
Retry helper — exponential backoff with jitter for notification delivery.

Usage:
    from src.notifications.retry import retry_with_backoff

    retry_with_backoff(lambda: send_http_request(...), attempts=3, base_delay=1.0)

Only retries on transient errors (network timeouts, 429, 5xx HTTP responses).
4xx client errors (except 429) are not retried — they indicate a bad request
that won't succeed on retry.
"""
from __future__ import annotations

import logging
import random
import time
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# HTTP status codes that warrant a retry
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class TransientError(Exception):
    """Raised by callers to signal a retryable failure."""


def retry_with_backoff(
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    jitter: float = 0.5,
    label: str = "operation",
) -> T:
    """
    Call fn() up to `attempts` times with exponential backoff between retries.

    Args:
        fn:         Zero-argument callable to retry.
        attempts:   Maximum number of attempts (including the first try).
        base_delay: Initial delay in seconds before the first retry.
        max_delay:  Cap on sleep duration.
        jitter:     Random fraction of the delay added to prevent thundering herd.
        label:      Human-readable label used in log messages.

    Returns:
        The return value of fn() on success.

    Raises:
        The last exception raised by fn() after all attempts are exhausted.
    """
    last_exc: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except TransientError as exc:
            last_exc = exc
        except Exception as exc:
            # Non-transient errors bubble up immediately
            raise

        if attempt < attempts:
            delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
            delay += random.uniform(0, jitter * delay)
            logger.warning(
                "%s failed on attempt %d/%d — retrying in %.1fs: %s",
                label, attempt, attempts, delay, last_exc,
            )
            time.sleep(delay)

    logger.error("%s failed after %d attempts: %s", label, attempts, last_exc)
    raise last_exc  # type: ignore[misc]
