from typing import Literal, Self

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Discero API"
    database_url: str = "sqlite:///./finance.db"
    cors_origins: str = (
        "http://localhost:3000,http://localhost:3001"
    )

    jwt_secret: str = "development-only-change-this-secret"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 30

    app_env: Literal["development", "test", "production"] = "production"
    frontend_url: str = "http://localhost:3000"
    email_backend: Literal["console", "smtp", "resend"] = "console"
    email_from: str = "Discero <no-reply@example.com>"
    resend_api_key: str | None = None
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
    copilot_model_timeout_seconds: float = 20.0
    # SDK-level retry count for a DECIDE/NARRATE HTTP attempt (Anthropic
    # and Groq SDKs both default to 2). Kept at 1 by default -- one
    # retry on a transient error without letting worst-case latency on
    # the turn's single allowed provider call approach ~3x the timeout.
    # Configurable rather than hardcoded so it can be tuned per
    # deployment without a code change if production latency data
    # supports it.
    copilot_model_max_retries: int = 1

    # Default "anthropic" preserves pre-existing deployments' behavior
    # (Anthropic if ANTHROPIC_API_KEY is set, deterministic free mode
    # otherwise) for anyone who upgrades without setting this var.
    copilot_provider: Literal["groq", "anthropic", "free"] = "anthropic"
    groq_api_key: str | None = None
    copilot_groq_model: str = "llama-3.3-70b-versatile"

    # Estimated-cost observability (see app/services/copilot_observability.py).
    # Both unset by default -- an unconfigured deployment must never see a
    # fabricated cost figure; estimated_cost stays null until an operator
    # sets both rates for whichever provider/model they're running.
    copilot_input_cost_per_million_tokens: float | None = None
    copilot_output_cost_per_million_tokens: float | None = None

    plaid_client_id: str | None = None
    plaid_secret: str | None = None
    plaid_env: Literal["sandbox", "production"] = "sandbox"
    plaid_products: str = "transactions"
    plaid_country_codes: str = "US"
    plaid_redirect_uri: str | None = None

    @field_validator("database_url", mode="after")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        # Some hosting providers (e.g. Heroku-style config vars) still emit
        # the legacy "postgres://" scheme, which SQLAlchemy 1.4+ rejects.
        if value.startswith("postgres://"):
            return "postgresql://" + value[len("postgres://") :]
        return value

    @model_validator(mode="after")
    def validate_email_delivery(self) -> Self:
        if self.email_backend == "resend" and not self.resend_api_key:
            raise ValueError(
                "RESEND_API_KEY is required when EMAIL_BACKEND=resend"
            )
        return self

    @model_validator(mode="after")
    def validate_production_secrets(self) -> Self:
        # Only the literal shipped-in-source default is rejected here;
        # this is not a general secret-strength check.
        if (
            self.app_env == "production"
            and self.jwt_secret == "development-only-change-this-secret"
        ):
            raise ValueError(
                "JWT_SECRET must be set to a real secret when "
                "APP_ENV=production; the default development value "
                "is not safe to use in production"
            )
        return self

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
