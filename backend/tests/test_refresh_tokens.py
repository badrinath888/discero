from fastapi.testclient import TestClient

from app.routers.users import REFRESH_COOKIE_NAME


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


def test_login_returns_access_token_and_sets_refresh_cookie(
    client: TestClient,
) -> None:
    _, payload = register_and_login(
        client,
        "refresh-login@example.com",
    )

    assert payload["access_token"]
    assert payload["token_type"] == "bearer"
    # The refresh token is never in the JSON body -- only the cookie.
    assert "refresh_token" not in payload
    assert client.cookies.get(REFRESH_COOKIE_NAME)


def test_refresh_cookie_is_httponly_and_scoped_to_users_path(
    client: TestClient,
) -> None:
    _, _ = register_and_login(client, "refresh-cookie-attrs@example.com")

    login = client.post(
        "/users/login",
        json={
            "email": "refresh-cookie-attrs@example.com",
            "password": PASSWORD,
        },
    )
    set_cookie = login.headers.get("set-cookie", "")

    assert REFRESH_COOKIE_NAME in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Path=/users" in set_cookie


def test_refresh_issues_valid_access_token_using_cookie(
    client: TestClient,
) -> None:
    user_id, _ = register_and_login(
        client,
        "refresh-valid@example.com",
    )

    # No body needed -- the refresh token travels only via the cookie
    # the client already picked up from /users/login.
    response = client.post("/users/refresh")

    assert response.status_code == 200
    payload = response.json()
    assert payload["access_token"]
    assert payload["user"]["id"] == user_id
    assert "refresh_token" not in payload

    me = client.get(
        "/users/me",
        headers={
            "Authorization": f"Bearer {payload['access_token']}"
        },
    )
    assert me.status_code == 200


def test_refresh_rotates_the_cookie(client: TestClient) -> None:
    register_and_login(client, "refresh-rotate@example.com")
    assert client.cookies.get(REFRESH_COOKIE_NAME)

    response = client.post("/users/refresh")

    assert response.status_code == 200
    # A fresh Set-Cookie is issued on every successful refresh -- not
    # asserting the token value itself differs from the pre-refresh one,
    # since two JWTs minted for the same user/version within the same
    # wall-clock second are legitimately byte-identical (exp has
    # one-second resolution); that is not a rotation failure.
    assert REFRESH_COOKIE_NAME in response.headers.get("set-cookie", "")
    assert client.cookies.get(REFRESH_COOKIE_NAME)


def test_refresh_without_cookie_is_rejected(client: TestClient) -> None:
    response = client.post("/users/refresh")

    assert response.status_code == 401
    assert response.json()["detail"] == (
        "invalid or expired refresh token"
    )


def test_access_token_in_cookie_cannot_refresh(client: TestClient) -> None:
    _, login = register_and_login(
        client,
        "refresh-wrong-type@example.com",
    )

    client.cookies.set(REFRESH_COOKIE_NAME, login["access_token"])

    response = client.post("/users/refresh")

    assert response.status_code == 401
    assert response.json()["detail"] == (
        "invalid or expired refresh token"
    )


def test_refresh_rejects_mismatched_origin(client: TestClient) -> None:
    register_and_login(client, "refresh-bad-origin@example.com")

    response = client.post(
        "/users/refresh",
        headers={"Origin": "https://attacker.example"},
    )

    assert response.status_code == 403


def test_refresh_allows_configured_origin(client: TestClient) -> None:
    register_and_login(client, "refresh-good-origin@example.com")

    response = client.post(
        "/users/refresh",
        headers={"Origin": "http://localhost:3000"},
    )

    assert response.status_code == 200


def test_password_change_invalidates_refresh_cookie(
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

    response = client.post("/users/refresh")

    assert response.status_code == 401
    assert response.json()["detail"] == (
        "session expired; please sign in again"
    )


def test_logout_revokes_refresh_cookie_and_all_access_tokens(
    client: TestClient,
) -> None:
    _, login = register_and_login(client, "logout@example.com")
    access_token = login["access_token"]

    logout_response = client.post(
        "/users/logout",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert logout_response.status_code == 204

    # The refresh cookie no longer works...
    refresh_response = client.post("/users/refresh")
    assert refresh_response.status_code == 401

    # ...and neither does the access token minted before logout.
    me_response = client.get(
        "/users/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert me_response.status_code == 401


def test_logout_requires_authentication(client: TestClient) -> None:
    response = client.post("/users/logout")

    assert response.status_code == 401
