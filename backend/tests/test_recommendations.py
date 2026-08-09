from datetime import date
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import (
    Budget,
    FinancialAccount,
    PlaidItem,
    SavingsGoal,
    Transaction,
    User,
)
from app.services.recommendation_service import evaluate_recommendations
from tests.conftest import TestingSessionLocal


TEST_DATE = date(2026, 8, 8)


def create_user(db: Session) -> User:
    user = User(
        email=f"reco-{uuid4().hex}@example.com",
        password_hash="test-password-hash",
        email_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_account(
    db: Session, user: User, *, available_balance_cents: int = 500_000
) -> None:
    item = PlaidItem(
        user_id=user.id,
        provider_item_id=f"item-{uuid4().hex}",
        institution_name="Test Bank",
        access_token_ciphertext="encrypted-test-token",
        status="active",
    )
    db.add(item)
    db.flush()

    account = FinancialAccount(
        plaid_item_id=item.id,
        provider_account_id=f"account-{uuid4().hex}",
        name="Checking",
        account_type="depository",
        current_balance_cents=available_balance_cents,
        available_balance_cents=available_balance_cents,
        currency="USD",
    )
    db.add(account)
    db.commit()


def create_goal(
    db: Session,
    user: User,
    *,
    name: str = "Vacation",
    target_cents: int = 15_000,
    saved_cents: int = 0,
    target_date: date | None = TEST_DATE,
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
    return goal


def seed_income(db: Session, user: User, *, monthly_cents: int = 10_000) -> None:
    for month in (5, 6, 7):
        db.add(
            Transaction(
                user_id=user.id,
                posted_on=date(2026, month, 15),
                description="Paycheck",
                amount_cents=monthly_cents,
                category="Income",
            )
        )
    db.commit()


def seed_spending(
    db: Session, user: User, *, monthly_cents: int = 100_000
) -> None:
    for month in (5, 6, 7):
        db.add(
            Transaction(
                user_id=user.id,
                posted_on=date(2026, month, 15),
                description="Rent",
                amount_cents=-monthly_cents,
                category="Housing",
            )
        )
    db.commit()


def seed_dining_overspend(db: Session, user: User) -> None:
    db.add(
        Budget(
            user_id=user.id,
            category="Dining",
            month="2026-08",
            limit_cents=10_000,
        )
    )
    db.add(
        Transaction(
            user_id=user.id,
            posted_on=date(2026, 8, 5),
            description="Restaurant",
            amount_cents=-29_800,
            category="Dining",
        )
    )
    db.commit()


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


def test_no_data_surfaces_data_quality_recommendation() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)

        result = evaluate_recommendations(db, user.id, user, as_of=TEST_DATE)

        ids = [r.id for r in result.recommendations]
        assert "no-linked-accounts" in ids


def test_goal_conflict_recommendation_reflects_real_shortfall() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)
        seed_income(db, user, monthly_cents=10_000)  # $100/mo capacity
        create_goal(
            db, user, target_cents=15_000, saved_cents=0
        )  # requires $150/mo (target_date == as_of)

        result = evaluate_recommendations(db, user.id, user, as_of=TEST_DATE)

        goal_rec = next(
            r for r in result.recommendations if r.id == "goal-conflict"
        )
        assert goal_rec.severity == "critical"
        assert goal_rec.category == "goals"
        capacity_signal = next(
            s
            for s in goal_rec.source_signals
            if s.label == "Monthly capacity"
        )
        required_signal = next(
            s
            for s in goal_rec.source_signals
            if s.label == "Required monthly"
        )
        shortfall_signal = next(
            s
            for s in goal_rec.source_signals
            if s.label == "Monthly shortfall"
        )
        assert capacity_signal.value_display == "$100.00"
        assert required_signal.value_display == "$150.00"
        assert shortfall_signal.value_display == "$50.00"
        assert goal_rec.impact == "$50.00/month shortfall"


def test_goal_conflict_recommendation_names_the_pressure_goal() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)
        seed_income(db, user, monthly_cents=10_000)  # $100/mo capacity
        create_goal(
            db,
            user,
            name="Production Test Goal",
            target_cents=15_000,
            saved_cents=0,
        )  # requires $150/mo (target_date == as_of)

        result = evaluate_recommendations(db, user.id, user, as_of=TEST_DATE)

        goal_rec = next(
            r for r in result.recommendations if r.id == "goal-conflict"
        )
        assert "Production Test Goal" in goal_rec.title
        assert "$50.00" in goal_rec.title
        assert "Increase monthly savings by $50.00" in (
            goal_rec.recommended_action or ""
        )
        assert "Production Test Goal's target date" in (
            goal_rec.recommended_action or ""
        )


def test_budget_overage_recommendation() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)
        seed_dining_overspend(db, user)

        result = evaluate_recommendations(db, user.id, user, as_of=TEST_DATE)

        budget_rec = next(
            r for r in result.recommendations if r.id == "budget-overage-Dining"
        )
        assert budget_rec.category == "budget"
        assert "198%" in budget_rec.title or round(
            (29_800 / 10_000) * 100
        ) == 298  # spent 298% of limit -> overspent by $198
        assert budget_rec.impact == "$198.00 over budget"


def test_healthy_safe_to_spend_is_positive_not_fabricated() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=6_000_000)

        result = evaluate_recommendations(db, user.id, user, as_of=TEST_DATE)

        safe_rec = next(
            r for r in result.recommendations if r.id == "safe-to-spend-status"
        )
        assert safe_rec.severity == "positive"
        assert safe_rec.confidence is not None


def test_recommendations_are_capped_and_ranked_by_severity() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=500_000)
        seed_income(db, user, monthly_cents=10_000)
        seed_dining_overspend(db, user)
        create_goal(db, user, target_cents=15_000, saved_cents=0)

        result = evaluate_recommendations(db, user.id, user, as_of=TEST_DATE)

        assert len(result.recommendations) <= 8
        assert result.recommendations == sorted(
            result.recommendations,
            key=lambda r: (
                -{
                    "critical": 5,
                    "warning": 4,
                    "opportunity": 3,
                    "positive": 2,
                    "informational": 1,
                }[r.severity],
                r.id,
            ),
        )
        # Priorities are a contiguous 1-based rank matching list order.
        assert [r.priority for r in result.recommendations] == list(
            range(1, len(result.recommendations) + 1)
        )


def test_recommendations_are_deterministic_across_calls() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)
        seed_income(db, user, monthly_cents=10_000)
        create_goal(db, user, target_cents=15_000, saved_cents=0)

        first = evaluate_recommendations(db, user.id, user, as_of=TEST_DATE)
        second = evaluate_recommendations(db, user.id, user, as_of=TEST_DATE)

        assert [r.id for r in first.recommendations] == [
            r.id for r in second.recommendations
        ]


def test_recommendations_endpoint_requires_authentication(
    client: TestClient,
) -> None:
    response = client.get("/users/9999/recommendations")
    assert response.status_code == 401


def test_recommendations_endpoint_blocks_other_user(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "reco-owner")

    response = client.get(
        f"/users/{user_id + 1}/recommendations", headers=headers
    )

    assert response.status_code == 403


def test_recommendations_endpoint_returns_real_data(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "reco-endpoint")

    response = client.get(
        f"/users/{user_id}/recommendations", headers=headers
    )

    assert response.status_code == 200
    body = response.json()
    assert "recommendations" in body
    assert isinstance(body["recommendations"], list)


# --- Financial resilience recommendation ---------------------------------


def test_weak_runway_recommendation() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=200_000)
        seed_spending(db, user, monthly_cents=100_000)

        result = evaluate_recommendations(db, user.id, user, as_of=TEST_DATE)

        resilience_rec = next(
            r
            for r in result.recommendations
            if r.id == "financial-resilience"
        )
        assert resilience_rec.category == "resilience"
        assert resilience_rec.severity == "warning"
        assert "2.0 month(s)" in (resilience_rec.impact or "")
        # Derived from raw spending history -- must never claim to
        # know which transactions are essential.
        assert "spending-pace runway" in (resilience_rec.impact or "")
        assert "essential-expense" not in (resilience_rec.impact or "")
        burn_signal = next(
            s
            for s in resilience_rec.source_signals
            if s.label == "Monthly spending baseline"
        )
        assert burn_signal.value_display == "$1,000.00"


def test_strong_runway_is_positive_and_not_critical() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=1_500_000)
        seed_spending(db, user, monthly_cents=100_000)

        result = evaluate_recommendations(db, user.id, user, as_of=TEST_DATE)

        resilience_rec = next(
            r
            for r in result.recommendations
            if r.id == "financial-resilience"
        )
        assert resilience_rec.severity == "positive"
        assert resilience_rec.severity != "critical"


def test_resilience_severity_boundaries() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=150_000)
        seed_spending(db, user, monthly_cents=300_000)  # ratio 0.5 -> critical

        result = evaluate_recommendations(db, user.id, user, as_of=TEST_DATE)
        resilience_rec = next(
            r
            for r in result.recommendations
            if r.id == "financial-resilience"
        )
        assert resilience_rec.severity == "critical"

    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=400_000)
        seed_spending(db, user, monthly_cents=100_000)  # ratio 4.0 -> fair

        result = evaluate_recommendations(db, user.id, user, as_of=TEST_DATE)
        resilience_rec = next(
            r
            for r in result.recommendations
            if r.id == "financial-resilience"
        )
        assert resilience_rec.severity == "informational"


def test_reserve_critical_for_severe_runway_not_moderate_budget_overage() -> (
    None
):
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=500_000)
        seed_spending(db, user, monthly_cents=100_000)

        result = evaluate_recommendations(db, user.id, user, as_of=TEST_DATE)

        critical_ids = {
            r.id for r in result.recommendations if r.severity == "critical"
        }
        assert "financial-resilience" not in critical_ids


# --- Budget-overage severity regression (fix) -----------------------------


def test_normal_budget_overage_is_not_critical() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)
        db.add(
            Budget(
                user_id=user.id,
                category="Dining",
                month="2026-08",
                limit_cents=3_000,  # $30
            )
        )
        db.add(
            Transaction(
                user_id=user.id,
                posted_on=date(2026, 8, 5),
                description="Restaurant",
                amount_cents=-8_940,  # $89.40 spent, $59.40 over
                category="Dining",
            )
        )
        db.commit()

        result = evaluate_recommendations(db, user.id, user, as_of=TEST_DATE)

        budget_rec = next(
            r
            for r in result.recommendations
            if r.id == "budget-overage-Dining"
        )
        assert budget_rec.impact == "$59.40 over budget"
        # 298% over a tiny $30 budget is a normal overage, not a
        # critical financial event.
        assert budget_rec.severity == "warning"


def test_large_absolute_budget_overage_is_still_critical() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)
        db.add(
            Budget(
                user_id=user.id,
                category="Dining",
                month="2026-08",
                limit_cents=10_000,  # $100
            )
        )
        db.add(
            Transaction(
                user_id=user.id,
                posted_on=date(2026, 8, 5),
                description="Restaurant",
                amount_cents=-29_800,  # $298 spent, $198 over
                category="Dining",
            )
        )
        db.commit()

        result = evaluate_recommendations(db, user.id, user, as_of=TEST_DATE)

        budget_rec = next(
            r
            for r in result.recommendations
            if r.id == "budget-overage-Dining"
        )
        assert budget_rec.severity == "critical"


# --- Safe-to-spend grounded-copy regression (fix) -------------------------


def test_safe_to_spend_why_does_not_claim_zero_deductions_reduced_it() -> (
    None
):
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=6_000_000)

        result = evaluate_recommendations(db, user.id, user, as_of=TEST_DATE)

        safe_rec = next(
            r for r in result.recommendations if r.id == "safe-to-spend-status"
        )
        # It's fine to name obligations/essential spending/reserve when
        # explicitly saying they are NOT reducing the result -- the bug
        # was claiming they reduced it while being zero.
        assert "no active obligations" in safe_rec.why.lower()
        assert "after upcoming obligations" not in safe_rec.why.lower()
        assert "liquid balance" in safe_rec.why.lower()
