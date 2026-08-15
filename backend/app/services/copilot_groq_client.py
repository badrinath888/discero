"""Groq provider for Discero Copilot.

`CopilotClient` (see copilot_service.py) defines the shared call
contract that DECIDE/NARRATE orchestration is built around: a
`call(system=, messages=, tools=, tool_choice=)` method taking
Anthropic-shaped tool schemas and returning an object whose `.content`
is a list of blocks with `.type` ("text" | "tool_use") and, for
tool_use, `.id`/`.name`/`.input`.

`GroqCopilotClient` implements that same contract on top of Groq's
OpenAI-compatible chat-completions API, translating to/from Groq's
wire format only inside this module. Orchestration in
copilot_service.py never branches on provider -- it only ever sees the
shared shape. A single Copilot turn's DECIDE and NARRATE calls always
go through the same client instance, so this module only has to stay
self-consistent (its own output feeding back into its own input), not
compatible with Anthropic's wire format.
"""

from __future__ import annotations

import json
from types import SimpleNamespace


class GroqCopilotClient:
    """Same call() contract as CopilotClient, backed by Groq."""

    provider_name = "groq"

    def __init__(
        self,
        api_key: str | None,
        model: str = "llama-3.3-70b-versatile",
        timeout: float = 20.0,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def call(
        self,
        *,
        system: str,
        messages: list[dict],
        tools: list[dict],
        tool_choice: dict | None = None,
    ):
        from groq import Groq

        client = Groq(
            api_key=self.api_key,
            timeout=self.timeout,
            max_retries=1,
        )

        groq_messages = [{"role": "system", "content": system}]
        groq_messages.extend(_to_groq_messages(messages))

        response = client.chat.completions.create(
            model=self.model,
            max_tokens=1024,
            messages=groq_messages,
            tools=[_to_groq_tool(t) for t in tools],
            tool_choice=_to_groq_tool_choice(tool_choice),
            # One tool call per turn, matching the existing
            # Anthropic-path orchestration -- no autonomous loop.
            parallel_tool_calls=False,
        )

        return _from_groq_response(response)


def _to_groq_tool(tool: dict) -> dict:
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["input_schema"],
        },
    }


def _to_groq_tool_choice(tool_choice: dict | None):
    if not tool_choice or tool_choice.get("type") == "auto":
        return "auto"
    if tool_choice.get("type") == "tool":
        return {
            "type": "function",
            "function": {"name": tool_choice["name"]},
        }
    return "auto"


def _to_groq_messages(messages: list[dict]) -> list[dict]:
    converted: list[dict] = []

    for message in messages:
        role = message["role"]
        content = message["content"]

        if isinstance(content, str):
            converted.append({"role": role, "content": content})
            continue

        if role == "assistant":
            converted.append(_assistant_blocks_to_groq(content))
        elif role == "user":
            converted.extend(_user_blocks_to_groq(content))

    return converted


def _assistant_blocks_to_groq(blocks) -> dict:
    text_parts: list[str] = []
    tool_calls: list[dict] = []

    for block in blocks:
        block_type = getattr(block, "type", None)
        if block_type == "text" and getattr(block, "text", None):
            text_parts.append(block.text)
        elif block_type == "tool_use":
            tool_calls.append(
                {
                    "id": block.id,
                    "type": "function",
                    "function": {
                        "name": block.name,
                        "arguments": json.dumps(block.input or {}),
                    },
                }
            )

    message: dict = {
        "role": "assistant",
        "content": " ".join(text_parts) or None,
    }
    if tool_calls:
        message["tool_calls"] = tool_calls
    return message


def _user_blocks_to_groq(blocks: list[dict]) -> list[dict]:
    # The only structured user-content shape orchestration ever sends
    # is a tool_result block (built in copilot_service._narrate) --
    # Groq/OpenAI represents that as a dedicated "tool" role message,
    # not a user message.
    return [
        {
            "role": "tool",
            "tool_call_id": block["tool_use_id"],
            "content": block["content"],
        }
        for block in blocks
        if block.get("type") == "tool_result"
    ]


def _from_groq_response(response) -> SimpleNamespace:
    message = response.choices[0].message
    blocks: list[SimpleNamespace] = []

    if message.content:
        blocks.append(SimpleNamespace(type="text", text=message.content))

    for tool_call in message.tool_calls or []:
        try:
            arguments = json.loads(tool_call.function.arguments)
        except (json.JSONDecodeError, TypeError):
            # Malformed arguments never crash the turn or get guessed
            # at -- an empty input dict fails the existing Pydantic
            # validation path in copilot_service.py, which already
            # turns that into a clarification response.
            arguments = {}

        blocks.append(
            SimpleNamespace(
                type="tool_use",
                id=tool_call.id,
                name=tool_call.function.name,
                input=arguments,
            )
        )

    return SimpleNamespace(content=blocks)
