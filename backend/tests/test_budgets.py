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


def test_cross_user_budget_mutations_and_progress_rejected(
    client: TestClient,
) -> None:
    owner_id, _ = register_and_login(client, "budget-owner")
    _, attacker_headers = register_and_login(client, "budget-attacker")

    responses = [
        client.put(
            f"/users/{owner_id}/budgets",
            headers=attacker_headers,
            json={
                "category": "Dining",
                "month": "2026-08",
                "limit_cents": 30000,
            },
        ),
        client.post(
            f"/users/{owner_id}/budgets/copy",
            headers=attacker_headers,
            json={
                "source_month": "2026-07",
                "target_month": "2026-08",
            },
        ),
        client.get(
            f"/users/{owner_id}/budgets/progress?month=2026-08",
            headers=attacker_headers,
        ),
    ]

    assert [response.status_code for response in responses] == [
        403,
        403,
        403,
    ]


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
            "overspent": False,
        }
    ]


def test_budget_progress_reports_overspending(
    client: TestClient,
) -> None:
    from datetime import date

    from app.models import Transaction
    from tests.conftest import TestingSessionLocal

    user_id, headers = register_and_login(
        client,
        "budget-overspent",
    )

    client.put(
        f"/users/{user_id}/budgets",
        headers=headers,
        json={
            "category": "Dining",
            "month": "2026-07",
            "limit_cents": 10000,
        },
    )

    with TestingSessionLocal() as db:
        db.add(
            Transaction(
                user_id=user_id,
                posted_on=date(2026, 7, 31),
                description="Dinner",
                amount_cents=-12500,
                category="Dining",
            )
        )
        db.commit()

    response = client.get(
        f"/users/{user_id}/budgets/progress?month=2026-07",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()[0] == {
        "category": "Dining",
        "month": "2026-07",
        "limit_cents": 10000,
        "spent_cents": 12500,
        "remaining_cents": -2500,
        "percent_used": 125.0,
        "over_budget_cents": 2500,
        "overspent": True,
    }


def test_delete_budget_only_removes_selected_month(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "budget-delete")

    for month in ["2026-07", "2026-08"]:
        response = client.put(
            f"/users/{user_id}/budgets",
            headers=headers,
            json={
                "category": "Dining",
                "month": month,
                "limit_cents": 30000,
            },
        )
        assert response.status_code == 200

    deleted = client.delete(
        f"/users/{user_id}/budgets/Dining",
        params={"month": "2026-08"},
        headers=headers,
    )

    assert deleted.status_code == 204
    assert client.get(
        f"/users/{user_id}/budgets?month=2026-08",
        headers=headers,
    ).json() == []
    assert len(
        client.get(
            f"/users/{user_id}/budgets?month=2026-07",
            headers=headers,
        ).json()
    ) == 1


def test_delete_budget_rejects_cross_user_access(
    client: TestClient,
) -> None:
    owner_id, _ = register_and_login(client, "budget-delete-owner")
    _, attacker_headers = register_and_login(
        client,
        "budget-delete-attacker",
    )

    response = client.delete(
        f"/users/{owner_id}/budgets/Dining",
        params={"month": "2026-08"},
        headers=attacker_headers,
    )

    assert response.status_code == 403


def test_copy_previous_month_budgets(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "budget-copy")

    for category, limit_cents in [
        ("Dining", 30000),
        ("Groceries", 50000),
    ]:
        response = client.put(
            f"/users/{user_id}/budgets",
            headers=headers,
            json={
                "category": category,
                "month": "2026-07",
                "limit_cents": limit_cents,
            },
        )
        assert response.status_code == 200

    response = client.post(
        f"/users/{user_id}/budgets/copy-previous",
        params={"month": "2026-08"},
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_month"] == "2026-07"
    assert body["target_month"] == "2026-08"
    assert body["copied"] == 2
    assert body["updated"] == 0
    assert body["skipped"] == 0
    assert [
        (item["category"], item["limit_cents"])
        for item in body["budgets"]
    ] == [("Dining", 30000), ("Groceries", 50000)]


def test_copy_budgets_between_selected_months(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client,
        "budget-copy-selected",
    )

    saved = client.put(
        f"/users/{user_id}/budgets",
        headers=headers,
        json={
            "category": "Utilities",
            "month": "2026-03",
            "limit_cents": 22500,
        },
    )
    assert saved.status_code == 200

    response = client.post(
        f"/users/{user_id}/budgets/copy",
        headers=headers,
        json={
            "source_month": "2026-03",
            "target_month": "2026-08",
        },
    )

    assert response.status_code == 200
    assert response.json()["source_month"] == "2026-03"
    assert response.json()["target_month"] == "2026-08"
    assert response.json()["copied"] == 1
    assert response.json()["budgets"][0]["month"] == "2026-08"


def test_copy_budgets_rejects_same_month(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client,
        "budget-copy-same",
    )

    response = client.post(
        f"/users/{user_id}/budgets/copy",
        headers=headers,
        json={
            "source_month": "2026-08",
            "target_month": "2026-08",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "source and target months must differ"
    )


def test_copy_previous_month_preserves_existing_by_default(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client,
        "budget-copy-preserve",
    )

    for month, limit_cents in [
        ("2026-07", 30000),
        ("2026-08", 45000),
    ]:
        response = client.put(
            f"/users/{user_id}/budgets",
            headers=headers,
            json={
                "category": "Dining",
                "month": month,
                "limit_cents": limit_cents,
            },
        )
        assert response.status_code == 200

    response = client.post(
        f"/users/{user_id}/budgets/copy-previous",
        params={"month": "2026-08"},
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["copied"] == 0
    assert body["updated"] == 0
    assert body["skipped"] == 1
    assert body["budgets"][0]["limit_cents"] == 45000


def test_copy_previous_month_can_overwrite_existing(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client,
        "budget-copy-overwrite",
    )

    for month, limit_cents in [
        ("2026-07", 30000),
        ("2026-08", 45000),
    ]:
        response = client.put(
            f"/users/{user_id}/budgets",
            headers=headers,
            json={
                "category": "Dining",
                "month": month,
                "limit_cents": limit_cents,
            },
        )
        assert response.status_code == 200

    response = client.post(
        f"/users/{user_id}/budgets/copy-previous",
        params={"month": "2026-08", "overwrite": "true"},
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["copied"] == 0
    assert body["updated"] == 1
    assert body["skipped"] == 0
    assert body["budgets"][0]["limit_cents"] == 30000


def test_copy_previous_month_returns_404_when_source_empty(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client,
        "budget-copy-empty",
    )

    response = client.post(
        f"/users/{user_id}/budgets/copy-previous",
        params={"month": "2026-08"},
        headers=headers,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "no budgets found for 2026-07"
