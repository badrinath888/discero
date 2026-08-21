"""AI Evals + Observability 1.0 -- execution-trace primitives for one
Discero Copilot turn.

Deliberately separate from copilot_audit.py (which persists a bounded
row per turn to the DB): this module has no DB/session dependency at
all. It only ever reads provider response metadata that's already on
the object copilot_service.py has in hand (never a second network call)
and does arithmetic on numbers the provider actually returned -- it
never estimates a token count or invents a cost figure. Both stay
`None` whenever the provider or operator hasn't supplied the inputs
needed to compute them, per the same "never fabricate a number" rule
that governs financial results.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None


def extract_token_usage(response) -> TokenUsage | None:
    """Reads provider-reported token usage off a DECIDE/NARRATE response.

    Understands both shapes CopilotModelProvider implementations can
    return: Anthropic's native `usage.input_tokens`/`usage.output_tokens`
    (CopilotClient passes the SDK response through untouched) and the
    OpenAI-compatible `usage.prompt_tokens`/`usage.completion_tokens`
    GroqCopilotClient forwards from Groq. Returns None whenever the
    response has no usage object at all -- never a guessed count.
    """
    usage = getattr(response, "usage", None)
    if usage is None:
        return None

    input_tokens = getattr(usage, "input_tokens", None)
    output_tokens = getattr(usage, "output_tokens", None)

    if input_tokens is None and output_tokens is None:
        input_tokens = getattr(usage, "prompt_tokens", None)
        output_tokens = getattr(usage, "completion_tokens", None)

    if input_tokens is None and output_tokens is None:
        return None

    total_tokens = getattr(usage, "total_tokens", None)
    if (
        total_tokens is None
        and input_tokens is not None
        and output_tokens is not None
    ):
        total_tokens = input_tokens + output_tokens

    return TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )


def estimate_cost(
    usage: TokenUsage | None,
    input_rate_per_million: float | None,
    output_rate_per_million: float | None,
) -> float | None:
    """Cost in dollars from real usage x configured per-million rates.

    Returns None -- never a fabricated figure -- whenever usage is
    unavailable or either rate is unconfigured. This is the only place
    in the codebase that turns token counts into a dollar figure; it is
    intentionally independent of any financial calculation service.
    """
    if usage is None:
        return None
    if input_rate_per_million is None or output_rate_per_million is None:
        return None
    if usage.input_tokens is None or usage.output_tokens is None:
        return None

    return (
        usage.input_tokens * input_rate_per_million
        + usage.output_tokens * output_rate_per_million
    ) / 1_000_000


@dataclass(frozen=True)
class CopilotTrace:
    """One Copilot turn's operational trace -- bounded, testable, and
    never a substitute for copilot_audit's persisted row. Built only
    for the terminal outcome of a turn (never per intermediate step),
    so a single instance always describes the whole request.
    """

    request_id: str
    tool: str | None
    tool_calls: int
    tool_duration_ms: int | None
    provider_duration_ms: int | None
    total_duration_ms: int
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    estimated_cost: float | None
    success: bool
    failure_stage: str | None = None


def log_turn_completed(trace: CopilotTrace) -> None:
    """Bounded structured log line -- IDs, names, counts, and timings
    only. Never the user's prompt, the model's prose answer, or a
    financial payload; see copilot_audit.py for the same privacy rule
    applied to the persisted audit row.
    """
    if trace.success:
        logger.info(
            "copilot_turn_completed request_id=%s tool=%s tool_calls=%d "
            "tool_ms=%s provider_ms=%s total_ms=%d input_tokens=%s "
            "output_tokens=%s total_tokens=%s estimated_cost=%s",
            trace.request_id,
            trace.tool or "-",
            trace.tool_calls,
            trace.tool_duration_ms,
            trace.provider_duration_ms,
            trace.total_duration_ms,
            trace.input_tokens,
            trace.output_tokens,
            trace.total_tokens,
            trace.estimated_cost,
        )
        return

    logger.warning(
        "copilot_turn_failed request_id=%s failure_stage=%s total_ms=%d",
        trace.request_id,
        trace.failure_stage or "-",
        trace.total_duration_ms,
    )
