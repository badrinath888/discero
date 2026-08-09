from datetime import date
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import SavingsGoal, User
from app.services.goal_intelligence_service import (
    calculate_feasible_target_date,
    evaluate_goal_intelligence,
)
from tests.conftest import TestingSessionLocal


TEST_DATE = date(2026, 8, 8)


def create_user(db: Session) -> User:
    user = User(
        email=f"goal-intel-{uuid4().hex}@example.com",
        password_hash="test-password-hash",
        email_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_goal(
    db: Session,
    user: User,
    *,
    name: str,
    target_cents: int,
    saved_cents: int = 0,
    target_date: date | None = None,
) -> SavingsGoal:
    goal = SavingsGoal(
        user_id=user.id,
        name=name,
        target_cents=target_cents,
        saved_cents=saved_cents,
        target_date=target_date,
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return goal


def register_and_login(client: TestClient, prefix: str) -> tuple[int, dict]:
    email = f"{prefix}-{uuid4().hex}@example.com"
    password = "TestPassword123!"

    create_response = client.post(
        "/users", json={"email": email, "password": password}
    )
    assert create_response.status_code == 201

    login_response = client.post(
        "/users/login", json={"email": email, "password": password}
    )
    assert login_response.status_code == 200

    return create_response.json()["id"], {
        "Authorization": f"Bearer {login_response.json()['access_token']}"
    }


def test_on_track_goal() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_goal(
            db,
            user,
            name="Vacation",
            target_cents=120_000,
            saved_cents=0,
            target_date=date(2026, 10, 8),
        )

        result = evaluate_goal_intelligence(
            db, user.id, monthly_capacity_cents=100_000, as_of=TEST_DATE
        )

        goal = result.goals[0]
        assert goal.months_remaining == 2
        assert goal.required_monthly_cents == 60_000
        assert goal.allocated_monthly_cents == 60_000
        assert goal.monthly_gap_cents == 0
        assert goal.status == "on_track"
        assert goal.suggested_feasible_target_date is None
        assert result.conflict_status == "no_conflict"


def test_at_risk_single_goal_not_labeled_conflict() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_goal(
            db,
            user,
            name="Laptop fund",
            target_cents=200_000,
            saved_cents=0,
            target_date=date(2026, 10, 8),
        )

        result = evaluate_goal_intelligence(
            db, user.id, monthly_capacity_cents=70_000, as_of=TEST_DATE
        )

        goal = result.goals[0]
        assert goal.months_remaining == 2
        assert goal.required_monthly_cents == 100_000
        assert goal.allocated_monthly_cents == 70_000
        assert goal.monthly_gap_cents == 30_000
        # Only one goal is involved -- this is a tight timeline, not a
        # competing-goals conflict.
        assert goal.status == "at_risk"
        assert goal.urgency_rank == 1
        # remaining 200_000 / allocated 70_000 -> ceil = 3 months out.
        assert goal.projected_completion_date == date(2026, 11, 8)
        assert goal.suggested_feasible_target_date == date(2026, 11, 8)


def test_completed_goal() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_goal(
            db,
            user,
            name="Emergency fund",
            target_cents=100_000,
            saved_cents=100_000,
            target_date=date(2026, 12, 1),
        )

        result = evaluate_goal_intelligence(
            db, user.id, monthly_capacity_cents=50_000, as_of=TEST_DATE
        )

        goal = result.goals[0]
        assert goal.status == "completed"
        assert goal.urgency_rank is None
        assert goal.monthly_gap_cents == 0
        assert goal.projected_completion_date == TEST_DATE


def test_past_due_active_goal() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_goal(
            db,
            user,
            name="Overdue goal",
            target_cents=100_000,
            saved_cents=50_000,
            target_date=date(2026, 7, 1),
        )

        result = evaluate_goal_intelligence(
            db, user.id, monthly_capacity_cents=0, as_of=TEST_DATE
        )

        goal = result.goals[0]
        assert goal.months_remaining == 0
        assert goal.remaining_amount_cents == 50_000
        # Past due with no time left -> the full remainder is "required"
        # this instant.
        assert goal.required_monthly_cents == 50_000
        assert goal.allocated_monthly_cents == 0
        assert goal.monthly_gap_cents == 50_000
        assert goal.status == "at_risk"


def test_zero_monthly_capacity_explicit() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_goal(
            db,
            user,
            name="Goal",
            target_cents=60_000,
            saved_cents=0,
            target_date=date(2026, 10, 8),
        )

        result = evaluate_goal_intelligence(
            db, user.id, monthly_capacity_cents=0, as_of=TEST_DATE
        )

        assert result.total_capacity_cents == 0
        goal = result.goals[0]
        assert goal.allocated_monthly_cents == 0
        assert goal.monthly_gap_cents == 30_000


def test_multiple_goals_total_shortfall_and_largest_contributor() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        # Nearest deadline, allocated first.
        create_goal(
            db,
            user,
            name="Near goal",
            target_cents=100_000,
            saved_cents=0,
            target_date=date(2026, 9, 8),
        )
        # Further out, allocated second.
        create_goal(
            db,
            user,
            name="Far goal",
            target_cents=300_000,
            saved_cents=0,
            target_date=date(2026, 11, 8),
        )

        result = evaluate_goal_intelligence(
            db, user.id, monthly_capacity_cents=50_000, as_of=TEST_DATE
        )

        assert result.total_required_cents == 200_000
        assert result.total_shortfall_cents == 150_000
        assert result.conflict_status == "conflict"

        by_name = {g.name: g for g in result.goals}
        near = by_name["Near goal"]
        far = by_name["Far goal"]

        # Nearest-deadline goal is funded first (existing allocation
        # strategy, reused unmodified).
        assert near.allocated_monthly_cents == 50_000
        assert near.monthly_gap_cents == 50_000
        assert far.allocated_monthly_cents == 0
        assert far.monthly_gap_cents == 100_000

        # Both are underfunded together -> genuine multi-goal conflict.
        assert near.status == "conflict"
        assert far.status == "conflict"

        # Far goal has the larger shortfall -> largest pressure.
        assert result.largest_pressure_goal_id == far.goal_id

        # Nearest deadline still ranked most urgent regardless of size.
        assert near.urgency_rank == 1
        assert far.urgency_rank == 2

        assert any("$1,500.00" in s for s in result.suggestions)


def test_feasible_target_date_zero_and_completed_edge_cases() -> None:
    assert (
        calculate_feasible_target_date(0, 50_000, TEST_DATE) == TEST_DATE
    )
    assert (
        calculate_feasible_target_date(-100, 50_000, TEST_DATE)
        == TEST_DATE
    )
    assert calculate_feasible_target_date(50_000, 0, TEST_DATE) is None
    assert (
        calculate_feasible_target_date(50_000, -100, TEST_DATE) is None
    )


def test_feasible_target_date_rounding() -> None:
    # 1 cent remaining still needs a full extra month at any pace.
    assert calculate_feasible_target_date(1, 100_000, TEST_DATE) == date(
        2026, 9, 8
    )
    # Exact multiple: 200_000 / 100_000 = 2 months exactly.
    assert calculate_feasible_target_date(
        200_000, 100_000, TEST_DATE
    ) == date(2026, 10, 8)
    # Day-of-month clamping across a short month.
    assert calculate_feasible_target_date(
        1, 100_000, date(2026, 1, 31)
    ) == date(2026, 2, 28)


def test_goal_intelligence_endpoint_requires_authentication(
    client: TestClient,
) -> None:
    response = client.get("/users/9999/goals/intelligence")
    assert response.status_code == 401


def test_goal_intelligence_endpoint_blocks_other_user(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "goal-intel-owner")

    response = client.get(
        f"/users/{user_id + 1}/goals/intelligence", headers=headers
    )

    assert response.status_code == 403


def test_goal_intelligence_endpoint_returns_real_data(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "goal-intel-endpoint")

    response = client.get(
        f"/users/{user_id}/goals/intelligence"
        "?monthly_capacity_cents=50000",
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_capacity_cents"] == 50_000
    assert body["goals"] == []
