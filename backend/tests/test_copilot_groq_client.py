"""GroqCopilotClient: the narrow translation layer to/from Groq's
OpenAI-compatible wire format. Groq is never called for real here --
`groq.Groq` itself is monkeypatched.
"""

import json
from types import SimpleNamespace

from app.services.copilot_groq_client import GroqCopilotClient


def _groq_message(
    *, content: str | None = None, tool_calls: list[SimpleNamespace] | None = None
) -> SimpleNamespace:
    return SimpleNamespace(content=content, tool_calls=tool_calls)


def _groq_tool_call(call_id: str, name: str, arguments: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _groq_response(message: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class _FakeGroqClient:
    """Stands in for groq.Groq -- records the outbound request and
    returns a scripted response, so the real SDK is never invoked.
    """

    last_kwargs: dict | None = None
    response: SimpleNamespace | None = None

    def __init__(self, **kwargs):
        pass

    @property
    def chat(self):
        return self

    @property
    def completions(self):
        return self

    def create(self, **kwargs):
        _FakeGroqClient.last_kwargs = kwargs
        return _FakeGroqClient.response


def _patch_groq(monkeypatch, response: SimpleNamespace) -> _FakeGroqClient:
    _FakeGroqClient.response = response
    _FakeGroqClient.last_kwargs = None
    monkeypatch.setattr("groq.Groq", _FakeGroqClient)
    return _FakeGroqClient


def test_enabled_reflects_api_key_presence() -> None:
    assert GroqCopilotClient(api_key=None).enabled is False
    assert GroqCopilotClient(api_key="fake-groq-key").enabled is True


def test_tool_schema_translated_to_openai_function_format(monkeypatch) -> None:
    _patch_groq(monkeypatch, _groq_response(_groq_message(content="hi")))
    client = GroqCopilotClient(api_key="fake-key")

    client.call(
        system="sys",
        messages=[{"role": "user", "content": "hello"}],
        tools=[
            {
                "name": "get_safe_to_spend",
                "description": "desc",
                "input_schema": {"type": "object", "properties": {}},
            }
        ],
    )

    sent_tools = _FakeGroqClient.last_kwargs["tools"]
    assert sent_tools == [
        {
            "type": "function",
            "function": {
                "name": "get_safe_to_spend",
                "description": "desc",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    # Never an autonomous multi-tool loop -- one tool per turn.
    assert _FakeGroqClient.last_kwargs["parallel_tool_calls"] is False


def test_forced_tool_choice_translated_to_openai_format(monkeypatch) -> None:
    _patch_groq(monkeypatch, _groq_response(_groq_message(content="hi")))
    client = GroqCopilotClient(api_key="fake-key")

    client.call(
        system="sys",
        messages=[{"role": "user", "content": "hello"}],
        tools=[],
        tool_choice={"type": "tool", "name": "present_financial_answer"},
    )

    assert _FakeGroqClient.last_kwargs["tool_choice"] == {
        "type": "function",
        "function": {"name": "present_financial_answer"},
    }


def test_text_response_parses_to_text_block(monkeypatch) -> None:
    _patch_groq(
        monkeypatch, _groq_response(_groq_message(content="plain answer"))
    )
    client = GroqCopilotClient(api_key="fake-key")

    response = client.call(
        system="sys", messages=[{"role": "user", "content": "hi"}], tools=[]
    )

    assert len(response.content) == 1
    assert response.content[0].type == "text"
    assert response.content[0].text == "plain answer"


def test_tool_call_response_parses_arguments_as_json(monkeypatch) -> None:
    _patch_groq(
        monkeypatch,
        _groq_response(
            _groq_message(
                tool_calls=[
                    _groq_tool_call(
                        "call_1",
                        "get_safe_to_spend",
                        json.dumps({"as_of": "2026-08-08"}),
                    )
                ]
            )
        ),
    )
    client = GroqCopilotClient(api_key="fake-key")

    response = client.call(
        system="sys", messages=[{"role": "user", "content": "hi"}], tools=[]
    )

    block = response.content[0]
    assert block.type == "tool_use"
    assert block.id == "call_1"
    assert block.name == "get_safe_to_spend"
    assert block.input == {"as_of": "2026-08-08"}


def test_malformed_tool_arguments_never_crash_and_never_guess(
    monkeypatch,
) -> None:
    _patch_groq(
        monkeypatch,
        _groq_response(
            _groq_message(
                tool_calls=[
                    _groq_tool_call(
                        "call_1", "simulate_major_purchase", "{not valid json"
                    )
                ]
            )
        ),
    )
    client = GroqCopilotClient(api_key="fake-key")

    response = client.call(
        system="sys", messages=[{"role": "user", "content": "hi"}], tools=[]
    )

    block = response.content[0]
    assert block.type == "tool_use"
    # Empty dict, never a guessed/fabricated argument -- downstream
    # Pydantic validation turns this into a clarification response.
    assert block.input == {}


def test_followup_history_with_tool_result_round_trips_to_groq_format(
    monkeypatch,
) -> None:
    # Mirrors exactly what copilot_service._narrate builds: the tool
    # already picked by the deterministic router, synthesized as a
    # plain Anthropic-shaped dict (never a live SDK response object,
    # since no DECIDE call happened this turn), followed by a
    # user-role tool_result block carrying the normalized deterministic
    # result JSON.
    _patch_groq(monkeypatch, _groq_response(_groq_message(content="done")))
    client = GroqCopilotClient(api_key="fake-key")

    prior_tool_use = {
        "type": "tool_use",
        "id": "call_1",
        "name": "get_safe_to_spend",
        "input": {},
    }

    client.call(
        system="sys",
        messages=[
            {"role": "user", "content": "What's my safe to spend?"},
            {"role": "assistant", "content": [prior_tool_use]},
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "call_1",
                        "content": '{"safe_to_spend_cents": 5000}',
                    }
                ],
            },
        ],
        tools=[],
    )

    sent_messages = _FakeGroqClient.last_kwargs["messages"]
    assert sent_messages[0] == {"role": "system", "content": "sys"}
    assert sent_messages[1] == {
        "role": "user",
        "content": "What's my safe to spend?",
    }
    assistant_message = sent_messages[2]
    assert assistant_message["role"] == "assistant"
    assert assistant_message["tool_calls"] == [
        {
            "id": "call_1",
            "type": "function",
            "function": {
                "name": "get_safe_to_spend",
                "arguments": "{}",
            },
        }
    ]
    tool_result_message = sent_messages[3]
    assert tool_result_message == {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": '{"safe_to_spend_cents": 5000}',
    }
