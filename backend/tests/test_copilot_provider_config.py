"""COPILOT_PROVIDER selection: which client class gets built, and the
deterministic-fallback behavior when a provider's key is missing.
"""

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.deps import build_copilot_client
from app.services.copilot_groq_client import GroqCopilotClient
from app.services.copilot_service import CopilotClient


def make_settings(**overrides: object) -> Settings:
    overrides.setdefault("database_url", "sqlite://")
    return Settings(
        _env_file=None,
        jwt_secret="test-secret",
        **overrides,
    )


def test_groq_provider_with_key_selects_groq_client() -> None:
    config = make_settings(
        copilot_provider="groq", groq_api_key="fake-groq-key"
    )
    client = build_copilot_client(config)

    assert isinstance(client, GroqCopilotClient)
    assert client.provider_name == "groq"
    assert client.enabled is True


def test_anthropic_provider_with_key_selects_anthropic_client() -> None:
    config = make_settings(
        copilot_provider="anthropic", anthropic_api_key="fake-anthropic-key"
    )
    client = build_copilot_client(config)

    assert isinstance(client, CopilotClient)
    assert client.provider_name == "anthropic"
    assert client.enabled is True


def test_free_provider_never_uses_external_client_even_with_keys_set() -> (
    None
):
    config = make_settings(
        copilot_provider="free",
        groq_api_key="fake-groq-key",
        anthropic_api_key="fake-anthropic-key",
    )
    client = build_copilot_client(config)

    assert client.enabled is False


def test_groq_provider_missing_key_falls_back_to_disabled_client() -> None:
    config = make_settings(copilot_provider="groq", groq_api_key=None)
    client = build_copilot_client(config)

    assert isinstance(client, GroqCopilotClient)
    assert client.enabled is False


def test_anthropic_provider_missing_key_falls_back_to_disabled_client() -> (
    None
):
    config = make_settings(copilot_provider="anthropic", anthropic_api_key=None)
    client = build_copilot_client(config)

    assert isinstance(client, CopilotClient)
    assert client.enabled is False


def test_unknown_provider_value_is_rejected_at_config_load() -> None:
    with pytest.raises(ValidationError):
        make_settings(copilot_provider="not-a-real-provider")


def test_default_provider_is_anthropic_for_backward_compatibility() -> None:
    # Pre-existing deployments never set COPILOT_PROVIDER -- the
    # default must reproduce their exact prior behavior (Anthropic if
    # configured, deterministic free mode otherwise).
    config = make_settings()

    assert config.copilot_provider == "anthropic"


def test_groq_model_defaults_to_configured_tool_capable_model() -> None:
    config = make_settings(copilot_provider="groq", groq_api_key="fake-key")
    client = build_copilot_client(config)

    assert client.model == "openai/gpt-oss-120b"


def test_max_retries_defaults_to_one_for_both_providers() -> None:
    # Default preserves pre-existing behavior for anyone upgrading
    # without setting COPILOT_MODEL_MAX_RETRIES.
    anthropic_client = build_copilot_client(
        make_settings(
            copilot_provider="anthropic", anthropic_api_key="fake-key"
        )
    )
    groq_client = build_copilot_client(
        make_settings(copilot_provider="groq", groq_api_key="fake-key")
    )

    assert anthropic_client.max_retries == 1
    assert groq_client.max_retries == 1


def test_max_retries_is_configurable_per_deployment() -> None:
    config = make_settings(
        copilot_provider="anthropic",
        anthropic_api_key="fake-key",
        copilot_model_max_retries=0,
    )
    client = build_copilot_client(config)

    assert client.max_retries == 0
