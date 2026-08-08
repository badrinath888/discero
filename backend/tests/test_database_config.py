from app.config import Settings


def make_settings(**overrides: object) -> Settings:
    overrides.setdefault("database_url", "sqlite://")
    return Settings(
        _env_file=None,
        jwt_secret="test-secret",
        **overrides,
    )


def test_sqlite_database_url_is_left_unchanged() -> None:
    settings = make_settings(database_url="sqlite:///./finance.db")

    assert settings.database_url == "sqlite:///./finance.db"


def test_postgres_scheme_is_normalized_to_postgresql() -> None:
    settings = make_settings(
        database_url="postgres://user:pw@host:5432/dbname"
    )

    assert settings.database_url == "postgresql://user:pw@host:5432/dbname"


def test_postgresql_scheme_is_left_unchanged() -> None:
    settings = make_settings(
        database_url="postgresql://user:pw@host:5432/dbname"
    )

    assert settings.database_url == "postgresql://user:pw@host:5432/dbname"
