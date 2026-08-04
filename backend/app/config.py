from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "FinSight API"
    database_url: str = "sqlite:///./finance.db"
    cors_origins: str = (
        "http://localhost:3000,http://localhost:3001"
    )

    jwt_secret: str = "development-only-change-this-secret"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    app_env: Literal["development", "test", "production"] = "production"
    frontend_url: str = "http://localhost:3000"
    email_backend: Literal["console", "smtp"] = "console"
    email_from: str = "FinSight <no-reply@example.com>"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True
    password_reset_expire_minutes: int = 30
    email_verification_expire_hours: int = 24

    token_encryption_key: str | None = None

    anthropic_api_key: str | None = None
    llm_model: str = "claude-sonnet-4-6"

    plaid_client_id: str | None = None
    plaid_secret: str | None = None
    plaid_env: Literal["sandbox", "production"] = "sandbox"
    plaid_products: str = "transactions"
    plaid_country_codes: str = "US"
    plaid_redirect_uri: str | None = None

    @property
    def cors_origin_list(self) -> list[str]:
        return [
            origin.strip().rstrip("/")
            for origin in self.cors_origins.split(",")
            if origin.strip()
        ]

    @property
    def plaid_is_configured(self) -> bool:
        return bool(self.plaid_client_id and self.plaid_secret)

    @property
    def token_encryption_is_configured(self) -> bool:
        return bool(self.token_encryption_key)

    @property
    def plaid_product_list(self) -> list[str]:
        return [
            value.strip()
            for value in self.plaid_products.split(",")
            if value.strip()
        ]

    @property
    def plaid_country_code_list(self) -> list[str]:
        return [
            value.strip().upper()
            for value in self.plaid_country_codes.split(",")
            if value.strip()
        ]


settings = Settings()
