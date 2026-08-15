from datetime import date, datetime, timezone
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
    created_at: date | None = None,
) -> SavingsGoal:
    goal = SavingsGoal(
        user_id=user.id,
        name=name,
        target_cents=target_cents,
        saved_cents=saved_cents,
        target_date=target_date,
    )
    if created_at is not None:
        goal.created_at = datetime(
            created_at.year,
            created_at.month,
            created_at.day,
            tzinfo=timezone.utc,
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
        # Target date has already passed -- no future contribution
        # schedule can retroactively fix this, so it's "not_feasible"
        # rather than a merely tight "at_risk" timeline.
        assert goal.status == "not_feasible"
        assert goal.key_driver == "target_date_passed"


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


def test_projected_delay_months_when_underfunded() -> None:
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
        # target 2026-10-08, projected completion 2026-11-08 -> 1 month late.
        assert goal.projected_completion_date == date(2026, 11, 8)
        assert goal.projected_delay_months == 1


def test_projected_delay_months_zero_when_on_track() -> None:
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
        assert goal.projected_delay_months == 0


def test_projected_delay_months_none_when_completely_unfunded() -> None:
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

        goal = result.goals[0]
        assert goal.projected_completion_date is None
        assert goal.projected_delay_months is None


def test_projected_delay_months_none_without_target_date() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_goal(
            db,
            user,
            name="Someday goal",
            target_cents=60_000,
            saved_cents=0,
            target_date=None,
        )

        result = evaluate_goal_intelligence(
            db, user.id, monthly_capacity_cents=50_000, as_of=TEST_DATE
        )

        goal = result.goals[0]
        assert goal.projected_delay_months is None


def test_headroom_key_driver_and_recommendation_pass_through() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_goal(
            db,
            user,
            name="Near goal",
            target_cents=100_000,
            saved_cents=0,
            target_date=date(2026, 9, 8),
        )
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

        assert result.key_driver == "largest_required_goal"
        assert result.monthly_headroom_cents == 0
        assert result.recommendation.type == "increase_monthly_capacity"
        assert result.recommendation.amount_cents == 150_000


def test_no_conflict_recommendation_is_no_change_needed() -> None:
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

        assert result.key_driver == "no_conflict"
        assert result.monthly_headroom_cents == 40_000
        assert result.recommendation.type == "no_change_needed"
        assert result.recommendation_alternatives == []


def test_ahead_status_when_saved_beats_original_pace() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        # Created 6 months before TEST_DATE with a 12-month original
        # runway (created_at -> target_date): an even pace would need
        # $1,000/month and $6,000 banked by now. $7,500 saved is a
        # full month ahead of that original pace.
        create_goal(
            db,
            user,
            name="Ahead fund",
            target_cents=1_200_000,
            saved_cents=750_000,
            target_date=date(2027, 2, 8),
            created_at=date(2026, 2, 8),
        )

        result = evaluate_goal_intelligence(
            db, user.id, monthly_capacity_cents=75_000, as_of=TEST_DATE
        )

        goal = result.goals[0]
        assert goal.months_remaining == 6
        assert goal.required_monthly_cents == 75_000
        assert goal.allocated_monthly_cents == 75_000
        assert goal.monthly_gap_cents == 0
        assert goal.status == "ahead"
        assert goal.key_driver == "ahead_of_schedule"
        assert goal.recommended_action.type == "no_change_needed"
        assert goal.alternative_actions == []


def test_on_track_goal_not_marked_ahead_without_original_pace_surplus() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        # Same shape as the "ahead" case, but saved only exactly what
        # the original even pace would have banked by now -- no
        # material surplus, so it stays plain "on_track".
        create_goal(
            db,
            user,
            name="On-pace fund",
            target_cents=1_200_000,
            saved_cents=600_000,
            target_date=date(2027, 2, 8),
            created_at=date(2026, 2, 8),
        )

        result = evaluate_goal_intelligence(
            db, user.id, monthly_capacity_cents=100_000, as_of=TEST_DATE
        )

        goal = result.goals[0]
        assert goal.status == "on_track"
        assert goal.key_driver == "on_track"
        assert goal.recommended_action.type == "no_change_needed"


def test_not_feasible_overdue_goal_with_no_capacity_recommends_increase() -> None:
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
        assert goal.status == "not_feasible"
        assert goal.key_driver == "target_date_passed"
        assert goal.recommended_action.type == "increase_goal_allocation"
        assert goal.recommended_action.amount_cents == 50_000
        assert "$500.00" in goal.recommended_action.message
        assert goal.alternative_actions == []


def test_not_feasible_overdue_goal_with_partial_capacity_recommends_extend() -> None:
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
            db, user.id, monthly_capacity_cents=20_000, as_of=TEST_DATE
        )

        goal = result.goals[0]
        assert goal.status == "not_feasible"
        assert goal.allocated_monthly_cents == 20_000
        # remaining 50_000 / allocated 20_000 -> ceil = 3 months out.
        assert goal.projected_completion_date == date(2026, 11, 8)
        assert goal.recommended_action.type == "extend_target_date"
        assert "2026-11-08" in goal.recommended_action.message
        assert goal.alternative_actions == []


def test_at_risk_recommended_action_matches_exact_gap() -> None:
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
        assert goal.status == "at_risk"
        assert goal.key_driver == "insufficient_monthly_capacity"
        assert goal.recommended_action.type == "increase_goal_allocation"
        assert goal.recommended_action.amount_cents == 30_000
        assert goal.recommended_action.resulting_monthly_gap_cents == 0
        assert "$300.00" in goal.recommended_action.message

        # A single goal (no competing goal) only offers the
        # target-date alternative, never a reprioritization option.
        assert len(goal.alternative_actions) == 1
        assert goal.alternative_actions[0].type == "extend_target_date"
        assert "2026-11-08" in goal.alternative_actions[0].message


def test_completed_and_no_deadline_key_drivers_and_actions() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_goal(
            db,
            user,
            name="Done fund",
            target_cents=100_000,
            saved_cents=100_000,
            target_date=date(2026, 12, 1),
        )
        create_goal(
            db,
            user,
            name="Someday fund",
            target_cents=60_000,
            saved_cents=0,
            target_date=None,
        )

        result = evaluate_goal_intelligence(
            db, user.id, monthly_capacity_cents=50_000, as_of=TEST_DATE
        )

        by_name = {g.name: g for g in result.goals}
        done = by_name["Done fund"]
        someday = by_name["Someday fund"]

        assert done.status == "completed"
        assert done.key_driver == "goal_already_completed"
        assert done.recommended_action.type == "no_change_needed"
        assert done.alternative_actions == []

        assert someday.status == "no_deadline"
        assert someday.key_driver == "no_target_date_set"
        assert someday.recommended_action.type == "no_change_needed"
        assert someday.alternative_actions == []


def test_conflict_alternatives_bounded_to_two_with_reprioritize_donor() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        # Nearest deadline, fully funded -- the only eligible donor
        # for a reprioritize suggestion.
        create_goal(
            db,
            user,
            name="Anchor goal",
            target_cents=50_000,
            saved_cents=0,
            target_date=date(2026, 9, 8),
        )
        # Middle deadline, partially funded -- gets both a projected
        # completion (extend_target_date alt) and a donor
        # (reprioritize alt): exactly 2 alternatives.
        create_goal(
            db,
            user,
            name="Business trip",
            target_cents=200_000,
            saved_cents=0,
            target_date=date(2026, 10, 8),
        )
        # Furthest deadline, receives zero allocation -- no
        # projection is possible, so only the reprioritize alt
        # applies.
        create_goal(
            db,
            user,
            name="Car fund",
            target_cents=300_000,
            saved_cents=0,
            target_date=date(2026, 11, 8),
        )

        result = evaluate_goal_intelligence(
            db, user.id, monthly_capacity_cents=90_000, as_of=TEST_DATE
        )

        by_name = {g.name: g for g in result.goals}
        anchor = by_name["Anchor goal"]
        business = by_name["Business trip"]
        car = by_name["Car fund"]

        assert anchor.status == "on_track"
        assert business.status == "conflict"
        assert car.status == "conflict"

        assert business.recommended_action.type == "increase_goal_allocation"
        assert business.recommended_action.amount_cents == 60_000
        assert len(business.alternative_actions) == 2
        alt_types = {alt.type for alt in business.alternative_actions}
        assert alt_types == {"extend_target_date", "reprioritize_goal"}
        reprioritize = next(
            alt
            for alt in business.alternative_actions
            if alt.type == "reprioritize_goal"
        )
        assert reprioritize.goal_id == anchor.goal_id
        assert reprioritize.amount_cents == 50_000

        assert car.recommended_action.amount_cents == 100_000
        # No projected completion is possible with zero allocation,
        # so only the reprioritize alternative applies here.
        assert len(car.alternative_actions) == 1
        assert car.alternative_actions[0].type == "reprioritize_goal"
        assert car.alternative_actions[0].goal_id == anchor.goal_id
