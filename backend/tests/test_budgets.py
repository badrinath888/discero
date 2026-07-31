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


def test_save_and_list_budget_by_month(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client,
        "budget-month",
    )

    july_response = client.put(
        f"/users/{user_id}/budgets",
        headers=headers,
        json={
            "category": "Dining",
            "month": "2026-07",
            "limit_cents": 30000,
        },
    )

    august_response = client.put(
        f"/users/{user_id}/budgets",
        headers=headers,
        json={
            "category": "Dining",
            "month": "2026-08",
            "limit_cents": 45000,
        },
    )

    assert july_response.status_code == 200
    assert august_response.status_code == 200

    july_budgets = client.get(
        f"/users/{user_id}/budgets?month=2026-07",
        headers=headers,
    )

    august_budgets = client.get(
        f"/users/{user_id}/budgets?month=2026-08",
        headers=headers,
    )

    assert july_budgets.status_code == 200
    assert august_budgets.status_code == 200

    assert july_budgets.json() == [
        {
            "id": july_response.json()["id"],
            "category": "Dining",
            "month": "2026-07",
            "limit_cents": 30000,
        }
    ]

    assert august_budgets.json() == [
        {
            "id": august_response.json()["id"],
            "category": "Dining",
            "month": "2026-08",
            "limit_cents": 45000,
        }
    ]


def test_update_existing_budget_for_same_month(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client,
        "budget-update",
    )

    first = client.put(
        f"/users/{user_id}/budgets",
        headers=headers,
        json={
            "category": "Groceries",
            "month": "2026-07",
            "limit_cents": 40000,
        },
    )

    updated = client.put(
        f"/users/{user_id}/budgets",
        headers=headers,
        json={
            "category": "Groceries",
            "month": "2026-07",
            "limit_cents": 55000,
        },
    )

    assert first.status_code == 200
    assert updated.status_code == 200
    assert updated.json()["id"] == first.json()["id"]
    assert updated.json()["limit_cents"] == 55000


def test_reject_invalid_budget_month(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client,
        "budget-invalid",
    )

    response = client.put(
        f"/users/{user_id}/budgets",
        headers=headers,
        json={
            "category": "Housing",
            "month": "2026-13",
            "limit_cents": 100000,
        },
    )

    assert response.status_code == 422


def test_budget_routes_require_authentication(
    client: TestClient,
) -> None:
    response = client.get(
        "/users/1/budgets?month=2026-07"
    )

    assert response.status_code == 401


def test_cross_user_budget_access_rejected(
    client: TestClient,
) -> None:
    first_user_id, first_headers = register_and_login(
        client,
        "budget-first",
    )

    second_user_id, _ = register_and_login(
        client,
        "budget-second",
    )

    assert first_user_id != second_user_id

    response = client.get(
        f"/users/{second_user_id}/budgets?month=2026-07",
        headers=first_headers,
    )

    assert response.status_code == 403

def test_budget_progress_calculates_monthly_spending(
    client: TestClient,
) -> None:
    from datetime import date

    from app.models import Transaction
    from tests.conftest import TestingSessionLocal

    user_id, headers = register_and_login(
        client,
        "budget-progress",
    )

    client.put(
        f"/users/{user_id}/budgets",
        headers=headers,
        json={
            "category": "Dining",
            "month": "2026-07",
            "limit_cents": 30000,
        },
    )

    with TestingSessionLocal() as db:
        db.add_all(
            [
                Transaction(
                    user_id=user_id,
                    posted_on=date(2026, 7, 10),
                    description="Restaurant",
                    amount_cents=-12000,
                    category="Dining",
                ),
                Transaction(
                    user_id=user_id,
                    posted_on=date(2026, 7, 20),
                    description="Coffee",
                    amount_cents=-3000,
                    category="Dining",
                ),
                Transaction(
                    user_id=user_id,
                    posted_on=date(2026, 8, 1),
                    description="August meal",
                    amount_cents=-5000,
                    category="Dining",
                ),
            ]
        )
        db.commit()

    response = client.get(
        f"/users/{user_id}/budgets/progress?month=2026-07",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "category": "Dining",
            "month": "2026-07",
            "limit_cents": 30000,
            "spent_cents": 15000,
            "remaining_cents": 15000,
            "percent_used": 50.0,
            "over_budget_cents": 0,
        }
    ]
