from datetime import date
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models import SavingsGoal, User
from app.schemas import GoalConflictDetectionRequest
from app.services.goal_conflict_detection_service import (
    detect_goal_conflicts,
)
from tests.conftest import TestingSessionLocal


TEST_DATE = date(2026, 8, 6)


def create_user(db: Session) -> User:
    user = User(
        email=f"goal-conflict-{uuid4().hex}@example.com",
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


def test_detects_conflict_when_capacity_is_insufficient() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)

        create_goal(
            db,
            user,
            name="Emergency fund",
            target_cents=600_000,
            target_date=date(2027, 2, 6),
        )
        create_goal(
            db,
            user,
            name="Vacation",
            target_cents=300_000,
            target_date=date(2026, 11, 6),
        )

        result = detect_goal_conflicts(
            db,
            user.id,
            GoalConflictDetectionRequest(
                monthly_savings_capacity_cents=150_000,
            ),
            as_of=TEST_DATE,
        )

        assert result.conflict_status == "conflict"
        assert result.total_required_monthly_cents == 200_000
        assert result.monthly_shortfall_cents == 50_000
        assert result.goals[0].status == "on_track"
        assert result.goals[1].status == "at_risk"


def test_conflict_explanation_uses_formatted_dollars_not_cents() -> (
    None
):
    # Regression test for a production report: the explanation
    # sentence was interpolating raw integer cents ("15000 cents")
    # instead of formatted dollars, while the calculation cards
    # (fed by the same numbers) already displayed dollars correctly.
    with TestingSessionLocal() as db:
        user = create_user(db)

        create_goal(
            db,
            user,
            name="Emergency fund",
            target_cents=15_000,
            target_date=TEST_DATE,
        )

        result = detect_goal_conflicts(
            db,
            user.id,
            GoalConflictDetectionRequest(
                monthly_savings_capacity_cents=10_000,
            ),
            as_of=TEST_DATE,
        )

        assert result.conflict_status == "conflict"
        assert result.total_required_monthly_cents == 15_000
        assert result.monthly_savings_capacity_cents == 10_000
        assert result.monthly_shortfall_cents == 5_000

        assert result.explanation == (
            "Your goals require $150.00 per month, but only $100.00 "
            "is available, leaving a $50.00 monthly shortfall."
        )
        assert "15000 cents" not in result.explanation
        assert "10000 cents" not in result.explanation
        assert "5000 cent" not in result.explanation
        assert "cents" not in result.explanation
        assert "cent " not in result.explanation


def test_returns_no_conflict_when_capacity_is_sufficient() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)

        create_goal(
            db,
            user,
            name="Emergency fund",
            target_cents=600_000,
            target_date=date(2027, 2, 6),
        )

        result = detect_goal_conflicts(
            db,
            user.id,
            GoalConflictDetectionRequest(
                monthly_savings_capacity_cents=150_000,
            ),
            as_of=TEST_DATE,
        )

        assert result.conflict_status == "no_conflict"
        assert result.total_required_monthly_cents == 100_000
        assert result.monthly_shortfall_cents == 0
        assert result.goals[0].status == "on_track"


def test_goal_without_deadline_is_reported() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)

        create_goal(
            db,
            user,
            name="Future home",
            target_cents=2_000_000,
        )

        result = detect_goal_conflicts(
            db,
            user.id,
            GoalConflictDetectionRequest(
                monthly_savings_capacity_cents=100_000,
            ),
            as_of=TEST_DATE,
        )

        assert result.goals[0].status == "no_deadline"
        assert result.goals[0].required_monthly_cents == 0
        assert result.confidence_score == 90.0
        assert any(
            "target dates" in recommendation
            for recommendation in result.recommendations
        )
