from uuid import uuid4

from fastapi.testclient import TestClient


PASSWORD = "TestPassword123!"


def register_and_login(
    client: TestClient,
    prefix: str,
) -> tuple[int, dict[str, str]]:
    email = f"{prefix}-{uuid4().hex}@example.com"

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

    return create_response.json()["id"], {
        "Authorization": (
            f"Bearer {login_response.json()['access_token']}"
        )
    }


def recurring_payload() -> dict[str, object]:
    return {
        "merchant": "Netflix",
        "normalized_merchant": "NETFLIX",
        "category": "Subscriptions",
        "amount_cents": 1599,
        "frequency": "Monthly",
        "last_payment": "2026-07-10",
        "next_payment": "2026-08-10",
        "confidence_score": 95.5,
        "price_change_percent": 0.0,
        "price_change_warning": False,
    }


def test_create_and_list_recurring_item(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client,
        "recurring-create",
    )

    response = client.post(
        f"/users/{user_id}/recurring-items",
        headers=headers,
        json=recurring_payload(),
    )

    assert response.status_code == 201

    body = response.json()

    assert body["merchant"] == "Netflix"
    assert body["normalized_merchant"] == "NETFLIX"
    assert body["category"] == "Subscriptions"
    assert body["amount_cents"] == 1599
    assert body["frequency"] == "Monthly"
    assert body["status"] == "suggested"
    assert body["confidence_score"] == 95.5

    list_response = client.get(
        f"/users/{user_id}/recurring-items",
        headers=headers,
    )

    assert list_response.status_code == 200
    assert len(list_response.json()) == 1


def test_update_recurring_item(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client,
        "recurring-update",
    )

    created = client.post(
        f"/users/{user_id}/recurring-items",
        headers=headers,
        json=recurring_payload(),
    )

    item_id = created.json()["id"]

    updated = client.patch(
        f"/users/{user_id}/recurring-items/{item_id}",
        headers=headers,
        json={
            "amount_cents": 1799,
            "status": "active",
            "next_payment": "2026-09-10",
        },
    )

    assert updated.status_code == 200

    body = updated.json()

    assert body["amount_cents"] == 1799
    assert body["status"] == "active"
    assert body["next_payment"] == "2026-09-10"


def test_duplicate_recurring_item_rejected(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client,
        "recurring-duplicate",
    )

    first = client.post(
        f"/users/{user_id}/recurring-items",
        headers=headers,
        json=recurring_payload(),
    )

    assert first.status_code == 201

    duplicate = client.post(
        f"/users/{user_id}/recurring-items",
        headers=headers,
        json=recurring_payload(),
    )

    assert duplicate.status_code == 409
    assert (
        duplicate.json()["detail"]
        == "recurring item already exists"
    )


def test_delete_recurring_item(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client,
        "recurring-delete",
    )

    created = client.post(
        f"/users/{user_id}/recurring-items",
        headers=headers,
        json=recurring_payload(),
    )

    item_id = created.json()["id"]

    deleted = client.delete(
        f"/users/{user_id}/recurring-items/{item_id}",
        headers=headers,
    )

    assert deleted.status_code == 204

    items = client.get(
        f"/users/{user_id}/recurring-items",
        headers=headers,
    )

    assert items.status_code == 200
    assert items.json() == []


def test_recurring_routes_require_authentication(
    client: TestClient,
) -> None:
    response = client.get(
        "/users/1/recurring-items",
    )

    assert response.status_code == 401


def test_cross_user_recurring_access_rejected(
    client: TestClient,
) -> None:
    first_user_id, first_headers = register_and_login(
        client,
        "recurring-first",
    )

    second_user_id, _ = register_and_login(
        client,
        "recurring-second",
    )

    assert first_user_id != second_user_id

    response = client.get(
        f"/users/{second_user_id}/recurring-items",
        headers=first_headers,
    )

    assert response.status_code == 403


def test_other_user_cannot_update_recurring_item(
    client: TestClient,
) -> None:
    owner_id, owner_headers = register_and_login(
        client,
        "recurring-owner",
    )

    _, attacker_headers = register_and_login(
        client,
        "recurring-attacker",
    )

    created = client.post(
        f"/users/{owner_id}/recurring-items",
        headers=owner_headers,
        json=recurring_payload(),
    )

    item_id = created.json()["id"]

    response = client.patch(
        f"/users/{owner_id}/recurring-items/{item_id}",
        headers=attacker_headers,
        json={
            "status": "cancelled",
        },
    )

    assert response.status_code == 403