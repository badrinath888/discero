import io

from fastapi.testclient import TestClient


PASSWORD = "TestPassword123!"


def register_and_login(
    client: TestClient,
    email: str,
) -> tuple[int, dict[str, str]]:
    create_response = client.post(
        "/users",
        json={
            "email": email,
            "password": PASSWORD,
        },
    )

    assert create_response.status_code == 201

    login_response = client.post(
        "/users/login",
        json={
            "email": email,
            "password": PASSWORD,
        },
    )

    assert login_response.status_code == 200

    token = login_response.json()["access_token"]

    return create_response.json()["id"], {
        "Authorization": f"Bearer {token}",
    }


def test_health(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_and_get_user(client: TestClient) -> None:
    user_id, headers = register_and_login(
        client,
        "a@b.com",
    )

    response = client.get(
        f"/users/{user_id}",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["email"] == "a@b.com"


def test_duplicate_email_rejected(
    client: TestClient,
) -> None:
    payload = {
        "email": "dup@b.com",
        "password": PASSWORD,
    }

    first = client.post("/users", json=payload)
    second = client.post("/users", json=payload)

    assert first.status_code == 201
    assert second.status_code == 409


def test_change_password(
    client: TestClient,
) -> None:
    email = "password-change@example.com"
    _, headers = register_and_login(client, email)
    new_password = "UpdatedPassword456!"

    response = client.patch(
        "/users/me/password",
        headers=headers,
        json={
            "current_password": PASSWORD,
            "new_password": new_password,
        },
    )

    assert response.status_code == 204

    old_login = client.post(
        "/users/login",
        json={
            "email": email,
            "password": PASSWORD,
        },
    )
    new_login = client.post(
        "/users/login",
        json={
            "email": email,
            "password": new_password,
        },
    )

    assert old_login.status_code == 401
    assert new_login.status_code == 200


def test_change_password_rejects_wrong_current_password(
    client: TestClient,
) -> None:
    _, headers = register_and_login(
        client,
        "wrong-password@example.com",
    )

    response = client.patch(
        "/users/me/password",
        headers=headers,
        json={
            "current_password": "WrongPassword123!",
            "new_password": "UpdatedPassword456!",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "current password is incorrect"


def test_change_password_rejects_same_password(
    client: TestClient,
) -> None:
    _, headers = register_and_login(
        client,
        "same-password@example.com",
    )

    response = client.patch(
        "/users/me/password",
        headers=headers,
        json={
            "current_password": PASSWORD,
            "new_password": PASSWORD,
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "new password must be different"


def test_upload_flow_and_summary(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    csv_bytes = (
        "date,description,amount\n"
        "2026-01-05,Whole Foods,-52.10\n"
        "2026-01-06,Starbucks,-6.25\n"
        "2026-01-06,ACME Payroll,2000.00\n"
    ).encode()

    files = {
        "file": (
            "txns.csv",
            io.BytesIO(csv_bytes),
            "text/csv",
        )
    }

    response = client.post(
        f"/users/{user_id}/transactions/upload",
        files=files,
        headers=auth_headers,
    )

    assert response.status_code == 200

    body = response.json()

    assert body["imported"] == 3
    assert body["rejected"] == 0

    transactions_response = client.get(
        f"/users/{user_id}/transactions",
        headers=auth_headers,
    )

    assert transactions_response.status_code == 200
    assert len(transactions_response.json()) == 3

    summary_response = client.get(
        f"/users/{user_id}/summary/by-category",
        headers=auth_headers,
    )

    assert summary_response.status_code == 200

    categories = {
        row["category"]: row["total_cents"]
        for row in summary_response.json()
    }

    assert categories["Groceries"] == -5210
    assert categories["Income"] == 200000


def test_upload_rejects_non_csv(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    files = {
        "file": (
            "data.txt",
            io.BytesIO(b"hello"),
            "text/plain",
        )
    }

    response = client.post(
        f"/users/{user_id}/transactions/upload",
        files=files,
        headers=auth_headers,
    )

    assert response.status_code == 400


def test_upload_requires_authentication(
    client: TestClient,
) -> None:
    files = {
        "file": (
            "t.csv",
            io.BytesIO(b"date,description,amount\n"),
            "text/csv",
        )
    }

    response = client.post(
        "/users/9999/transactions/upload",
        files=files,
    )

    assert response.status_code == 401


def test_cross_user_access_rejected(
    client: TestClient,
) -> None:
    first_user_id, first_headers = register_and_login(
        client,
        "first@example.com",
    )

    second_user_id, _ = register_and_login(
        client,
        "second@example.com",
    )

    assert first_user_id != second_user_id

    response = client.get(
        f"/users/{second_user_id}/transactions",
        headers=first_headers,
    )

    assert response.status_code == 403