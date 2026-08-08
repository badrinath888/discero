from fastapi.testclient import TestClient


def test_login_is_rate_limited_after_repeated_attempts(
    client: TestClient,
) -> None:
    client.post(
        "/users",
        json={
            "email": "rate-limit-login@example.com",
            "password": "TestPassword123!",
        },
    )

    for _ in range(10):
        response = client.post(
            "/users/login",
            json={
                "email": "rate-limit-login@example.com",
                "password": "WrongPassword!",
            },
        )
        assert response.status_code == 401

    blocked = client.post(
        "/users/login",
        json={
            "email": "rate-limit-login@example.com",
            "password": "WrongPassword!",
        },
    )

    assert blocked.status_code == 429


def test_registration_is_rate_limited(client: TestClient) -> None:
    for i in range(10):
        client.post(
            "/users",
            json={
                "email": f"rate-limit-register-{i}@example.com",
                "password": "TestPassword123!",
            },
        )

    blocked = client.post(
        "/users",
        json={
            "email": "rate-limit-register-overflow@example.com",
            "password": "TestPassword123!",
        },
    )

    assert blocked.status_code == 429


def test_forgot_password_is_rate_limited(
    client: TestClient,
) -> None:
    for _ in range(10):
        response = client.post(
            "/users/forgot-password",
            json={"email": "nobody@example.com"},
        )
        assert response.status_code == 200

    blocked = client.post(
        "/users/forgot-password",
        json={"email": "nobody@example.com"},
    )

    assert blocked.status_code == 429


def test_rate_limit_is_scoped_per_endpoint(
    client: TestClient,
) -> None:
    # Exhausting the login limiter must not affect an unrelated
    # endpoint sharing the same client IP.
    for _ in range(10):
        client.post(
            "/users/login",
            json={
                "email": "unrelated@example.com",
                "password": "WrongPassword!",
            },
        )

    response = client.post(
        "/users",
        json={
            "email": "rate-limit-scope@example.com",
            "password": "TestPassword123!",
        },
    )

    assert response.status_code == 201
