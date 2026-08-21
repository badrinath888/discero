import pytest
from pydantic import ValidationError

from app.config import Settings


def make_settings(**overrides: object) -> Settings:
    overrides.setdefault("database_url", "sqlite://")
    return Settings(_env_file=None, **overrides)


def test_production_rejects_default_jwt_secret() -> None:
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        make_settings(
            app_env="production",
            jwt_secret="development-only-change-this-secret",
        )


def test_production_accepts_real_jwt_secret() -> None:
    settings = make_settings(
        app_env="production",
        jwt_secret="a-real-randomly-generated-secret",
        cors_origins="https://discero-app.vercel.app",
    )

    assert settings.app_env == "production"


def test_non_production_allows_default_jwt_secret() -> None:
    settings = make_settings(
        app_env="development",
        jwt_secret="development-only-change-this-secret",
    )

    assert settings.jwt_secret == "development-only-change-this-secret"


def test_production_rejects_wildcard_cors() -> None:
    with pytest.raises(ValidationError, match="CORS_ORIGINS"):
        make_settings(
            app_env="production",
            jwt_secret="a-real-randomly-generated-secret",
            cors_origins="*",
        )


def test_production_rejects_empty_cors() -> None:
    with pytest.raises(ValidationError, match="CORS_ORIGINS"):
        make_settings(
            app_env="production",
            jwt_secret="a-real-randomly-generated-secret",
            cors_origins="",
        )


def test_production_rejects_localhost_cors_origin() -> None:
    with pytest.raises(ValidationError, match="CORS_ORIGINS"):
        make_settings(
            app_env="production",
            jwt_secret="a-real-randomly-generated-secret",
            cors_origins="https://discero-app.vercel.app,http://localhost:3000",
        )


def test_production_accepts_exact_deployed_origin() -> None:
    settings = make_settings(
        app_env="production",
        jwt_secret="a-real-randomly-generated-secret",
        cors_origins="https://discero-app.vercel.app",
    )

    assert settings.cors_origin_list == ["https://discero-app.vercel.app"]


def test_non_production_allows_localhost_cors() -> None:
    settings = make_settings(
        app_env="development",
        jwt_secret="a-real-randomly-generated-secret",
    )

    assert "http://localhost:3000" in settings.cors_origin_list


def test_production_with_plaid_requires_encryption_key() -> None:
    with pytest.raises(ValidationError, match="TOKEN_ENCRYPTION_KEY"):
        make_settings(
            app_env="production",
            jwt_secret="a-real-randomly-generated-secret",
            cors_origins="https://discero-app.vercel.app",
            plaid_client_id="plaid-client-id",
            plaid_secret="plaid-secret",
            token_encryption_key=None,
        )


def test_production_with_plaid_and_encryption_key_is_valid() -> None:
    settings = make_settings(
        app_env="production",
        jwt_secret="a-real-randomly-generated-secret",
        cors_origins="https://discero-app.vercel.app",
        plaid_client_id="plaid-client-id",
        plaid_secret="plaid-secret",
        token_encryption_key="a-real-fernet-key",
    )

    assert settings.token_encryption_key == "a-real-fernet-key"


def test_production_without_plaid_does_not_require_encryption_key() -> None:
    settings = make_settings(
        app_env="production",
        jwt_secret="a-real-randomly-generated-secret",
        cors_origins="https://discero-app.vercel.app",
        token_encryption_key=None,
    )

    assert settings.token_encryption_key is None
