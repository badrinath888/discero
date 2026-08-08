"""Lightweight in-process rate limiting for abuse-prone auth endpoints.

Deliberately not backed by Redis or any external store: this is a
single-process sliding-window counter, appropriate for the current
single-instance deployment. It will not coordinate limits across
multiple backend instances/workers -- see README for that caveat.
"""

import time
from collections import defaultdict
from threading import Lock

from fastapi import HTTPException, Request

_attempts: dict[str, list[float]] = defaultdict(list)
_lock = Lock()


def reset_rate_limits() -> None:
    """Test-only hook: clears all in-memory rate-limit state."""
    with _lock:
        _attempts.clear()


def _check(key: str, *, max_attempts: int, window_seconds: float) -> None:
    now = time.monotonic()

    with _lock:
        recent = [
            t for t in _attempts[key] if now - t < window_seconds
        ]

        if len(recent) >= max_attempts:
            _attempts[key] = recent
            raise HTTPException(
                status_code=429,
                detail="too many attempts, please try again later",
            )

        recent.append(now)
        _attempts[key] = recent


def rate_limiter(
    *, max_attempts: int, window_seconds: float = 60.0
):
    """FastAPI dependency factory: limits attempts per client IP."""

    def dependency(request: Request) -> None:
        client_ip = (
            request.client.host if request.client else "unknown"
        )
        key = f"{request.url.path}:{client_ip}"
        _check(
            key,
            max_attempts=max_attempts,
            window_seconds=window_seconds,
        )

    return dependency
