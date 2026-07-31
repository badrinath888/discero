from datetime import date, timedelta
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


def test_create_and_list_savings_goal(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client,
        "goal-create",
    )

    response = client.post(
        f"/users/{user_id}/goals",
        headers=headers,
        json={
            "name": "Emergency Fund",
            "target_cents": 1000000,
            "saved_cents": 250000,
            "target_date": "2027-12-31",
        },
    )

    assert response.status_code == 201

    body = response.json()

    assert body["name"] == "Emergency Fund"
    assert body["target_cents"] == 1000000
    assert body["saved_cents"] == 250000
    assert body["remaining_cents"] == 750000
    assert body["progress_percent"] == 25.0
    assert body["status"] == "active"

    list_response = client.get(
        f"/users/{user_id}/goals",
        headers=headers,
    )

    assert list_response.status_code == 200
    assert len(list_response.json()) == 1


def test_update_savings_goal(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client,
        "goal-update",
    )

    created = client.post(
        f"/users/{user_id}/goals",
        headers=headers,
        json={
            "name": "Vacation",
            "target_cents": 300000,
            "saved_cents": 50000,
        },
    )

    goal_id = created.json()["id"]

    updated = client.patch(
        f"/users/{user_id}/goals/{goal_id}",
        headers=headers,
        json={
            "saved_cents": 150000,
        },
    )

    assert updated.status_code == 200
    assert updated.json()["saved_cents"] == 150000
    assert updated.json()["remaining_cents"] == 150000
    assert updated.json()["progress_percent"] == 50.0


def test_completed_goal_status(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client,
        "goal-completed",
    )

    response = client.post(
        f"/users/{user_id}/goals",
        headers=headers,
        json={
            "name": "Laptop",
            "target_cents": 200000,
            "saved_cents": 200000,
        },
    )

    assert response.status_code == 201
    assert response.json()["status"] == "completed"
    assert response.json()["remaining_cents"] == 0
    assert response.json()["progress_percent"] == 100.0


def test_overdue_goal_status(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client,
        "goal-overdue",
    )

    past_date = (
        date.today() - timedelta(days=1)
    ).isoformat()

    response = client.post(
        f"/users/{user_id}/goals",
        headers=headers,
        json={
            "name": "Old Goal",
            "target_cents": 500000,
            "saved_cents": 100000,
            "target_date": past_date,
        },
    )

    assert response.status_code == 201
    assert response.json()["status"] == "overdue"


def test_delete_savings_goal(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client,
        "goal-delete",
    )

    created = client.post(
        f"/users/{user_id}/goals",
        headers=headers,
        json={
            "name": "New Car",
            "target_cents": 2500000,
        },
    )

    goal_id = created.json()["id"]

    deleted = client.delete(
        f"/users/{user_id}/goals/{goal_id}",
        headers=headers,
    )

    assert deleted.status_code == 204

    goals = client.get(
        f"/users/{user_id}/goals",
        headers=headers,
    )

    assert goals.status_code == 200
    assert goals.json() == []


def test_goal_routes_require_authentication(
    client: TestClient,
) -> None:
    response = client.get("/users/1/goals")

    assert response.status_code == 401


def test_cross_user_goal_access_rejected(
    client: TestClient,
) -> None:
    first_user_id, first_headers = register_and_login(
        client,
        "goal-first",
    )

    second_user_id, _ = register_and_login(
        client,
        "goal-second",
    )

    assert first_user_id != second_user_id

    response = client.get(
        f"/users/{second_user_id}/goals",
        headers=first_headers,
    )

    assert response.status_code == 403
