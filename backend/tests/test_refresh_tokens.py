from fastapi.testclient import TestClient


PASSWORD = "TestPassword123!"
NEW_PASSWORD = "UpdatedPassword456!"


def register_and_login(
    client: TestClient,
    email: str,
) -> tuple[int, dict]:
    created = client.post(
        "/users",
        json={"email": email, "password": PASSWORD},
    )
    assert created.status_code == 201

    login = client.post(
        "/users/login",
        json={"email": email, "password": PASSWORD},
    )
    assert login.status_code == 200

    return created.json()["id"], login.json()


def test_login_returns_refresh_token(client: TestClient) -> None:
    _, payload = register_and_login(
        client,
        "refresh-login@example.com",
    )

    assert payload["access_token"]
    assert payload["refresh_token"]
    assert payload["token_type"] == "bearer"


def test_refresh_issues_valid_tokens(client: TestClient) -> None:
    user_id, login = register_and_login(
        client,
        "refresh-valid@example.com",
    )

    response = client.post(
        "/users/refresh",
        json={"refresh_token": login["refresh_token"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["access_token"]
    assert payload["refresh_token"]
    assert payload["user"]["id"] == user_id

    me = client.get(
        "/users/me",
        headers={
            "Authorization": f"Bearer {payload['access_token']}"
        },
    )
    assert me.status_code == 200


def test_access_token_cannot_refresh(client: TestClient) -> None:
    _, login = register_and_login(
        client,
        "refresh-wrong-type@example.com",
    )

    response = client.post(
        "/users/refresh",
        json={"refresh_token": login["access_token"]},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == (
        "invalid or expired refresh token"
    )


def test_password_change_invalidates_refresh_token(
    client: TestClient,
) -> None:
    _, login = register_and_login(
        client,
        "refresh-invalidated@example.com",
    )

    change = client.patch(
        "/users/me/password",
        headers={
            "Authorization": f"Bearer {login['access_token']}"
        },
        json={
            "current_password": PASSWORD,
            "new_password": NEW_PASSWORD,
        },
    )
    assert change.status_code == 204

    response = client.post(
        "/users/refresh",
        json={"refresh_token": login["refresh_token"]},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == (
        "session expired; please sign in again"
    )
