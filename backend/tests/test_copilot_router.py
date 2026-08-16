from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.routers.copilot as copilot_router
from app.deps import get_copilot_client
from app.main import app
from app.models import CopilotAuditEvent
from app.services.copilot_service import CopilotClient
from tests.conftest import TestingSessionLocal


def _tool_use_response(name: str, tool_input: dict) -> SimpleNamespace:
    return SimpleNamespace(
        content=[
            SimpleNamespace(
                type="tool_use",
                id="tool_1",
                name=name,
                input=tool_input,
            )
        ]
    )


def test_chat_requires_authentication(client: TestClient) -> None:
    response = client.post(
        "/users/9999/copilot/chat",
        json={"messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 401


def test_chat_blocks_other_user(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    response = client.post(
        f"/users/{user_id + 1}/copilot/chat",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers=auth_headers,
    )

    assert response.status_code == 403


def test_chat_uses_free_mode_without_api_key(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    # The test environment has no ANTHROPIC_API_KEY configured, so the
    # real DI-provided client is disabled -- this exercises the actual
    # default wiring, not a mock. A supported question must still get a
    # real deterministic answer, never "unavailable".
    response = client.post(
        f"/users/{user_id}/copilot/chat",
        json={
            "messages": [
                {"role": "user", "content": "What's my safe to spend?"}
            ]
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "answer"
    assert body["provenance"] == "deterministic"


def test_chat_free_mode_unsupported_question_explains_capabilities(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    response = client.post(
        f"/users/{user_id}/copilot/chat",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers=auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "out_of_scope"
    assert "AI provider key" not in (body["answer"] or "")


def test_chat_happy_path_with_injected_client(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    calls = {"n": 0}

    def fake_call(**kwargs):
        calls["n"] += 1
        # The deterministic router already resolves get_safe_to_spend
        # before any provider call -- this turn's one provider call is
        # NARRATE only.
        return _tool_use_response(
            "present_financial_answer",
            {"answer": "You have room to spend."},
        )

    fake_client = CopilotClient(api_key="fake-key")
    fake_client.call = fake_call  # type: ignore[method-assign]

    app.dependency_overrides[get_copilot_client] = lambda: fake_client

    response = client.post(
        f"/users/{user_id}/copilot/chat",
        json={
            "messages": [
                {"role": "user", "content": "What's my safe to spend?"}
            ]
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "answer"
    assert body["answer"] == "You have room to spend."
    assert body["tool_used"] == "Safe-to-Spend"
    assert body["provenance"] == "ai_enhanced"
    assert any(m["label"] == "Safe to spend" for m in body["key_numbers"])


def test_chat_rejects_empty_message_list(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    response = client.post(
        f"/users/{user_id}/copilot/chat",
        json={"messages": []},
        headers=auth_headers,
    )

    assert response.status_code == 422


def test_chat_returns_correlation_id_header(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    response = client.post(
        f"/users/{user_id}/copilot/chat",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.headers.get("x-request-id")


def test_chat_is_rate_limited(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    for _ in range(20):
        response = client.post(
            f"/users/{user_id}/copilot/chat",
            json={"messages": [{"role": "user", "content": "hi"}]},
            headers=auth_headers,
        )
        assert response.status_code == 200

    blocked = client.post(
        f"/users/{user_id}/copilot/chat",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers=auth_headers,
    )

    assert blocked.status_code == 429


def test_chat_unexpected_exception_returns_safe_response(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    # Simulates a genuinely unexpected bug (not a classified provider/
    # validation/tool failure) escaping run_copilot_turn entirely --
    # e.g. a bug in the deterministic router before any tool result
    # exists. The router's request-boundary safety net must turn this
    # into the stable Copilot envelope, never a raw 500.
    def boom(*args, **kwargs):
        raise RuntimeError("unexpected programming error")

    monkeypatch.setattr(copilot_router, "run_copilot_turn", boom)

    response = client.post(
        f"/users/{user_id}/copilot/chat",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers=auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "answer"
    assert "couldn't complete that" in (body["answer"] or "")
    assert body["provenance"] == "deterministic"
    # Correlation id must still be available even on the failure path.
    assert response.headers.get("x-request-id")


def test_chat_unexpected_exception_does_not_leak_sensitive_text(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    sensitive = "balance $58,234.12 for account 4111111111111111"

    def boom(*args, **kwargs):
        raise RuntimeError(f"tool crashed while holding {sensitive}")

    monkeypatch.setattr(copilot_router, "run_copilot_turn", boom)

    response = client.post(
        f"/users/{user_id}/copilot/chat",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert sensitive not in response.text

    request_id = response.headers["x-request-id"]
    with TestingSessionLocal() as db:
        event = (
            db.query(CopilotAuditEvent)
            .filter(CopilotAuditEvent.request_id == request_id)
            .one()
        )
        assert event.event_type == "unexpected_failure"
        assert sensitive not in str(event.event_metadata)


def test_chat_narration_exception_still_returns_tool_result(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    # The deterministic router resolves the tool first (Path A); the
    # provider is only consulted afterward, for NARRATE. If that call
    # blows up with a raw exception (not just a bad response shape),
    # the already-successful tool result must still win -- the generic
    # last-resort fallback must never replace it.
    def fake_call(**kwargs):
        raise RuntimeError("provider exploded during narration")

    fake_client = CopilotClient(api_key="fake-key")
    fake_client.call = fake_call  # type: ignore[method-assign]

    app.dependency_overrides[get_copilot_client] = lambda: fake_client

    response = client.post(
        f"/users/{user_id}/copilot/chat",
        json={
            "messages": [
                {"role": "user", "content": "What's my safe to spend?"}
            ]
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "answer"
    assert "couldn't complete that" not in (body["answer"] or "")
    assert body["provenance"] == "deterministic"
    assert any(m["label"] == "Safe to spend" for m in body["key_numbers"])
