from datetime import date
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models import SavingsGoal, User
from app.services.goal_impact_service import calculate_goal_impacts
from tests.conftest import TestingSessionLocal


TEST_DATE = date(2026, 8, 6)


def create_user(db: Session, prefix: str = "goal-impact") -> User:
    user = User(
        email=f"{prefix}-{uuid4().hex}@example.com",
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


def test_no_active_goals_returns_empty_list() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)

        result = calculate_goal_impacts(
            db,
            user.id,
            baseline_monthly_capacity_cents=50_000,
            adjusted_monthly_capacity_cents=50_000,
            as_of=TEST_DATE,
        )

        assert result == []


def test_single_active_goal_unaffected_when_capacity_unchanged() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        goal = create_goal(
            db,
            user,
            name="Emergency fund",
            target_cents=120_000,
            target_date=date(2027, 8, 6),
        )

        result = calculate_goal_impacts(
            db,
            user.id,
            baseline_monthly_capacity_cents=20_000,
            adjusted_monthly_capacity_cents=20_000,
            as_of=TEST_DATE,
        )

        assert len(result) == 1
        impact = result[0]
        assert impact.goal_id == goal.id
        assert impact.goal_name == "Emergency fund"
        assert impact.remaining_amount_cents == 120_000
        assert impact.current_required_monthly_contribution_cents == 10_000
        assert impact.baseline_monthly_allocation_cents == 20_000
        assert impact.adjusted_monthly_allocation_cents == 20_000
        assert impact.monthly_allocation_change_cents == 0
        assert impact.delay_months == 0
        assert impact.funding_shortfall_cents == 0
        assert impact.status == "unaffected"
        assert (
            impact.baseline_estimated_completion_date
            == impact.adjusted_estimated_completion_date
        )


def test_multiple_goals_allocate_by_nearest_target_date_first() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        vacation = create_goal(
            db,
            user,
            name="Vacation",
            target_cents=100_000,
            target_date=date(2027, 2, 6),
        )
        emergency = create_goal(
            db,
            user,
            name="Emergency fund",
            target_cents=100_000,
            target_date=date(2026, 10, 6),
        )

        result = calculate_goal_impacts(
            db,
            user.id,
            baseline_monthly_capacity_cents=50_000,
            adjusted_monthly_capacity_cents=50_000,
            as_of=TEST_DATE,
        )

        assert [impact.goal_id for impact in result] == [
            emergency.id,
            vacation.id,
        ]
        assert result[0].baseline_monthly_allocation_cents == 50_000
        assert result[1].baseline_monthly_allocation_cents == 0


def test_goals_with_same_target_date_break_ties_by_goal_id() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        first = create_goal(
            db,
            user,
            name="A",
            target_cents=50_000,
            target_date=date(2027, 1, 6),
        )
        second = create_goal(
            db,
            user,
            name="B",
            target_cents=50_000,
            target_date=date(2027, 1, 6),
        )

        result = calculate_goal_impacts(
            db,
            user.id,
            baseline_monthly_capacity_cents=50_000,
            adjusted_monthly_capacity_cents=50_000,
            as_of=TEST_DATE,
        )

        assert [impact.goal_id for impact in result] == [
            first.id,
            second.id,
        ]


def test_completed_goals_are_excluded() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_goal(
            db,
            user,
            name="Done",
            target_cents=50_000,
            saved_cents=50_000,
            target_date=date(2027, 1, 6),
        )
        active = create_goal(
            db,
            user,
            name="Active",
            target_cents=50_000,
            target_date=date(2027, 1, 6),
        )

        result = calculate_goal_impacts(
            db,
            user.id,
            baseline_monthly_capacity_cents=10_000,
            adjusted_monthly_capacity_cents=10_000,
            as_of=TEST_DATE,
        )

        assert len(result) == 1
        assert result[0].goal_id == active.id


def test_overdue_goal_is_at_risk_with_full_shortfall() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_goal(
            db,
            user,
            name="Late goal",
            target_cents=50_000,
            target_date=date(2026, 7, 1),
        )

        result = calculate_goal_impacts(
            db,
            user.id,
            baseline_monthly_capacity_cents=100_000,
            adjusted_monthly_capacity_cents=100_000,
            as_of=TEST_DATE,
        )

        assert len(result) == 1
        impact = result[0]
        assert impact.status == "at_risk"
        assert impact.funding_shortfall_cents == 50_000
        assert impact.adjusted_monthly_allocation_cents == 50_000


def test_goal_without_target_date_is_unaffected_when_capacity_unchanged() -> (
    None
):
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_goal(
            db,
            user,
            name="Someday",
            target_cents=50_000,
            target_date=None,
        )

        result = calculate_goal_impacts(
            db,
            user.id,
            baseline_monthly_capacity_cents=100_000,
            adjusted_monthly_capacity_cents=100_000,
            as_of=TEST_DATE,
        )

        assert len(result) == 1
        impact = result[0]
        assert impact.status == "unaffected"
        assert impact.current_required_monthly_contribution_cents == 0
        assert impact.baseline_monthly_allocation_cents == 50_000
        assert impact.adjusted_monthly_allocation_cents == 50_000
        assert impact.delay_months == 0
        assert impact.funding_shortfall_cents == 0


def test_goal_without_target_date_can_still_be_delayed_never_at_risk() -> (
    None
):
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_goal(
            db,
            user,
            name="Someday",
            target_cents=50_000,
            target_date=None,
        )

        result = calculate_goal_impacts(
            db,
            user.id,
            baseline_monthly_capacity_cents=100_000,
            adjusted_monthly_capacity_cents=10_000,
            as_of=TEST_DATE,
        )

        assert len(result) == 1
        impact = result[0]
        assert impact.status == "delayed"
        assert impact.status != "at_risk"
        assert impact.funding_shortfall_cents == 0
        assert impact.baseline_monthly_allocation_cents == 50_000
        assert impact.adjusted_monthly_allocation_cents == 10_000


def test_zero_available_capacity_is_impossible_without_crashing() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_goal(
            db,
            user,
            name="Unfunded",
            target_cents=50_000,
            target_date=date(2027, 1, 6),
        )

        result = calculate_goal_impacts(
            db,
            user.id,
            baseline_monthly_capacity_cents=0,
            adjusted_monthly_capacity_cents=0,
            as_of=TEST_DATE,
        )

        assert len(result) == 1
        impact = result[0]
        assert impact.status == "impossible"
        assert impact.baseline_monthly_allocation_cents == 0
        assert impact.adjusted_monthly_allocation_cents == 0
        assert impact.funding_shortfall_cents == 50_000


def test_negative_available_capacity_is_clamped_without_crashing() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_goal(
            db,
            user,
            name="Negative capacity",
            target_cents=50_000,
            target_date=date(2027, 1, 6),
        )

        result = calculate_goal_impacts(
            db,
            user.id,
            baseline_monthly_capacity_cents=-25_000,
            adjusted_monthly_capacity_cents=-50_000,
            as_of=TEST_DATE,
        )

        assert len(result) == 1
        impact = result[0]
        assert impact.baseline_monthly_allocation_cents == 0
        assert impact.adjusted_monthly_allocation_cents == 0
        assert impact.status == "impossible"


def test_partially_reduced_allocation_stays_on_time() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_goal(
            db,
            user,
            name="Reduced goal",
            target_cents=90_000,
            target_date=date(2026, 11, 6),
        )

        result = calculate_goal_impacts(
            db,
            user.id,
            baseline_monthly_capacity_cents=80_000,
            adjusted_monthly_capacity_cents=50_000,
            as_of=TEST_DATE,
        )

        assert len(result) == 1
        impact = result[0]
        assert impact.baseline_monthly_allocation_cents == 80_000
        assert impact.adjusted_monthly_allocation_cents == 50_000
        assert impact.monthly_allocation_change_cents == -30_000
        assert impact.delay_months == 0
        assert impact.funding_shortfall_cents == 0
        assert impact.status == "reduced"


def test_delayed_goal_still_meets_target_date() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_goal(
            db,
            user,
            name="Delayed goal",
            target_cents=90_000,
            target_date=date(2026, 11, 6),
        )

        result = calculate_goal_impacts(
            db,
            user.id,
            baseline_monthly_capacity_cents=90_000,
            adjusted_monthly_capacity_cents=35_000,
            as_of=TEST_DATE,
        )

        assert len(result) == 1
        impact = result[0]
        assert impact.delay_months == 2
        assert impact.funding_shortfall_cents == 0
        assert impact.status == "delayed"
        assert (
            impact.adjusted_estimated_completion_date
            > impact.baseline_estimated_completion_date
        )
        assert (
            impact.adjusted_estimated_completion_date
            <= date(2026, 11, 6)
        )


def test_at_risk_goal_reports_shortfall_by_target_date() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_goal(
            db,
            user,
            name="At risk goal",
            target_cents=90_000,
            target_date=date(2026, 11, 6),
        )

        result = calculate_goal_impacts(
            db,
            user.id,
            baseline_monthly_capacity_cents=90_000,
            adjusted_monthly_capacity_cents=20_000,
            as_of=TEST_DATE,
        )

        assert len(result) == 1
        impact = result[0]
        assert impact.status == "at_risk"
        assert impact.funding_shortfall_cents == 30_000
        assert (
            impact.adjusted_estimated_completion_date
            > date(2026, 11, 6)
        )


def test_impossible_goal_when_no_positive_allocation() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_goal(
            db,
            user,
            name="No funding",
            target_cents=50_000,
            target_date=date(2027, 1, 6),
        )

        result = calculate_goal_impacts(
            db,
            user.id,
            baseline_monthly_capacity_cents=50_000,
            adjusted_monthly_capacity_cents=0,
            as_of=TEST_DATE,
        )

        assert len(result) == 1
        impact = result[0]
        assert impact.status == "impossible"
        assert impact.adjusted_monthly_allocation_cents == 0
        assert impact.adjusted_estimated_completion_date is None
        assert impact.funding_shortfall_cents == 50_000


def test_cents_stay_integers_and_consistent_with_odd_amounts() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_goal(
            db,
            user,
            name="Odd cents",
            target_cents=100_001,
            target_date=date(2026, 11, 6),
        )

        result = calculate_goal_impacts(
            db,
            user.id,
            baseline_monthly_capacity_cents=100_001,
            adjusted_monthly_capacity_cents=100_001,
            as_of=TEST_DATE,
        )

        assert len(result) == 1
        impact = result[0]
        assert isinstance(impact.remaining_amount_cents, int)
        assert impact.remaining_amount_cents == 100_001
        assert (
            impact.current_required_monthly_contribution_cents
            == 33_334
        )
        assert impact.baseline_monthly_allocation_cents == 100_001
        assert impact.adjusted_monthly_allocation_cents == 100_001


def test_user_data_isolation() -> None:
    with TestingSessionLocal() as db:
        user_a = create_user(db, "isolation-a")
        user_b = create_user(db, "isolation-b")

        create_goal(
            db,
            user_a,
            name="User A goal",
            target_cents=50_000,
            target_date=date(2027, 1, 6),
        )
        create_goal(
            db,
            user_b,
            name="User B goal",
            target_cents=75_000,
            target_date=date(2027, 1, 6),
        )

        result_a = calculate_goal_impacts(
            db,
            user_a.id,
            baseline_monthly_capacity_cents=50_000,
            adjusted_monthly_capacity_cents=50_000,
            as_of=TEST_DATE,
        )

        assert len(result_a) == 1
        assert result_a[0].goal_name == "User A goal"
