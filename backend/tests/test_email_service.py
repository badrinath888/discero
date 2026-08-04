import logging
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from app.config import Settings, settings
from app.routers import users
from app.services import email_service


def configure_resend(monkeypatch) -> None:
    monkeypatch.setattr(settings, "email_backend", "resend")
    monkeypatch.setattr(settings, "resend_api_key", "re_test_secret")
    monkeypatch.setattr(settings, "email_from", "FinSight <mail@example.com>")
    monkeypatch.setattr(settings, "frontend_url", "https://app.example.com/")


def test_resend_sends_password_reset(monkeypatch) -> None:
    configure_resend(monkeypatch)
    send = MagicMock(return_value={"id": "email-id"})
    monkeypatch.setattr(email_service.resend.Emails, "send", send)

    email_service.send_password_reset("user@example.com", "reset-token")

    send.assert_called_once_with(
        {
            "from": "FinSight <mail@example.com>",
            "to": ["user@example.com"],
            "subject": "Reset your FinSight password",
            "text": (
                "Reset your password within 30 minutes:\n"
                "https://app.example.com/reset-password?token=reset-token"
            ),
        }
    )


def test_resend_sends_email_verification(monkeypatch) -> None:
    configure_resend(monkeypatch)
    send = MagicMock(return_value={"id": "email-id"})
    monkeypatch.setattr(email_service.resend.Emails, "send", send)

    email_service.send_email_verification(
        "user@example.com", "verification-token"
    )

    send.assert_called_once_with(
        {
            "from": "FinSight <mail@example.com>",
            "to": ["user@example.com"],
            "subject": "Verify your FinSight email",
            "text": (
                "Verify your email within 24 hours:\n"
                "https://app.example.com/verify-email?token=verification-token"
            ),
        }
    )


def test_resend_requires_api_key() -> None:
    with pytest.raises(
        ValidationError,
        match="RESEND_API_KEY is required when EMAIL_BACKEND=resend",
    ):
        Settings(
            _env_file=None,
            email_backend="resend",
            resend_api_key=None,
        )


def test_resend_failure_raises_clear_internal_error(monkeypatch) -> None:
    configure_resend(monkeypatch)
    monkeypatch.setattr(
        email_service.resend.Emails,
        "send",
        MagicMock(side_effect=RuntimeError("provider rejected request")),
    )

    with pytest.raises(
        RuntimeError, match="Resend email delivery failed"
    ) as error:
        email_service.send_password_reset("user@example.com", "reset-token")

    assert error.value.__context__ is not None
    assert error.value.__suppress_context__ is True


def test_delivery_failure_logs_do_not_leak_secrets(
    monkeypatch, caplog
) -> None:
    api_key = "re_private_api_key"
    reset_token = "private-reset-token"
    verification_token = "private-verification-token"
    smtp_password = "private-smtp-password"
    monkeypatch.setattr(
        email_service,
        "send_password_reset",
        MagicMock(
            side_effect=RuntimeError(
                f"{api_key} {reset_token} {smtp_password}"
            )
        ),
    )
    monkeypatch.setattr(
        email_service,
        "send_email_verification",
        MagicMock(side_effect=RuntimeError(verification_token)),
    )

    with caplog.at_level(logging.ERROR, logger=users.__name__):
        users._send_password_reset("user@example.com", reset_token)
        users._send_verification("user@example.com", verification_token)

    assert "Unable to deliver password reset email" in caplog.text
    assert "Unable to deliver verification email" in caplog.text
    for secret in (api_key, reset_token, verification_token, smtp_password):
        assert secret not in caplog.text
    assert "reset-password?token=" not in caplog.text
    assert "verify-email?token=" not in caplog.text


def test_smtp_delivery_is_unchanged(monkeypatch) -> None:
    monkeypatch.setattr(settings, "email_backend", "smtp")
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_port", 2525)
    monkeypatch.setattr(settings, "smtp_use_tls", True)
    monkeypatch.setattr(settings, "smtp_username", "smtp-user")
    monkeypatch.setattr(settings, "smtp_password", "smtp-password")
    smtp = MagicMock()
    smtp_factory = MagicMock()
    smtp_factory.return_value.__enter__.return_value = smtp
    monkeypatch.setattr(email_service.smtplib, "SMTP", smtp_factory)

    email_service.send_password_reset("user@example.com", "reset-token")

    smtp_factory.assert_called_once_with(
        "smtp.example.com", 2525, timeout=10
    )
    smtp.starttls.assert_called_once_with()
    smtp.login.assert_called_once_with("smtp-user", "smtp-password")
    message = smtp.send_message.call_args.args[0]
    assert message["From"] == settings.email_from
    assert message["To"] == "user@example.com"
    assert "reset-password?token=reset-token" in message.get_content()


def test_console_delivery_remains_available_in_development(
    monkeypatch, caplog
) -> None:
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "email_backend", "console")

    with caplog.at_level(logging.WARNING, logger=email_service.__name__):
        email_service.send_password_reset("user@example.com", "reset-token")

    assert "Development email to user@example.com" in caplog.text
    assert "Reset your FinSight password" in caplog.text
    assert "reset-token" not in caplog.text
    assert "reset-password?token=" not in caplog.text
