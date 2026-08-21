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


def test_cors_middleware_allows_credentials_only_with_explicit_origins() -> (
    None
):
    # allow_credentials=True is required for the browser to send/receive
    # the HttpOnly refresh-token cookie (see app/routers/users.py) --
    # this is safe ONLY because allow_origins is always a concrete list,
    # never "*". Starlette itself refuses that combination at
    # middleware-construction time, but this asserts the actual
    # deployed config never even attempts it, regardless.
    cors_middleware = next(
        m for m in app.user_middleware if m.cls.__name__ == "CORSMiddleware"
    )

    assert cors_middleware.kwargs.get("allow_credentials") is True
    assert "*" not in cors_middleware.kwargs.get("allow_origins", [])
    assert cors_middleware.kwargs.get("allow_origins")
