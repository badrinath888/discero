from datetime import date, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    FinancialAccount,
    PlaidItem,
    RecurringItem,
    SavingsGoal,
    Transaction,
    User,
)
from app.schemas import WhatIfSimulationRequest
from app.services.what_if_service import simulate_what_if
from tests.conftest import TestingSessionLocal

TEST_DATE = date(2026, 8, 4)


def create_user(
    db: Session,
    email_prefix: str = "what-if",
) -> User:
    user = User(
        email=f"{email_prefix}-{uuid4().hex}@example.com",
        password_hash="test-password-hash",
        email_verified=True,
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return user


def create_account(
    db: Session,
    user: User,
    *,
    available_balance_cents: int | None = 500_000,
) -> FinancialAccount:
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
    db.refresh(account)

    return account


def create_recurring_item(
    db: Session,
    user: User,
    *,
    merchant: str,
    amount_cents: int,
    next_payment: date,
    frequency: str = "Monthly",
) -> RecurringItem:
    item = RecurringItem(
        user_id=user.id,
        merchant=merchant,
        normalized_merchant=f"{merchant.upper()}-{uuid4().hex}",
        category="Bills",
        amount_cents=amount_cents,
        frequency=frequency,
        last_payment=next_payment - timedelta(days=30),
        next_payment=next_payment,
        status="active",
        confidence_score=90.0,
    )

    db.add(item)
    db.commit()
    db.refresh(item)

    return item


def create_goal(
    db: Session,
    user: User,
    *,
    target_cents: int = 600_000,
    saved_cents: int = 0,
    target_date: date | None = date(2027, 8, 4),
) -> SavingsGoal:
    goal = SavingsGoal(
        user_id=user.id,
        name="Vacation",
        target_cents=target_cents,
        saved_cents=saved_cents,
        target_date=target_date,
    )

    db.add(goal)
    db.commit()
    db.refresh(goal)

    return goal


def seed_income(db: Session, user: User) -> None:
    for month in (5, 6, 7):
        db.add(
            Transaction(
                user_id=user.id,
                posted_on=date(2026, month, 1),
                description="Paycheck",
                amount_cents=300_000,
                category="Income",
            )
        )
    db.commit()


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


def test_one_time_expense_reduces_safe_to_spend() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "one-time-basic")
        create_account(db, user, available_balance_cents=500_000)

        result = simulate_what_if(
            db,
            user.id,
            WhatIfSimulationRequest(
                scenario_type="one_time_expense",
                scenario_name="New laptop",
                amount_cents=200_000,
                effective_date=TEST_DATE + timedelta(days=5),
            ),
            as_of=TEST_DATE,
        )

        assert result.baseline.safe_to_spend_cents == 500_000
        assert result.scenario.safe_to_spend_cents == 300_000
        assert result.scenario.shortfall_cents == 0
        assert result.impact.safe_to_spend_delta_cents == -200_000
        assert result.impact.level == "caution"


def test_one_time_expense_creates_first_shortfall() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "one-time-shortfall")
        create_account(db, user, available_balance_cents=100_000)

        result = simulate_what_if(
            db,
            user.id,
            WhatIfSimulationRequest(
                scenario_type="one_time_expense",
                scenario_name="Emergency repair",
                amount_cents=250_000,
                effective_date=TEST_DATE + timedelta(days=5),
            ),
            as_of=TEST_DATE,
        )

        assert result.baseline.shortfall_cents == 0
        assert result.scenario.safe_to_spend_cents == 0
        assert result.scenario.shortfall_cents == 150_000
        assert result.impact.level == "negative"


def test_one_time_expense_worsens_existing_shortfall() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "existing-shortfall")
        create_account(db, user, available_balance_cents=100_000)
        create_recurring_item(
            db,
            user,
            merchant="Rent",
            amount_cents=300_000,
            next_payment=TEST_DATE + timedelta(days=5),
        )

        result = simulate_what_if(
            db,
            user.id,
            WhatIfSimulationRequest(
                scenario_type="one_time_expense",
                scenario_name="Car repair",
                amount_cents=50_000,
                effective_date=TEST_DATE + timedelta(days=5),
            ),
            as_of=TEST_DATE,
        )

        # Baseline already short by 200,000 (100,000 liquid against a
        # 300,000 obligation). The extra 50,000 hypothetical expense
        # must COMPOUND that shortfall to 250,000, not restart from
        # the already-clamped $0 baseline figure.
        assert result.baseline.safe_to_spend_cents == 0
        assert result.baseline.shortfall_cents == 200_000
        assert result.scenario.shortfall_cents == 250_000
        assert result.impact.shortfall_delta_cents == 50_000
        assert result.impact.level == "negative"


def test_rejects_effective_date_before_calculation_date() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "past-date")
        create_account(db, user)

        try:
            simulate_what_if(
                db,
                user.id,
                WhatIfSimulationRequest(
                    scenario_type="one_time_expense",
                    scenario_name="Phone",
                    amount_cents=100_000,
                    effective_date=TEST_DATE - timedelta(days=1),
                ),
                as_of=TEST_DATE,
            )
        except ValueError as exc:
            assert "cannot be before the calculation date" in str(exc)
        else:
            raise AssertionError("expected ValueError")


def test_rejects_effective_date_outside_horizon() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "outside-horizon")
        create_account(db, user)

        try:
            simulate_what_if(
                db,
                user.id,
                WhatIfSimulationRequest(
                    scenario_type="one_time_expense",
                    scenario_name="Trip",
                    amount_cents=100_000,
                    effective_date=TEST_DATE + timedelta(days=31),
                    horizon_days=30,
                ),
                as_of=TEST_DATE,
            )
        except ValueError as exc:
            assert "must fall within the selected horizon" in str(exc)
        else:
            raise AssertionError("expected ValueError")


def test_monthly_expense_increase_prorates_over_horizon() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "expense-increase")
        create_account(db, user, available_balance_cents=1_000_000)

        result = simulate_what_if(
            db,
            user.id,
            WhatIfSimulationRequest(
                scenario_type="monthly_expense_change",
                scenario_name="Rent increase",
                monthly_amount_change_cents=30_000,
                horizon_days=90,
            ),
            as_of=TEST_DATE,
        )

        # $300/month over a 90-day (3-month) horizon -> $900 impact.
        assert result.impact.safe_to_spend_delta_cents == -90_000


def test_monthly_expense_decrease_improves_result() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "expense-decrease")
        create_account(db, user, available_balance_cents=500_000)

        result = simulate_what_if(
            db,
            user.id,
            WhatIfSimulationRequest(
                scenario_type="monthly_expense_change",
                scenario_name="Cancel subscription",
                monthly_amount_change_cents=-10_000,
                horizon_days=30,
            ),
            as_of=TEST_DATE,
        )

        assert result.impact.safe_to_spend_delta_cents == 10_000
        assert result.impact.level == "positive"


def test_monthly_income_decrease_reduces_safe_to_spend() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "income-decrease")
        create_account(db, user, available_balance_cents=500_000)

        result = simulate_what_if(
            db,
            user.id,
            WhatIfSimulationRequest(
                scenario_type="monthly_income_change",
                scenario_name="Income drop",
                monthly_amount_change_cents=-100_000,
                horizon_days=30,
            ),
            as_of=TEST_DATE,
        )

        assert result.impact.safe_to_spend_delta_cents == -100_000
        assert result.impact.level == "caution"


def test_monthly_income_increase_improves_result() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "income-increase")
        create_account(db, user, available_balance_cents=500_000)

        result = simulate_what_if(
            db,
            user.id,
            WhatIfSimulationRequest(
                scenario_type="monthly_income_change",
                scenario_name="Raise",
                monthly_amount_change_cents=50_000,
                horizon_days=30,
            ),
            as_of=TEST_DATE,
        )

        assert result.impact.safe_to_spend_delta_cents == 50_000
        assert result.impact.level == "positive"


def test_monthly_savings_increase_reserves_funds() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "savings-increase")
        create_account(db, user, available_balance_cents=500_000)

        result = simulate_what_if(
            db,
            user.id,
            WhatIfSimulationRequest(
                scenario_type="monthly_savings_change",
                scenario_name="Save more",
                monthly_amount_change_cents=50_000,
                horizon_days=30,
            ),
            as_of=TEST_DATE,
        )

        assert result.impact.safe_to_spend_delta_cents == -50_000
        # Already fully represented in the safe-to-spend delta itself
        # -- goal capacity is not separately touched, to avoid
        # double-counting the same hypothetical dollars.
        assert result.goal_impacts == []


def test_temporary_income_loss_caps_at_duration() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "income-loss")
        create_account(db, user, available_balance_cents=1_000_000)

        result = simulate_what_if(
            db,
            user.id,
            WhatIfSimulationRequest(
                scenario_type="temporary_income_loss",
                scenario_name="Layoff",
                monthly_income_loss_cents=250_000,
                duration_months=2,
                horizon_days=90,
            ),
            as_of=TEST_DATE,
        )

        assert result.impact.safe_to_spend_delta_cents == -500_000


def test_temporary_income_loss_caps_at_horizon_when_duration_longer() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "income-loss-long-duration")
        create_account(db, user, available_balance_cents=1_000_000)

        result = simulate_what_if(
            db,
            user.id,
            WhatIfSimulationRequest(
                scenario_type="temporary_income_loss",
                scenario_name="Extended leave",
                monthly_income_loss_cents=100_000,
                duration_months=3,
                horizon_days=30,
            ),
            as_of=TEST_DATE,
        )

        # Only 1 month of the 3-month loss falls inside a 30-day
        # horizon.
        assert result.impact.safe_to_spend_delta_cents == -100_000


def test_zero_monthly_amount_change_is_rejected(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "zero-amount")

    response = client.post(
        f"/users/{user_id}/what-if",
        headers=headers,
        json={
            "scenario_type": "monthly_expense_change",
            "scenario_name": "No-op",
            "monthly_amount_change_cents": 0,
        },
    )

    assert response.status_code == 422


def test_missing_required_field_is_rejected(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "missing-field")

    response = client.post(
        f"/users/{user_id}/what-if",
        headers=headers,
        json={
            "scenario_type": "temporary_income_loss",
            "scenario_name": "Layoff",
            "monthly_income_loss_cents": 100_000,
        },
    )

    assert response.status_code == 422


def test_confidence_unchanged_between_baseline_and_scenario() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "confidence-unchanged")
        create_account(db, user, available_balance_cents=500_000)
        create_recurring_item(
            db,
            user,
            merchant="Rent",
            amount_cents=100_000,
            next_payment=TEST_DATE + timedelta(days=5),
        )

        result = simulate_what_if(
            db,
            user.id,
            WhatIfSimulationRequest(
                scenario_type="one_time_expense",
                scenario_name="Laptop",
                amount_cents=50_000,
                effective_date=TEST_DATE + timedelta(days=5),
            ),
            as_of=TEST_DATE,
        )

        assert (
            result.baseline.confidence_score
            == result.scenario.confidence_score
        )
        assert (
            result.baseline.confidence_level
            == result.scenario.confidence_level
        )
        assert result.impact.confidence_delta == 0.0


def test_never_negative_safe_to_spend() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "never-negative")
        create_account(db, user, available_balance_cents=10_000)

        result = simulate_what_if(
            db,
            user.id,
            WhatIfSimulationRequest(
                scenario_type="one_time_expense",
                scenario_name="Large expense",
                amount_cents=5_000_000,
                effective_date=TEST_DATE + timedelta(days=5),
            ),
            as_of=TEST_DATE,
        )

        assert result.scenario.safe_to_spend_cents == 0
        assert result.scenario.shortfall_cents > 0


def test_no_accounts_or_data_does_not_crash() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "no-data")

        result = simulate_what_if(
            db,
            user.id,
            WhatIfSimulationRequest(
                scenario_type="monthly_income_change",
                scenario_name="Hypothetical raise",
                monthly_amount_change_cents=10_000,
            ),
            as_of=TEST_DATE,
        )

        assert result.baseline.safe_to_spend_cents == 0
        assert result.scenario.safe_to_spend_cents == 10_000


def test_goal_impacts_included_for_capacity_affecting_scenarios() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "goal-impacts")
        create_account(db, user, available_balance_cents=500_000)
        seed_income(db, user)
        create_goal(db, user, target_cents=600_000, saved_cents=0)

        result = simulate_what_if(
            db,
            user.id,
            WhatIfSimulationRequest(
                scenario_type="monthly_expense_change",
                scenario_name="Bill increase",
                monthly_amount_change_cents=100_000,
                horizon_days=30,
            ),
            as_of=TEST_DATE,
        )

        assert len(result.goal_impacts) == 1


def test_goal_impacts_empty_for_one_time_expense() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "goal-impacts-one-time")
        create_account(db, user, available_balance_cents=500_000)
        seed_income(db, user)
        create_goal(db, user, target_cents=600_000, saved_cents=0)

        result = simulate_what_if(
            db,
            user.id,
            WhatIfSimulationRequest(
                scenario_type="one_time_expense",
                scenario_name="Laptop",
                amount_cents=50_000,
                effective_date=TEST_DATE + timedelta(days=5),
            ),
            as_of=TEST_DATE,
        )

        assert result.goal_impacts == []


def test_simulation_writes_nothing_to_the_database() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "no-side-effects")
        create_account(db, user, available_balance_cents=500_000)
        create_goal(db, user, target_cents=600_000, saved_cents=0)

        transactions_before = db.scalar(
            select(Transaction).where(Transaction.user_id == user.id)
        )
        recurring_before = db.scalar(
            select(RecurringItem).where(
                RecurringItem.user_id == user.id
            )
        )
        goal = db.scalar(
            select(SavingsGoal).where(SavingsGoal.user_id == user.id)
        )

        simulate_what_if(
            db,
            user.id,
            WhatIfSimulationRequest(
                scenario_type="temporary_income_loss",
                scenario_name="Layoff",
                monthly_income_loss_cents=200_000,
                duration_months=2,
                horizon_days=90,
            ),
            as_of=TEST_DATE,
        )

        assert transactions_before is None
        assert recurring_before is None
        assert goal is not None
        assert goal.target_cents == 600_000
        assert goal.saved_cents == 0

        assert (
            db.scalar(
                select(Transaction).where(
                    Transaction.user_id == user.id
                )
            )
            is None
        )
        assert (
            db.scalar(
                select(RecurringItem).where(
                    RecurringItem.user_id == user.id
                )
            )
            is None
        )


def test_what_if_endpoint(client: TestClient) -> None:
    user_id, headers = register_and_login(client, "what-if-endpoint")

    with TestingSessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        create_account(db, user, available_balance_cents=500_000)

    response = client.post(
        f"/users/{user_id}/what-if",
        headers=headers,
        json={
            "scenario_type": "one_time_expense",
            "scenario_name": "New laptop",
            "amount_cents": 200_000,
            "effective_date": (
                date.today() + timedelta(days=5)
            ).isoformat(),
        },
    )

    assert response.status_code == 200

    payload = response.json()

    assert payload["baseline"]["safe_to_spend_cents"] == 500_000
    assert payload["scenario"]["safe_to_spend_cents"] == 300_000
    assert payload["impact"]["safe_to_spend_delta_cents"] == -200_000
    assert payload["impact"]["level"] in {
        "positive",
        "neutral",
        "caution",
        "negative",
    }
    assert len(payload["explanation"]) > 0


def test_what_if_endpoint_blocks_other_user(client: TestClient) -> None:
    user_id, _headers = register_and_login(client, "what-if-owner")
    _other_id, other_headers = register_and_login(
        client, "what-if-intruder"
    )

    response = client.post(
        f"/users/{user_id}/what-if",
        headers=other_headers,
        json={
            "scenario_type": "one_time_expense",
            "scenario_name": "Laptop",
            "amount_cents": 100_000,
            "effective_date": (
                date.today() + timedelta(days=5)
            ).isoformat(),
        },
    )

    assert response.status_code == 403
