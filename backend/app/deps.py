"""Shared FastAPI dependencies."""

from functools import lru_cache

from app.config import Settings, settings
from app.llm_categorization import LLMCategorizer
from app.services.copilot_groq_client import GroqCopilotClient
from app.services.copilot_service import CopilotClient, CopilotModelProvider


@lru_cache
def get_categorizer() -> LLMCategorizer:
    """One shared categorizer (its cache persists across requests)."""
    return LLMCategorizer(api_key=settings.anthropic_api_key, model=settings.llm_model)


def build_copilot_client(config: Settings) -> CopilotModelProvider:
    """Builds the configured Copilot model provider client.

    COPILOT_PROVIDER=free always yields a disabled client regardless of
    any key present, so `run_copilot_turn` takes the deterministic
    free-mode path unconditionally. COPILOT_PROVIDER=groq/anthropic
    with a missing/empty key also yields a disabled client -- same
    free-mode fallback, just via the existing `client.enabled` check
    rather than a special case here. Kept as a plain function (rather
    than inlined in `get_copilot_client`) so provider selection is
    testable without touching the process-wide `lru_cache`.
    """
    if config.copilot_provider == "groq":
        return GroqCopilotClient(
            api_key=config.groq_api_key,
            model=config.copilot_groq_model,
            timeout=config.copilot_model_timeout_seconds,
        )

    if config.copilot_provider == "free":
        return CopilotClient(api_key=None)

    return CopilotClient(
        api_key=config.anthropic_api_key,
        model=config.llm_model,
        timeout=config.copilot_model_timeout_seconds,
    )


@lru_cache
def get_copilot_client() -> CopilotModelProvider:
    return build_copilot_client(settings)
