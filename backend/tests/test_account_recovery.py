from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.main import app
from app.models import User
from app.security import hash_one_time_token
from app.services import email_service


EMAIL = "recovery@example.com"
PASSWORD = "TestPassword123!"
NEW_PASSWORD = "UpdatedPassword456!"
GENERIC_RESET = (
    "If an account exists for that email, a password reset link has been sent."
)
GENERIC_VERIFICATION = (
    "If the address needs verification, a verification link has been sent."
)


def db_session() -> Session:
    override = app.dependency_overrides[get_db]
    generator = override()
    db = next(generator)
    db.info["test_generator"] = generator
    return db


def close_db(db: Session) -> None:
    generator = db.info.pop("test_generator")
    try:
        next(generator)
    except StopIteration:
        pass


def register(client: TestClient, email: str = EMAIL) -> int:
    response = client.post(
        "/users", json={"email": email, "password": PASSWORD}
    )
    assert response.status_code == 201
    return response.json()["id"]


def capture_delivery(monkeypatch, name: str) -> list[tuple[str, str]]:
    deliveries: list[tuple[str, str]] = []
    monkeypatch.setattr(
        email_service,
        name,
        lambda email, token: deliveries.append((email, token)),
    )
    return deliveries


def test_forgot_password_is_generic_and_stores_only_hash(
    client: TestClient, monkeypatch
) -> None:
    deliveries = capture_delivery(monkeypatch, "send_password_reset")
    user_id = register(client)

    existing = client.post("/users/forgot-password", json={"email": EMAIL})
    unknown = client.post(
        "/users/forgot-password", json={"email": "unknown@example.com"}
    )

    assert existing.status_code == unknown.status_code == 200
    assert existing.json() == unknown.json() == {"message": GENERIC_RESET}
    assert len(deliveries) == 1
    raw_token = deliveries[0][1]
    db = db_session()
    try:
        user = db.get(User, user_id)
        assert user is not None
        assert user.password_reset_token_hash == hash_one_time_token(raw_token)
        assert user.password_reset_token_hash != raw_token
    finally:
        close_db(db)


def test_valid_reset_changes_password_invalidates_session_and_is_single_use(
    client: TestClient, monkeypatch
) -> None:
    deliveries = capture_delivery(monkeypatch, "send_password_reset")
    user_id = register(client)
    login = client.post(
        "/users/login", json={"email": EMAIL, "password": PASSWORD}
    )
    old_headers = {
        "Authorization": f"Bearer {login.json()['access_token']}"
    }
    client.post("/users/forgot-password", json={"email": EMAIL})
    token = deliveries[0][1]

    response = client.post(
        "/users/reset-password",
        json={"token": token, "new_password": NEW_PASSWORD},
    )

    assert response.status_code == 200
    db = db_session()
    try:
        user = db.get(User, user_id)
        assert user is not None
        assert user.token_version == 1
        assert user.password_reset_token_hash is None
        assert user.password_reset_expires_at is None
    finally:
        close_db(db)
    assert client.get("/users/me", headers=old_headers).status_code == 401
    assert client.post(
        "/users/login", json={"email": EMAIL, "password": PASSWORD}
    ).status_code == 401
    assert client.post(
        "/users/login", json={"email": EMAIL, "password": NEW_PASSWORD}
    ).status_code == 200
    assert client.post(
        "/users/reset-password",
        json={"token": token, "new_password": "AnotherPassword789!"},
    ).status_code == 400


def test_invalid_reset_token_fails(client: TestClient) -> None:
    response = client.post(
        "/users/reset-password",
        json={"token": "unknown-token", "new_password": NEW_PASSWORD},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "password reset link is invalid or expired"


def test_expired_reset_token_fails(
    client: TestClient, monkeypatch
) -> None:
    deliveries = capture_delivery(monkeypatch, "send_password_reset")
    user_id = register(client)
    client.post("/users/forgot-password", json={"email": EMAIL})
    db = db_session()
    try:
        user = db.get(User, user_id)
        assert user is not None
        user.password_reset_expires_at = datetime.now(timezone.utc) - timedelta(
            seconds=1
        )
        db.commit()
    finally:
        close_db(db)

    response = client.post(
        "/users/reset-password",
        json={"token": deliveries[0][1], "new_password": NEW_PASSWORD},
    )

    assert response.status_code == 400


def test_verification_succeeds_and_is_single_use(
    client: TestClient, monkeypatch
) -> None:
    deliveries = capture_delivery(monkeypatch, "send_email_verification")
    user_id = register(client)
    token = deliveries[0][1]

    response = client.post("/users/verify-email", json={"token": token})

    assert response.status_code == 200
    db = db_session()
    try:
        user = db.get(User, user_id)
        assert user is not None
        assert user.email_verified is True
        assert user.email_verification_token_hash is None
    finally:
        close_db(db)
    assert client.post(
        "/users/verify-email", json={"token": token}
    ).status_code == 400


def test_invalid_verification_token_fails(client: TestClient) -> None:
    response = client.post(
        "/users/verify-email", json={"token": "unknown-token"}
    )

    assert response.status_code == 400
    assert (
        response.json()["detail"]
        == "email verification link is invalid or expired"
    )


def test_expired_verification_token_fails(
    client: TestClient, monkeypatch
) -> None:
    deliveries = capture_delivery(monkeypatch, "send_email_verification")
    user_id = register(client)
    db = db_session()
    try:
        user = db.get(User, user_id)
        assert user is not None
        user.email_verification_expires_at = datetime.now(
            timezone.utc
        ) - timedelta(seconds=1)
        db.commit()
    finally:
        close_db(db)

    response = client.post(
        "/users/verify-email", json={"token": deliveries[0][1]}
    )

    assert response.status_code == 400


def test_resend_rotates_token_and_remains_generic(
    client: TestClient, monkeypatch
) -> None:
    deliveries = capture_delivery(monkeypatch, "send_email_verification")
    register(client)
    original_token = deliveries[-1][1]

    resend = client.post("/users/resend-verification", json={"email": EMAIL})
    unknown = client.post(
        "/users/resend-verification", json={"email": "unknown@example.com"}
    )

    assert resend.json() == unknown.json() == {"message": GENERIC_VERIFICATION}
    resent_token = deliveries[-1][1]
    assert resent_token != original_token
    assert client.post(
        "/users/verify-email", json={"token": original_token}
    ).status_code == 400
    assert client.post(
        "/users/verify-email", json={"token": resent_token}
    ).status_code == 200


def test_already_verified_resend_is_generic_without_delivery(
    client: TestClient, monkeypatch
) -> None:
    deliveries = capture_delivery(monkeypatch, "send_email_verification")
    register(client)
    token = deliveries.pop()[1]
    assert client.post(
        "/users/verify-email", json={"token": token}
    ).status_code == 200

    response = client.post(
        "/users/resend-verification", json={"email": EMAIL}
    )

    assert response.json() == {"message": GENERIC_VERIFICATION}
    assert deliveries == []


def test_unverified_users_may_log_in(
    client: TestClient, monkeypatch
) -> None:
    capture_delivery(monkeypatch, "send_email_verification")
    register(client)

    response = client.post(
        "/users/login", json={"email": EMAIL, "password": PASSWORD}
    )

    assert response.status_code == 200
    assert response.json()["user"]["email_verified"] is False


def test_console_delivery_is_blocked_without_logging_token_in_production(
    monkeypatch, caplog
) -> None:
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "email_backend", "console")

    with pytest.raises(RuntimeError, match="disabled in production"):
        email_service.send_password_reset("user@example.com", "raw-secret-token")

    assert "raw-secret-token" not in caplog.text
