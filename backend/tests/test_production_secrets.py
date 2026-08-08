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
    )

    assert settings.app_env == "production"


def test_non_production_allows_default_jwt_secret() -> None:
    settings = make_settings(
        app_env="development",
        jwt_secret="development-only-change-this-secret",
    )

    assert settings.jwt_secret == "development-only-change-this-secret"
