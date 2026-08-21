"""Rate limiting for abuse-prone endpoints.

Two interchangeable backends behind one interface:

  - In-process sliding window (default) -- a single dictionary guarded
    by a lock, exactly the original implementation. Correct for local
    dev/test/CI, but each process enforces its own separate count: it
    does NOT coordinate across multiple Render instances, so it must
    never be treated as the production abuse control once more than
    one instance is running.
  - Redis-backed sliding window (opt-in via REDIS_URL) -- every
    instance shares the same counters, atomically, via a Lua script
    Redis executes as a single server-side operation. This is the
    production-capable backend for horizontal scale. If Redis becomes
    unreachable, `_ResilientLimiter` falls back to the same in-process
    limiter (never an unconditional allow) for a short cooldown, then
    automatically retries Redis -- see its docstring.

Selecting REDIS_URL is the only thing that changes which backend a
deployment uses; callers of `rate_limiter()`/`authenticated_rate_limiter()`
are unaffected either way.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from threading import Lock
from uuid import uuid4

from fastapi import Depends, HTTPException, Request

from app.auth import get_current_user
from app.config import settings
from app.models import User

logger = logging.getLogger(__name__)

_TOO_MANY_ATTEMPTS = "too many attempts, please try again later"

# How long a Redis failure is trusted to still be ongoing before the
# next request is allowed to try Redis again. Short enough that a real
# recovery is picked up quickly, long enough that a sustained outage
# doesn't turn into a Redis round-trip attempt on every single request.
_REDIS_FAILURE_COOLDOWN_SECONDS = 5.0

# Atomicity matters here specifically because multiple app instances
# may run this against the same Redis concurrently: the script prunes
# expired entries, counts what's left, and only then admits the new
# attempt, all as one indivisible server-side operation (Redis executes
# a whole script without interleaving other clients' commands). A
# naive two-step "read count, then maybe write" from Python would let
# two concurrent requests both read a stale under-limit count and both
# get admitted, silently doubling the effective limit under load --
# exactly the failure mode a shared limiter exists to prevent.
_SLIDING_WINDOW_SCRIPT = """
local key = KEYS[1]
local now_ms = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])
local max_attempts = tonumber(ARGV[3])
local member = ARGV[4]

redis.call('ZREMRANGEBYSCORE', key, '-inf', now_ms - window_ms)
local count = redis.call('ZCARD', key)

if count >= max_attempts then
    return 0
end

redis.call('ZADD', key, now_ms, member)
redis.call('PEXPIRE', key, window_ms)
return 1
"""


class _InMemoryLimiter:
    """Original single-process sliding-window counter."""

    def __init__(self) -> None:
        self._attempts: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def reset(self) -> None:
        with self._lock:
            self._attempts.clear()

    def allow(
        self, key: str, *, max_attempts: int, window_seconds: float
    ) -> bool:
        now = time.monotonic()

        with self._lock:
            recent = [
                t for t in self._attempts[key] if now - t < window_seconds
            ]

            if len(recent) >= max_attempts:
                self._attempts[key] = recent
                return False

            recent.append(now)
            self._attempts[key] = recent
            return True


class _RedisLimiter:
    """Sliding-window counter backed by a Redis sorted set per key,
    shared by every backend instance pointed at the same Redis.

    Raises on a Redis/connection error rather than swallowing it --
    `_ResilientLimiter` is what decides how to degrade, so this class
    stays a thin, honest wrapper around the script call.
    """

    def __init__(self, client) -> None:
        self._client = client
        self._script = client.register_script(_SLIDING_WINDOW_SCRIPT)

    def allow(
        self, key: str, *, max_attempts: int, window_seconds: float
    ) -> bool:
        window_ms = int(window_seconds * 1000)
        now_ms = int(time.time() * 1000)
        # A random member (not just the timestamp) so two attempts
        # landing in the same millisecond never collide as the same
        # sorted-set member and get silently deduplicated into one.
        member = f"{now_ms}-{uuid4().hex}"

        result = self._script(
            keys=[f"ratelimit:{key}"],
            args=[now_ms, window_ms, max_attempts, member],
        )

        return bool(result)


class _ResilientLimiter:
    """Redis-backed limiting with an automatic local fallback.

    Redis healthy -> every instance shares the distributed limiter.
    Redis raises -> the same call is immediately enforced by the
    local, single-process limiter instead (never an unconditional
    allow -- a Redis outage must not become unlimited traffic on a
    financial API), and for `cooldown_seconds` afterwards every call
    skips Redis entirely and goes straight to local, so a dead
    connection isn't retried on every single request while an outage
    is ongoing. Once the cooldown elapses, the next call retries
    Redis: success resumes the shared limiter, another failure just
    restarts the cooldown. Cooldown is measured with a monotonic
    clock so it can't be perturbed by a system clock adjustment.
    """

    def __init__(
        self,
        redis_limiter: _RedisLimiter,
        local_limiter: _InMemoryLimiter,
        cooldown_seconds: float = _REDIS_FAILURE_COOLDOWN_SECONDS,
    ) -> None:
        self._redis_limiter = redis_limiter
        self._local_limiter = local_limiter
        self._cooldown_seconds = cooldown_seconds
        self._redis_retry_at = 0.0

    def allow(
        self, key: str, *, max_attempts: int, window_seconds: float
    ) -> bool:
        if time.monotonic() < self._redis_retry_at:
            return self._local_limiter.allow(
                key, max_attempts=max_attempts, window_seconds=window_seconds
            )

        try:
            return self._redis_limiter.allow(
                key, max_attempts=max_attempts, window_seconds=window_seconds
            )
        except Exception:
            logger.warning(
                "rate_limit_redis_unavailable, falling back to local "
                "limiter for %.0fs",
                self._cooldown_seconds,
                exc_info=True,
            )
            self._redis_retry_at = time.monotonic() + self._cooldown_seconds
            return self._local_limiter.allow(
                key, max_attempts=max_attempts, window_seconds=window_seconds
            )


_in_memory_limiter = _InMemoryLimiter()
_resilient_limiter: _ResilientLimiter | None = None
_redis_init_lock = Lock()


def _get_limiter():
    if not settings.redis_url:
        return _in_memory_limiter

    global _resilient_limiter

    if _resilient_limiter is None:
        with _redis_init_lock:
            if _resilient_limiter is None:
                import redis

                client = redis.Redis.from_url(
                    settings.redis_url,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                )
                _resilient_limiter = _ResilientLimiter(
                    _RedisLimiter(client), _in_memory_limiter
                )

    return _resilient_limiter


def reset_rate_limits() -> None:
    """Test-only hook: clears in-memory rate-limit state.

    Only affects the in-memory backend. Tests always run with
    REDIS_URL unset, so the in-memory backend is the only one ever
    exercised by the test suite -- this milestone adds no Redis
    service dependency to CI.
    """
    _in_memory_limiter.reset()


def _client_ip(request: Request) -> str:
    # `request.client.host` already reflects the real client IP, not a
    # proxy's, in the deployed topology: Render's Web Services are only
    # reachable through Render's own edge, and start.sh runs uvicorn
    # with --proxy-headers so that edge's X-Forwarded-For is what sets
    # `request.client`. No header is read directly here, so there is
    # nothing for an end user to spoof by sending their own
    # X-Forwarded-For -- see start.sh for the full reasoning. This
    # trust assumption depends on Render being the only public ingress
    # (see SECURITY.md); it would need revisiting behind any other
    # proxy topology.
    return request.client.host if request.client else "unknown"


def _route_key(request: Request) -> str:
    # The matched route's path template (e.g. "/users/{user_id}/plaid/
    # sync"), set by Starlette's router before the endpoint/its
    # dependencies run -- never something a client can influence.
    # Using it instead of the literal request path means
    # /users/1/plaid/sync and /users/2/plaid/sync share one logical
    # bucket instead of silently forking a separate bucket per id.
    # Falls back to the literal path in the (normally unreachable)
    # case no route was matched.
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path or request.url.path


def rate_limiter(*, max_attempts: int, window_seconds: float = 60.0):
    """FastAPI dependency factory: limits attempts per client IP."""

    def dependency(request: Request) -> None:
        key = f"{_route_key(request)}:{_client_ip(request)}"
        limiter = _get_limiter()

        if not limiter.allow(
            key,
            max_attempts=max_attempts,
            window_seconds=window_seconds,
        ):
            raise HTTPException(
                status_code=429,
                detail=_TOO_MANY_ATTEMPTS,
            )

    return dependency


def authenticated_rate_limiter(
    *,
    max_attempts: int,
    window_seconds: float = 60.0,
    user_max_attempts: int | None = None,
    user_window_seconds: float | None = None,
):
    """FastAPI dependency factory for authenticated, expensive
    endpoints (Copilot, CSV upload, Plaid link/exchange/sync): limits
    by client IP AND by the authenticated user, independently --
    either bucket being exceeded rejects the request.

    An IP-only limit is bypassable by rotating IPs; a single shared
    user-level quota would let many legitimate users behind one NAT
    exhaust each other's allowance. Enforcing both closes each gap
    without the other reintroducing it.

    The user identity is always the server-authenticated `User.id`
    from `get_current_user` (FastAPI caches that dependency per
    request, so this doesn't cost a second token decode when the
    endpoint also declares its own `Depends(get_current_user)`) --
    never a client-supplied `user_id` path/body value or anything a
    model could choose.

    `user_max_attempts`/`user_window_seconds` default to the IP
    values; pass them explicitly only when the two limits genuinely
    need to differ (e.g. a looser IP ceiling that still exists purely
    to catch many distinct accounts abusing one IP).
    """

    def dependency(
        request: Request,
        current_user: User = Depends(get_current_user),
    ) -> None:
        limiter = _get_limiter()
        route = _route_key(request)

        ip_key = f"{route}:{_client_ip(request)}"
        if not limiter.allow(
            ip_key,
            max_attempts=max_attempts,
            window_seconds=window_seconds,
        ):
            raise HTTPException(
                status_code=429,
                detail=_TOO_MANY_ATTEMPTS,
            )

        user_key = f"{route}:user:{current_user.id}"
        if not limiter.allow(
            user_key,
            max_attempts=user_max_attempts or max_attempts,
            window_seconds=user_window_seconds or window_seconds,
        ):
            raise HTTPException(
                status_code=429,
                detail=_TOO_MANY_ATTEMPTS,
            )

    return dependency
