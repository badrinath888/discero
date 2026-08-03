from datetime import datetime, timedelta, timezone

import jwt
from fastapi.testclient import TestClient

from app.config import settings
from app.database import get_db
from app.main import app
from app.models import User
from app.security import create_access_token, decode_access_token


PASSWORD = "TestPassword123!"
NEW_PASSWORD = "UpdatedPassword456!"
SESSION_EXPIRED = "session expired; please sign in again"


def register_and_login(
    client: TestClient,
    email: str,
) -> tuple[int, str]:
    create_response = client.post(
        "/users",
        json={"email": email, "password": PASSWORD},
    )
    assert create_response.status_code == 201

    login_response = client.post(
        "/users/login",
        json={"email": email, "password": PASSWORD},
    )
    assert login_response.status_code == 200

    return (
        create_response.json()["id"],
        login_response.json()["access_token"],
    )


def authorization(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def token_version(user_id: int) -> int:
    override = app.dependency_overrides[get_db]
    db_generator = override()
    db = next(db_generator)

    try:
        user = db.get(User, user_id)
        assert user is not None
        return user.token_version
    finally:
        try:
            next(db_generator)
        except StopIteration:
            pass


def test_password_change_invalidates_old_token_and_new_login_works(
    client: TestClient,
) -> None:
    email = "token-password@example.com"
    user_id, old_token = register_and_login(client, email)
    old_headers = authorization(old_token)

    assert decode_access_token(old_token) == (user_id, 0)
    assert client.get("/users/me", headers=old_headers).status_code == 200
    assert token_version(user_id) == 0

    change_response = client.patch(
        "/users/me/password",
        headers=old_headers,
        json={
            "current_password": PASSWORD,
            "new_password": NEW_PASSWORD,
        },
    )

    assert change_response.status_code == 204
    assert token_version(user_id) == 1

    old_token_response = client.get("/users/me", headers=old_headers)
    assert old_token_response.status_code == 401
    assert old_token_response.json()["detail"] == SESSION_EXPIRED

    old_login = client.post(
        "/users/login",
        json={"email": email, "password": PASSWORD},
    )
    new_login = client.post(
        "/users/login",
        json={"email": email, "password": NEW_PASSWORD},
    )

    assert old_login.status_code == 401
    assert new_login.status_code == 200
    new_token = new_login.json()["access_token"]
    assert decode_access_token(new_token) == (user_id, 1)
    assert client.get(
        "/users/me",
        headers=authorization(new_token),
    ).status_code == 200


def test_email_change_invalidates_old_token(
    client: TestClient,
) -> None:
    old_email = "token-old-email@example.com"
    new_email = "token-new-email@example.com"
    user_id, old_token = register_and_login(client, old_email)
    old_headers = authorization(old_token)

    change_response = client.patch(
        "/users/me/email",
        headers=old_headers,
        json={
            "new_email": new_email,
            "current_password": PASSWORD,
        },
    )

    assert change_response.status_code == 200
    assert token_version(user_id) == 1
    rejected = client.get("/users/me", headers=old_headers)
    assert rejected.status_code == 401
    assert rejected.json()["detail"] == SESSION_EXPIRED

    new_login = client.post(
        "/users/login",
        json={"email": new_email, "password": PASSWORD},
    )
    assert new_login.status_code == 200
    assert decode_access_token(new_login.json()["access_token"]) == (
        user_id,
        1,
    )


def test_failed_password_change_does_not_increment_version(
    client: TestClient,
) -> None:
    user_id, token = register_and_login(
        client,
        "token-failed-password@example.com",
    )
    headers = authorization(token)

    response = client.patch(
        "/users/me/password",
        headers=headers,
        json={
            "current_password": "WrongPassword123!",
            "new_password": NEW_PASSWORD,
        },
    )

    assert response.status_code == 400
    assert token_version(user_id) == 0
    assert client.get("/users/me", headers=headers).status_code == 200


def test_failed_email_change_does_not_increment_version(
    client: TestClient,
) -> None:
    user_id, token = register_and_login(
        client,
        "token-failed-email@example.com",
    )
    headers = authorization(token)

    response = client.patch(
        "/users/me/email",
        headers=headers,
        json={
            "new_email": "unused-token-email@example.com",
            "current_password": "WrongPassword123!",
        },
    )

    assert response.status_code == 400
    assert token_version(user_id) == 0
    assert client.get("/users/me", headers=headers).status_code == 200


def test_token_with_incorrect_version_is_rejected(
    client: TestClient,
) -> None:
    user_id, _ = register_and_login(
        client,
        "token-wrong-version@example.com",
    )
    token = create_access_token(user_id, token_version=99)

    response = client.get("/users/me", headers=authorization(token))

    assert response.status_code == 401
    assert response.json()["detail"] == SESSION_EXPIRED


def test_legacy_token_without_version_is_rejected(
    client: TestClient,
) -> None:
    user_id, _ = register_and_login(
        client,
        "token-legacy@example.com",
    )
    token = jwt.encode(
        {
            "sub": str(user_id),
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )

    response = client.get("/users/me", headers=authorization(token))

    assert response.status_code == 401
    assert response.json()["detail"] == SESSION_EXPIRED


def test_other_user_access_remains_forbidden(
    client: TestClient,
) -> None:
    _, first_token = register_and_login(
        client,
        "token-first-user@example.com",
    )
    second_user_id, _ = register_and_login(
        client,
        "token-second-user@example.com",
    )

    response = client.get(
        f"/users/{second_user_id}",
        headers=authorization(first_token),
    )

    assert response.status_code == 403
