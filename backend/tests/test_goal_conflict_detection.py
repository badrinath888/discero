from datetime import date, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import SavingsGoal, User
from app.schemas import GoalConflictDetectionRequest
from app.services.goal_conflict_detection_service import (
    detect_goal_conflicts,
)
from tests.conftest import TestingSessionLocal
from tests.test_what_if import (
    create_account,
    create_recurring_item,
    seed_income,
)


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


def register_and_login(
    client: TestClient,
    prefix: str,
) -> tuple[int, dict[str, str]]:
    email = f"{prefix}-{uuid4().hex}@example.com"
    password = "TestPassword123!"

    create_response = client.post(
        "/users",
        json={"email": email, "password": password},
    )
    assert create_response.status_code == 201

    login_response = client.post(
        "/users/login",
        json={"email": email, "password": password},
    )
    assert login_response.status_code == 200

    return create_response.json()["id"], {
        "Authorization": f"Bearer {login_response.json()['access_token']}"
    }


def test_capacity_is_derived_from_income_and_obligations_when_omitted() -> (
    None
):
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=0)
        seed_income(db, user)
        create_recurring_item(
            db,
            user,
            merchant="Rent",
            amount_cents=100_000,
            next_payment=TEST_DATE + timedelta(days=5),
        )
        create_goal(
            db,
            user,
            name="Vacation",
            target_cents=600_000,
            target_date=date(2027, 2, 6),
        )

        result = detect_goal_conflicts(
            db,
            user.id,
            GoalConflictDetectionRequest(),
            as_of=TEST_DATE,
        )

        # seed_income averages to 300,000/month; rent is a 100,000
        # upcoming obligation within the 30-day capacity window.
        assert result.monthly_savings_capacity_cents == 200_000
        assert any("estimated" in warning for warning in result.warnings)


def test_explicit_zero_capacity_is_not_overridden() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_goal(
            db,
            user,
            name="Vacation",
            target_cents=600_000,
            target_date=date(2027, 2, 6),
        )

        result = detect_goal_conflicts(
            db,
            user.id,
            GoalConflictDetectionRequest(monthly_savings_capacity_cents=0),
            as_of=TEST_DATE,
        )

        assert result.monthly_savings_capacity_cents == 0
        assert result.warnings == []


def test_monthly_headroom_when_capacity_exceeds_required() -> None:
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

        assert result.total_required_monthly_cents == 100_000
        assert result.monthly_headroom_cents == 50_000
        assert result.key_driver == "no_conflict"
        assert result.recommendation.type == "no_change_needed"
        assert result.recommendation_alternatives == []


def test_monthly_headroom_is_zero_at_exact_capacity() -> None:
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
                monthly_savings_capacity_cents=100_000,
            ),
            as_of=TEST_DATE,
        )

        assert result.monthly_shortfall_cents == 0
        assert result.monthly_headroom_cents == 0


def test_key_driver_insufficient_capacity_when_capacity_is_zero() -> None:
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
            GoalConflictDetectionRequest(monthly_savings_capacity_cents=0),
            as_of=TEST_DATE,
        )

        assert result.conflict_status == "conflict"
        assert result.key_driver == "insufficient_capacity"


def test_key_driver_largest_required_goal_when_capacity_is_positive() -> (
    None
):
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
        assert result.key_driver == "largest_required_goal"


def test_recommendation_primary_resolves_the_gap() -> None:
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

        assert result.recommendation.type == "increase_monthly_capacity"
        assert result.recommendation.amount_cents == 50_000
        assert result.recommendation.resulting_monthly_gap_cents == 0


def test_recommendation_extend_target_date_alternative() -> None:
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

        extend = next(
            (
                alt
                for alt in result.recommendation_alternatives
                if alt.type == "extend_target_date"
            ),
            None,
        )
        assert extend is not None
        assert extend.goal_id == result.goals[1].goal_id
        assert extend.extension_months is not None
        assert extend.extension_months > 0
        assert len(result.recommendation_alternatives) <= 2


def test_no_database_mutation() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_goal(
            db,
            user,
            name="Emergency fund",
            target_cents=600_000,
            target_date=date(2027, 2, 6),
        )

        before_count = db.query(SavingsGoal).count()

        detect_goal_conflicts(
            db,
            user.id,
            GoalConflictDetectionRequest(
                monthly_savings_capacity_cents=150_000,
            ),
            as_of=TEST_DATE,
        )

        db.expire_all()
        after_count = db.query(SavingsGoal).count()
        assert after_count == before_count


def test_goal_conflicts_endpoint_omitted_capacity_returns_200(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "goal-conflicts-endpoint")

    response = client.post(
        f"/users/{user_id}/goal-conflicts",
        headers=headers,
        json={},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["monthly_savings_capacity_cents"] >= 0
    assert body["key_driver"] == "no_goals"


def test_goal_conflicts_endpoint_blocks_other_user(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "goal-conflicts-owner")

    response = client.post(
        f"/users/{user_id + 1}/goal-conflicts",
        headers=headers,
        json={},
    )

    assert response.status_code == 403
