from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, read from environment / .env file.

    DATABASE_URL controls where data lives:
      - local dev / tests: sqlite:///./finance.db
      - production:        postgresql+psycopg2://user:pass@host:5432/finance
    Phase 4 (RAG) will require Postgres + pgvector; Phase 1 runs on either.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./finance.db"
    app_name: str = "Finance Platform API"


settings = Settings()
