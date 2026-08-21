"""Rate-limit abuse-prevention: in-memory backend behavior, Redis-backend
selection/atomicity behavior and outage fallback/recovery (mocked -- no
live Redis needed in CI), canonical route-template keys, per-user +
per-IP limiting on authenticated expensive endpoints, and coverage that
every sensitive flow is actually limited.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

import app.rate_limit as rate_limit_module
from app.auth import get_current_user
from app.config import settings
from app.main import app
from app.rate_limit import (
    _get_limiter,
    _InMemoryLimiter,
    _RedisLimiter,
    _ResilientLimiter,
    authenticated_rate_limiter,
    reset_rate_limits,
)


PASSWORD = "TestPassword123!"


# --- In-memory backend (the default, exercised by the whole suite) ------


def test_in_memory_limiter_blocks_after_max_attempts() -> None:
    limiter = _InMemoryLimiter()

    allowed = [
        limiter.allow("k", max_attempts=3, window_seconds=60)
        for _ in range(5)
    ]

    assert allowed == [True, True, True, False, False]


def test_in_memory_limiter_keys_are_independent() -> None:
    limiter = _InMemoryLimiter()

    for _ in range(3):
        limiter.allow("a", max_attempts=3, window_seconds=60)

    assert limiter.allow("a", max_attempts=3, window_seconds=60) is False
    assert limiter.allow("b", max_attempts=3, window_seconds=60) is True


def test_reset_rate_limits_clears_in_memory_state() -> None:
    limiter = _InMemoryLimiter()
    limiter.allow("k", max_attempts=1, window_seconds=60)
    assert limiter.allow("k", max_attempts=1, window_seconds=60) is False

    reset_rate_limits()

    # reset_rate_limits() clears the module-level limiter, not this
    # local instance -- confirm the module-level one is what backs
    # rate_limiter() by exercising it through an actual endpoint below
    # instead. This test only documents that reset() on an instance
    # works as the primitive reset_rate_limits() relies on.
    limiter.reset()
    assert limiter.allow("k", max_attempts=1, window_seconds=60) is True


def test_login_endpoint_is_rate_limited(client: TestClient) -> None:
    client.post(
        "/users",
        json={"email": "ratelimit-login@example.com", "password": PASSWORD},
    )

    responses = [
        client.post(
            "/users/login",
            json={
                "email": "ratelimit-login@example.com",
                "password": "wrong-password",
            },
        )
        for _ in range(15)
    ]

    statuses = [r.status_code for r in responses]
    assert 429 in statuses
    # Every attempt before the block is a normal 401 (wrong password),
    # never something that would leak account existence differently.
    assert all(s in (401, 429) for s in statuses)


@pytest.mark.parametrize(
    "path,body",
    [
        ("/users", {"email": "x@example.com", "password": PASSWORD}),
        ("/users/forgot-password", {"email": "x@example.com"}),
        ("/users/resend-verification", {"email": "x@example.com"}),
        ("/users/reset-password", {"token": "x" * 32, "new_password": PASSWORD}),
        ("/users/verify-email", {"token": "x" * 32}),
    ],
)
def test_sensitive_auth_flows_are_rate_limited(
    client: TestClient, path: str, body: dict
) -> None:
    responses = [client.post(path, json=body) for _ in range(15)]
    assert 429 in [r.status_code for r in responses]


def test_copilot_chat_is_rate_limited(
    client: TestClient, user_id: int, auth_headers: dict[str, str]
) -> None:
    responses = [
        client.post(
            f"/users/{user_id}/copilot/chat",
            headers=auth_headers,
            json={"messages": [{"role": "user", "content": "hi"}]},
        )
        for _ in range(25)
    ]
    assert 429 in [r.status_code for r in responses]


def test_plaid_link_token_creation_is_rate_limited(
    client: TestClient, user_id: int, auth_headers: dict[str, str]
) -> None:
    responses = [
        client.post(
            f"/users/{user_id}/plaid/link-token",
            headers=auth_headers,
        )
        for _ in range(25)
    ]
    assert 429 in [r.status_code for r in responses]


def test_plaid_exchange_token_is_rate_limited(
    client: TestClient, user_id: int, auth_headers: dict[str, str]
) -> None:
    responses = [
        client.post(
            f"/users/{user_id}/plaid/exchange-token",
            headers=auth_headers,
            json={"public_token": "public-sandbox-token"},
        )
        for _ in range(15)
    ]
    assert 429 in [r.status_code for r in responses]


def test_plaid_sync_is_rate_limited(
    client: TestClient, user_id: int, auth_headers: dict[str, str]
) -> None:
    responses = [
        client.post(
            f"/users/{user_id}/plaid/sync",
            headers=auth_headers,
        )
        for _ in range(25)
    ]
    assert 429 in [r.status_code for r in responses]


# --- Redis backend selection/atomicity (mocked) --------------------------


def test_get_limiter_uses_in_memory_when_redis_url_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "redis_url", None)

    assert isinstance(_get_limiter(), _InMemoryLimiter)


def test_get_limiter_uses_redis_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "redis_url", "redis://localhost:6379/0")
    monkeypatch.setattr(rate_limit_module, "_resilient_limiter", None)

    fake_redis_module = MagicMock()
    fake_client = MagicMock()
    fake_redis_module.Redis.from_url.return_value = fake_client
    monkeypatch.setitem(
        __import__("sys").modules, "redis", fake_redis_module
    )

    limiter = _get_limiter()

    assert isinstance(limiter, _ResilientLimiter)
    assert isinstance(limiter._redis_limiter, _RedisLimiter)
    fake_redis_module.Redis.from_url.assert_called_once()

    # Reused, not reconnected, on a second call.
    limiter_again = _get_limiter()
    assert limiter_again is limiter
    fake_redis_module.Redis.from_url.assert_called_once()

    monkeypatch.setattr(rate_limit_module, "_resilient_limiter", None)


def test_redis_limiter_admits_when_script_returns_truthy() -> None:
    fake_client = MagicMock()
    fake_script = MagicMock(return_value=1)
    fake_client.register_script.return_value = fake_script

    limiter = _RedisLimiter(fake_client)

    assert limiter.allow("k", max_attempts=5, window_seconds=60) is True
    fake_script.assert_called_once()


def test_redis_limiter_blocks_when_script_returns_falsy() -> None:
    fake_client = MagicMock()
    fake_script = MagicMock(return_value=0)
    fake_client.register_script.return_value = fake_script

    limiter = _RedisLimiter(fake_client)

    assert limiter.allow("k", max_attempts=5, window_seconds=60) is False


def test_redis_limiter_raises_on_backend_error() -> None:
    """_RedisLimiter itself no longer swallows a backend error -- degrading
    on failure is _ResilientLimiter's job (see the tests below), not this
    class's.
    """
    fake_client = MagicMock()
    fake_script = MagicMock(side_effect=ConnectionError("redis down"))
    fake_client.register_script.return_value = fake_script

    limiter = _RedisLimiter(fake_client)

    with pytest.raises(ConnectionError):
        limiter.allow("k", max_attempts=5, window_seconds=60)


def test_redis_limiter_uses_unique_member_per_call() -> None:
    """Two calls in the same millisecond must not collide as the same
    sorted-set member and get silently deduplicated into one attempt.
    """
    fake_client = MagicMock()
    fake_script = MagicMock(return_value=1)
    fake_client.register_script.return_value = fake_script

    limiter = _RedisLimiter(fake_client)
    limiter.allow("k", max_attempts=5, window_seconds=60)
    limiter.allow("k", max_attempts=5, window_seconds=60)

    first_member = fake_script.call_args_list[0].kwargs["args"][3]
    second_member = fake_script.call_args_list[1].kwargs["args"][3]
    assert first_member != second_member


# --- Redis outage: local fallback + cooldown/recovery (mocked) -----------


def test_resilient_limiter_uses_redis_when_healthy() -> None:
    fake_redis_limiter = MagicMock()
    fake_redis_limiter.allow.return_value = True
    fake_local_limiter = MagicMock()

    limiter = _ResilientLimiter(fake_redis_limiter, fake_local_limiter)

    assert limiter.allow("k", max_attempts=5, window_seconds=60) is True
    fake_redis_limiter.allow.assert_called_once()
    fake_local_limiter.allow.assert_not_called()


def test_resilient_limiter_falls_back_to_local_on_redis_error() -> None:
    fake_redis_limiter = MagicMock()
    fake_redis_limiter.allow.side_effect = ConnectionError("redis down")
    fake_local_limiter = MagicMock()
    fake_local_limiter.allow.return_value = True

    limiter = _ResilientLimiter(fake_redis_limiter, fake_local_limiter)

    assert limiter.allow("k", max_attempts=5, window_seconds=60) is True
    fake_local_limiter.allow.assert_called_once_with(
        "k", max_attempts=5, window_seconds=60
    )


def test_resilient_limiter_local_fallback_enforces_its_own_limit() -> None:
    """A Redis outage must never become unconditional-allow traffic --
    the local limiter behind it still blocks after its own limit.
    """
    fake_redis_limiter = MagicMock()
    fake_redis_limiter.allow.side_effect = ConnectionError("redis down")
    real_local_limiter = _InMemoryLimiter()

    limiter = _ResilientLimiter(fake_redis_limiter, real_local_limiter)

    allowed = [
        limiter.allow("k", max_attempts=3, window_seconds=60)
        for _ in range(5)
    ]

    assert allowed == [True, True, True, False, False]


def test_resilient_limiter_skips_redis_during_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_redis_limiter = MagicMock()
    fake_redis_limiter.allow.side_effect = ConnectionError("redis down")
    fake_local_limiter = MagicMock()
    fake_local_limiter.allow.return_value = True

    fake_now = [1_000.0]
    monkeypatch.setattr(
        rate_limit_module.time, "monotonic", lambda: fake_now[0]
    )

    limiter = _ResilientLimiter(
        fake_redis_limiter, fake_local_limiter, cooldown_seconds=5.0
    )

    limiter.allow("k", max_attempts=5, window_seconds=60)
    assert fake_redis_limiter.allow.call_count == 1

    fake_now[0] += 1.0  # still inside the cooldown
    limiter.allow("k", max_attempts=5, window_seconds=60)
    assert fake_redis_limiter.allow.call_count == 1  # not retried
    assert fake_local_limiter.allow.call_count == 2


def test_resilient_limiter_retries_redis_after_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_redis_limiter = MagicMock()
    fake_redis_limiter.allow.side_effect = ConnectionError("redis down")
    fake_local_limiter = MagicMock()
    fake_local_limiter.allow.return_value = True

    fake_now = [1_000.0]
    monkeypatch.setattr(
        rate_limit_module.time, "monotonic", lambda: fake_now[0]
    )

    limiter = _ResilientLimiter(
        fake_redis_limiter, fake_local_limiter, cooldown_seconds=5.0
    )

    limiter.allow("k", max_attempts=5, window_seconds=60)
    assert fake_redis_limiter.allow.call_count == 1

    fake_now[0] += 10.0  # past the cooldown
    limiter.allow("k", max_attempts=5, window_seconds=60)
    assert fake_redis_limiter.allow.call_count == 2


def test_resilient_limiter_resumes_redis_after_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_redis_limiter = MagicMock()
    fake_local_limiter = MagicMock()
    fake_local_limiter.allow.return_value = True

    fake_now = [1_000.0]
    monkeypatch.setattr(
        rate_limit_module.time, "monotonic", lambda: fake_now[0]
    )

    limiter = _ResilientLimiter(
        fake_redis_limiter, fake_local_limiter, cooldown_seconds=5.0
    )

    fake_redis_limiter.allow.side_effect = ConnectionError("redis down")
    limiter.allow("k", max_attempts=5, window_seconds=60)
    assert fake_local_limiter.allow.call_count == 1

    fake_now[0] += 10.0  # past the cooldown, and Redis has recovered
    fake_redis_limiter.allow.side_effect = None
    fake_redis_limiter.allow.return_value = True

    result = limiter.allow("k", max_attempts=5, window_seconds=60)

    assert result is True
    # The distributed limiter is used again -- local isn't consulted a
    # second time now that Redis is healthy.
    assert fake_local_limiter.allow.call_count == 1


# --- Canonical route keys -------------------------------------------------


def test_canonical_route_key_shares_ip_bucket_across_object_ids(
    client: TestClient, user_id: int, auth_headers: dict[str, str]
) -> None:
    """/users/{user_id}/plaid/link-token has a per-IP limit of 20. Two
    different literal user_id values on that same route template must
    still consume ONE shared ip-scoped bucket, not two.
    """
    for _ in range(20):
        client.post(f"/users/{user_id}/plaid/link-token", headers=auth_headers)

    response = client.post(
        f"/users/{user_id + 1}/plaid/link-token", headers=auth_headers
    )
    assert response.status_code == 429


def test_canonical_route_key_keeps_different_routes_separate(
    client: TestClient, user_id: int, auth_headers: dict[str, str]
) -> None:
    for _ in range(20):
        client.post(f"/users/{user_id}/plaid/link-token", headers=auth_headers)

    # A different logical route, same IP, must not already be blocked.
    response = client.post(
        f"/users/{user_id}/plaid/sync", headers=auth_headers
    )
    assert response.status_code != 429


# --- Authenticated (user + IP) limiting -----------------------------------


def test_authenticated_user_quota_persists_across_ip_changes(
    user_id: int, auth_headers: dict[str, str]
) -> None:
    """/plaid/link-token allows 20 attempts/IP/user. Issuing each request
    from a fresh, never-before-seen IP keeps the IP bucket unsaturated,
    so a 429 here can only come from the user-scoped bucket following the
    same authenticated user across IPs.
    """
    statuses = []
    for i in range(21):
        ip_client = TestClient(app, client=(f"203.0.113.{i}", 1))
        statuses.append(
            ip_client.post(
                f"/users/{user_id}/plaid/link-token", headers=auth_headers
            ).status_code
        )

    assert 429 in statuses


def test_authenticated_limiter_uses_server_side_user_identity_not_path_param(
    client: TestClient, user_id: int, auth_headers: dict[str, str]
) -> None:
    """Client/path input must never choose the user-limiter identity.
    Every one of these requests targets a DIFFERENT (unauthorized)
    literal user_id in the path; if the limiter identity were taken from
    that path value, each would land in its own fresh bucket and never
    trip. It comes from the authenticated User instead, so they all
    still land in this user's one bucket.
    """
    for i in range(20):
        client.post(
            f"/users/{user_id + 1000 + i}/plaid/link-token",
            headers=auth_headers,
        )

    response = client.post(
        f"/users/{user_id}/plaid/link-token", headers=auth_headers
    )
    assert response.status_code == 429


def _probe_app(
    max_attempts: int = 10, user_max_attempts: int | None = None
) -> FastAPI:
    """A minimal standalone app for exercising `authenticated_rate_limiter`
    in isolation, with distinct IP vs. user thresholds -- real endpoints
    default both to the same (preserved) value, which makes it impossible
    to cleanly demonstrate per-user independence and shared-IP protection
    as separate properties in the same scenario.
    """
    probe_app = FastAPI()

    def _fake_current_user(request: Request) -> SimpleNamespace:
        return SimpleNamespace(id=int(request.headers["X-Test-User-Id"]))

    probe_app.dependency_overrides[get_current_user] = _fake_current_user

    @probe_app.post("/probe")
    def probe(
        _rate_limit: None = Depends(
            authenticated_rate_limiter(
                max_attempts=max_attempts,
                window_seconds=60,
                user_max_attempts=user_max_attempts,
            )
        ),
    ) -> dict:
        return {"ok": True}

    return probe_app


def test_authenticated_rate_limiter_user_quota_is_independent_per_user() -> None:
    probe_client = TestClient(
        _probe_app(max_attempts=10, user_max_attempts=3), client=("198.51.100.1", 1)
    )

    for _ in range(3):
        assert (
            probe_client.post(
                "/probe", headers={"X-Test-User-Id": "1"}
            ).status_code
            == 200
        )
    assert (
        probe_client.post("/probe", headers={"X-Test-User-Id": "1"}).status_code
        == 429
    )

    # Same IP, a different user: unaffected by user 1's exhausted quota.
    assert (
        probe_client.post("/probe", headers={"X-Test-User-Id": "2"}).status_code
        == 200
    )


def test_authenticated_rate_limiter_shared_ip_quota_protects_against_many_users() -> None:
    probe_client = TestClient(
        _probe_app(max_attempts=5, user_max_attempts=100),
        client=("198.51.100.2", 1),
    )

    responses = [
        probe_client.post("/probe", headers={"X-Test-User-Id": str(i)})
        for i in range(8)
    ]

    statuses = [r.status_code for r in responses]
    assert statuses == [200, 200, 200, 200, 200, 429, 429, 429]


# --- Auth dependency consolidation -----------------------------------------


def test_get_current_user_rejects_stale_token_version(
    client: TestClient, user_id: int, auth_headers: dict[str, str]
) -> None:
    """Regression for consolidating onto one canonical get_current_user:
    session revocation (token_version bump on logout) must still work.
    """
    logout = client.post("/users/logout", headers=auth_headers)
    assert logout.status_code == 204

    response = client.get("/users/me", headers=auth_headers)
    assert response.status_code == 401
