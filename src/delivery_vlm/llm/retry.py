from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import Any, TypeVar

try:
    from openai import (  # type: ignore
        APIConnectionError,
        APIStatusError,
        APITimeoutError,
        RateLimitError,
    )
except Exception:  # noqa: BLE001
    APIConnectionError = APIStatusError = APITimeoutError = RateLimitError = ()  # type: ignore

T = TypeVar("T")


def _is_timeout_exc(e: BaseException) -> bool:
    if isinstance(e, APITimeoutError):
        return True
    msg = (str(e) or "").lower()
    return "timed out" in msg or "timeout" in msg


def _is_retryable_exc(e: BaseException) -> bool:
    if isinstance(e, (APIConnectionError, APITimeoutError, RateLimitError)):
        return True
    if isinstance(e, APIStatusError):
        code = getattr(e, "status_code", None)
        if code in (429, 500, 502, 503, 504):
            return True
        if isinstance(code, int) and 500 <= code <= 599:
            return True
        return False
    msg = (str(e) or "").lower()
    return any(
        k in msg
        for k in (
            "timeout",
            "timed out",
            "connection",
            "connect",
            "reset",
            "temporarily",
            "try again",
            "rate limit",
            "429",
            "502",
            "503",
            "504",
            "service unavailable",
            "bad gateway",
            "gateway",
            "empty response",
            "empty body",
            "no content",
        )
    )


def call_with_retries_timeout(
    fn: Callable[[float], T],
    *,
    base_timeout_s: float,
    tries: int = 3,
    base_sleep_s: float = 1.0,
    max_sleep_s: float = 8.0,
    on_retry: Callable[[int, BaseException, float, float], Any] | None = None,
) -> T:
    if tries < 1:
        tries = 1
    next_timeout_s = float(base_timeout_s)
    for attempt in range(1, tries + 1):
        timeout_s = next_timeout_s
        try:
            return fn(timeout_s)
        except Exception as e:  # noqa: BLE001
            if attempt >= tries or (not _is_retryable_exc(e)):
                raise
            if _is_timeout_exc(e):
                next_timeout_s = float(base_timeout_s) * 2.0
            sleep_s = min(max_sleep_s, base_sleep_s * (2 ** (attempt - 1)))
            sleep_s = sleep_s * (0.75 + random.random() * 0.5)
            if on_retry is not None:
                on_retry(attempt, e, float(sleep_s), float(next_timeout_s))
            time.sleep(float(sleep_s))
    return fn(next_timeout_s)
