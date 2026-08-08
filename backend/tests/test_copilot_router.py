from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.deps import get_copilot_client
from app.main import app
from app.services.copilot_service import CopilotClient


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
        if calls["n"] == 1:
            return _tool_use_response("get_safe_to_spend", {})
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
