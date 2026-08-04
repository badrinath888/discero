import logging
import smtplib
from email.message import EmailMessage

import resend

from app.config import settings


logger = logging.getLogger(__name__)


def send_password_reset(email: str, token: str) -> None:
    link = f"{settings.frontend_url.rstrip('/')}/reset-password?token={token}"
    _send(
        email,
        "Reset your FinSight password",
        f"Reset your password within {settings.password_reset_expire_minutes} minutes:\n{link}",
    )


def send_email_verification(email: str, token: str) -> None:
    link = f"{settings.frontend_url.rstrip('/')}/verify-email?token={token}"
    _send(
        email,
        "Verify your FinSight email",
        f"Verify your email within {settings.email_verification_expire_hours} hours:\n{link}",
    )


def _send(recipient: str, subject: str, body: str) -> None:
    if settings.email_backend == "console":
        if settings.app_env == "production":
            raise RuntimeError("console email is disabled in production")

        logger.warning("Development email to %s: %s", recipient, subject)
        return

    if settings.email_backend == "resend":
        if not settings.resend_api_key:
            raise RuntimeError(
                "RESEND_API_KEY is required for Resend email delivery"
            )

        resend.api_key = settings.resend_api_key
        try:
            resend.Emails.send(
                {
                    "from": settings.email_from,
                    "to": [recipient],
                    "subject": subject,
                    "text": body,
                }
            )
        except Exception:
            raise RuntimeError("Resend email delivery failed") from None
        return

    if not settings.smtp_host:
        raise RuntimeError("SMTP_HOST is required for SMTP email delivery")

    message = EmailMessage()
    message["From"] = settings.email_from
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        if settings.smtp_use_tls:
            smtp.starttls()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password or "")
        smtp.send_message(message)
