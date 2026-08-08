from app.config import Settings
from app.main import app


def make_settings(**overrides: object) -> Settings:
    overrides.setdefault("database_url", "sqlite://")
    return Settings(
        _env_file=None,
        jwt_secret="test-secret",
        **overrides,
    )


def test_default_cors_origins_are_not_wildcard() -> None:
    origins = make_settings().cors_origin_list

    assert "*" not in origins


def test_cors_origins_parses_and_strips_trailing_slash() -> None:
    settings = make_settings(
        cors_origins="https://app.example.com/, https://admin.example.com"
    )

    assert settings.cors_origin_list == [
        "https://app.example.com",
        "https://admin.example.com",
    ]


def test_cors_middleware_does_not_allow_credentials() -> None:
    cors_middleware = next(
        m for m in app.user_middleware if m.cls.__name__ == "CORSMiddleware"
    )

    assert cors_middleware.kwargs.get("allow_credentials", False) is False
    assert "*" not in cors_middleware.kwargs.get("allow_origins", [])
