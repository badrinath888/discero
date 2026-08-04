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


def create_goal(
    client: TestClient,
    user_id: int,
    headers: dict[str, str],
    *,
    name: str = "Emergency Fund",
    target_cents: int = 1_000_000,
    saved_cents: int = 0,
    target_date: str | None = None,
) -> dict:
    payload: dict[str, object] = {
        "name": name,
        "target_cents": target_cents,
        "saved_cents": saved_cents,
    }

    if target_date is not None:
        payload["target_date"] = target_date

    response = client.post(
        f"/users/{user_id}/goals",
        headers=headers,
        json=payload,
    )

    assert response.status_code == 201
    return response.json()


def get_goal(
    client: TestClient,
    user_id: int,
    headers: dict[str, str],
    goal_id: int,
) -> dict:
    response = client.get(
        f"/users/{user_id}/goals",
        headers=headers,
    )

    assert response.status_code == 200

    return next(
        goal
        for goal in response.json()
        if goal["id"] == goal_id
    )


def test_create_and_list_savings_goal(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client,
        "goal-create",
    )

    goal = create_goal(
        client,
        user_id,
        headers,
        saved_cents=250_000,
        target_date="2027-12-31",
    )

    assert goal["name"] == "Emergency Fund"
    assert goal["target_cents"] == 1_000_000
    assert goal["saved_cents"] == 250_000
    assert goal["remaining_cents"] == 750_000
    assert goal["progress_percent"] == 25.0
    assert goal["status"] == "active"

    response = client.get(
        f"/users/{user_id}/goals",
        headers=headers,
    )

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_initial_saved_amount_creates_opening_balance(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client,
        "goal-opening",
    )

    goal = create_goal(
        client,
        user_id,
        headers,
        saved_cents=125_000,
    )

    response = client.get(
        (
            f"/users/{user_id}/goals/"
            f"{goal['id']}/contributions"
        ),
        headers=headers,
    )

    assert response.status_code == 200

    contributions = response.json()

    assert len(contributions) == 1
    assert contributions[0]["amount_cents"] == 125_000
    assert contributions[0]["contribution_type"] == "deposit"
    assert contributions[0]["note"] == "Opening balance"


def test_update_savings_goal_details(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client,
        "goal-update",
    )

    goal = create_goal(
        client,
        user_id,
        headers,
        name="Vacation",
        target_cents=300_000,
        saved_cents=50_000,
    )

    response = client.patch(
        f"/users/{user_id}/goals/{goal['id']}",
        headers=headers,
        json={
            "name": "Europe Vacation",
            "target_cents": 400_000,
            "target_date": "2027-06-30",
        },
    )

    assert response.status_code == 200

    updated = response.json()

    assert updated["name"] == "Europe Vacation"
    assert updated["target_cents"] == 400_000
    assert updated["saved_cents"] == 50_000
    assert updated["remaining_cents"] == 350_000
    assert updated["target_date"] == "2027-06-30"


def test_create_deposit_updates_goal_balance(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client,
        "goal-deposit",
    )

    goal = create_goal(
        client,
        user_id,
        headers,
        target_cents=500_000,
    )

    response = client.post(
        (
            f"/users/{user_id}/goals/"
            f"{goal['id']}/contributions"
        ),
        headers=headers,
        json={
            "amount_cents": 75_000,
            "contribution_type": "deposit",
            "contributed_on": "2026-08-04",
            "note": "Monthly savings",
        },
    )

    assert response.status_code == 201

    contribution = response.json()

    assert contribution["amount_cents"] == 75_000
    assert contribution["contribution_type"] == "deposit"
    assert contribution["note"] == "Monthly savings"

    updated_goal = get_goal(
        client,
        user_id,
        headers,
        goal["id"],
    )

    assert updated_goal["saved_cents"] == 75_000
    assert updated_goal["remaining_cents"] == 425_000
    assert updated_goal["progress_percent"] == 15.0


def test_create_withdrawal_updates_goal_balance(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client,
        "goal-withdrawal",
    )

    goal = create_goal(
        client,
        user_id,
        headers,
        saved_cents=200_000,
    )

    response = client.post(
        (
            f"/users/{user_id}/goals/"
            f"{goal['id']}/contributions"
        ),
        headers=headers,
        json={
            "amount_cents": 50_000,
            "contribution_type": "withdrawal",
            "note": "Emergency expense",
        },
    )

    assert response.status_code == 201

    updated_goal = get_goal(
        client,
        user_id,
        headers,
        goal["id"],
    )

    assert updated_goal["saved_cents"] == 150_000


def test_withdrawal_cannot_exceed_saved_balance(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client,
        "goal-withdrawal-limit",
    )

    goal = create_goal(
        client,
        user_id,
        headers,
        saved_cents=25_000,
    )

    response = client.post(
        (
            f"/users/{user_id}/goals/"
            f"{goal['id']}/contributions"
        ),
        headers=headers,
        json={
            "amount_cents": 30_000,
            "contribution_type": "withdrawal",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "withdrawal cannot exceed the amount currently saved"
    )

    unchanged_goal = get_goal(
        client,
        user_id,
        headers,
        goal["id"],
    )

    assert unchanged_goal["saved_cents"] == 25_000


def test_list_contributions_newest_first(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client,
        "goal-history",
    )

    goal = create_goal(
        client,
        user_id,
        headers,
    )

    entries = (
        (10_000, "2026-06-01"),
        (20_000, "2026-08-01"),
        (15_000, "2026-07-01"),
    )

    for amount, contributed_on in entries:
        response = client.post(
            (
                f"/users/{user_id}/goals/"
                f"{goal['id']}/contributions"
            ),
            headers=headers,
            json={
                "amount_cents": amount,
                "contribution_type": "deposit",
                "contributed_on": contributed_on,
            },
        )

        assert response.status_code == 201

    response = client.get(
        (
            f"/users/{user_id}/goals/"
            f"{goal['id']}/contributions"
        ),
        headers=headers,
    )

    assert response.status_code == 200
    assert [
        item["contributed_on"]
        for item in response.json()
    ] == [
        "2026-08-01",
        "2026-07-01",
        "2026-06-01",
    ]


def test_update_contribution_recalculates_balance(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client,
        "goal-edit-contribution",
    )

    goal = create_goal(
        client,
        user_id,
        headers,
    )

    created = client.post(
        (
            f"/users/{user_id}/goals/"
            f"{goal['id']}/contributions"
        ),
        headers=headers,
        json={
            "amount_cents": 50_000,
            "contribution_type": "deposit",
            "note": "First amount",
        },
    )

    assert created.status_code == 201

    contribution_id = created.json()["id"]

    response = client.patch(
        (
            f"/users/{user_id}/goals/"
            f"{goal['id']}/contributions/"
            f"{contribution_id}"
        ),
        headers=headers,
        json={
            "amount_cents": 80_000,
            "note": "Corrected amount",
        },
    )

    assert response.status_code == 200
    assert response.json()["amount_cents"] == 80_000
    assert response.json()["note"] == "Corrected amount"

    updated_goal = get_goal(
        client,
        user_id,
        headers,
        goal["id"],
    )

    assert updated_goal["saved_cents"] == 80_000


def test_update_contribution_cannot_make_balance_negative(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client,
        "goal-edit-negative",
    )

    goal = create_goal(
        client,
        user_id,
        headers,
        saved_cents=50_000,
    )

    history = client.get(
        (
            f"/users/{user_id}/goals/"
            f"{goal['id']}/contributions"
        ),
        headers=headers,
    )

    assert history.status_code == 200

    contribution_id = history.json()[0]["id"]

    response = client.patch(
        (
            f"/users/{user_id}/goals/"
            f"{goal['id']}/contributions/"
            f"{contribution_id}"
        ),
        headers=headers,
        json={
            "contribution_type": "withdrawal",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "contribution change would make the goal balance negative"
    )


def test_delete_contribution_recalculates_balance(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client,
        "goal-delete-contribution",
    )

    goal = create_goal(
        client,
        user_id,
        headers,
    )

    first = client.post(
        (
            f"/users/{user_id}/goals/"
            f"{goal['id']}/contributions"
        ),
        headers=headers,
        json={
            "amount_cents": 100_000,
            "contribution_type": "deposit",
        },
    )

    second = client.post(
        (
            f"/users/{user_id}/goals/"
            f"{goal['id']}/contributions"
        ),
        headers=headers,
        json={
            "amount_cents": 40_000,
            "contribution_type": "deposit",
        },
    )

    assert first.status_code == 201
    assert second.status_code == 201

    response = client.delete(
        (
            f"/users/{user_id}/goals/"
            f"{goal['id']}/contributions/"
            f"{second.json()['id']}"
        ),
        headers=headers,
    )

    assert response.status_code == 204

    updated_goal = get_goal(
        client,
        user_id,
        headers,
        goal["id"],
    )

    assert updated_goal["saved_cents"] == 100_000


def test_deleting_deposit_cannot_make_balance_negative(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client,
        "goal-delete-negative",
    )

    goal = create_goal(
        client,
        user_id,
        headers,
    )

    deposit = client.post(
        (
            f"/users/{user_id}/goals/"
            f"{goal['id']}/contributions"
        ),
        headers=headers,
        json={
            "amount_cents": 100_000,
            "contribution_type": "deposit",
        },
    )

    withdrawal = client.post(
        (
            f"/users/{user_id}/goals/"
            f"{goal['id']}/contributions"
        ),
        headers=headers,
        json={
            "amount_cents": 60_000,
            "contribution_type": "withdrawal",
        },
    )

    assert deposit.status_code == 201
    assert withdrawal.status_code == 201

    response = client.delete(
        (
            f"/users/{user_id}/goals/"
            f"{goal['id']}/contributions/"
            f"{deposit.json()['id']}"
        ),
        headers=headers,
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "deleting this contribution would make the goal balance negative"
    )


def test_completed_goal_status(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client,
        "goal-completed",
    )

    goal = create_goal(
        client,
        user_id,
        headers,
        name="Laptop",
        target_cents=200_000,
        saved_cents=200_000,
    )

    assert goal["status"] == "completed"
    assert goal["remaining_cents"] == 0
    assert goal["progress_percent"] == 100.0


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

    goal = create_goal(
        client,
        user_id,
        headers,
        name="Old Goal",
        target_cents=500_000,
        saved_cents=100_000,
        target_date=past_date,
    )

    assert goal["status"] == "overdue"


def test_delete_savings_goal(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client,
        "goal-delete",
    )

    goal = create_goal(
        client,
        user_id,
        headers,
        name="New Car",
        target_cents=2_500_000,
        saved_cents=100_000,
    )

    response = client.delete(
        f"/users/{user_id}/goals/{goal['id']}",
        headers=headers,
    )

    assert response.status_code == 204

    goals = client.get(
        f"/users/{user_id}/goals",
        headers=headers,
    )

    assert goals.status_code == 200
    assert goals.json() == []


def test_goal_routes_require_authentication(
    client: TestClient,
) -> None:
    goals_response = client.get("/users/1/goals")
    contributions_response = client.get(
        "/users/1/goals/1/contributions"
    )

    assert goals_response.status_code == 401
    assert contributions_response.status_code == 401


def test_cross_user_goal_access_rejected(
    client: TestClient,
) -> None:
    first_user_id, first_headers = register_and_login(
        client,
        "goal-first",
    )

    second_user_id, second_headers = register_and_login(
        client,
        "goal-second",
    )

    goal = create_goal(
        client,
        second_user_id,
        second_headers,
    )

    goal_response = client.get(
        f"/users/{second_user_id}/goals",
        headers=first_headers,
    )

    contribution_response = client.get(
        (
            f"/users/{second_user_id}/goals/"
            f"{goal['id']}/contributions"
        ),
        headers=first_headers,
    )

    assert first_user_id != second_user_id
    assert goal_response.status_code == 403
    assert contribution_response.status_code == 403


def test_unknown_goal_and_contribution_return_not_found(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client,
        "goal-not-found",
    )

    goal = create_goal(
        client,
        user_id,
        headers,
    )

    missing_goal = client.get(
        f"/users/{user_id}/goals/999999/contributions",
        headers=headers,
    )

    missing_contribution = client.patch(
        (
            f"/users/{user_id}/goals/"
            f"{goal['id']}/contributions/999999"
        ),
        headers=headers,
        json={
            "amount_cents": 10_000,
        },
    )

    assert missing_goal.status_code == 404
    assert missing_contribution.status_code == 404