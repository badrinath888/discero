import pytest
from pydantic import ValidationError

from app.config import Settings
from app.services.plaid_service import (
    PlaidConfigurationError,
    get_plaid_client,
)


def make_settings(**overrides: object) -> Settings:
    return Settings(
        _env_file=None,
        database_url="sqlite://",
        jwt_secret="test-secret",
        **overrides,
    )


def test_plaid_defaults() -> None:
    settings = make_settings()

    assert settings.plaid_env == "sandbox"
    assert settings.plaid_product_list == ["transactions"]
    assert settings.plaid_country_code_list == ["US"]
    assert settings.plaid_is_configured is False


def test_plaid_lists_are_normalized() -> None:
    settings = make_settings(
        plaid_products="transactions, identity",
        plaid_country_codes="us, ca",
    )

    assert settings.plaid_product_list == [
        "transactions",
        "identity",
    ]
    assert settings.plaid_country_code_list == ["US", "CA"]


def test_plaid_rejects_invalid_environment() -> None:
    with pytest.raises(ValidationError):
        make_settings(plaid_env="invalid")


def test_plaid_client_requires_credentials() -> None:
    settings = make_settings()

    with pytest.raises(
        PlaidConfigurationError,
        match="Plaid credentials are not configured",
    ):
        get_plaid_client(settings)


def test_plaid_client_can_be_created() -> None:
    settings = make_settings(
        plaid_client_id="test-client-id",
        plaid_secret="test-secret",
    )

    client = get_plaid_client(settings)

    assert client is not None