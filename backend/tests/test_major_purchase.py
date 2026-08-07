from datetime import date, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import (
    FinancialAccount,
    PlaidItem,
    SavingsGoal,
    Transaction,
    User,
)
from app.schemas import MajorPurchaseSimulationRequest
from app.services.major_purchase_service import (
    simulate_major_purchase,
)
from tests.conftest import TestingSessionLocal


TEST_DATE = date(2026, 8, 4)


def create_user(
    db: Session,
    email_prefix: str = "major-purchase",
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
    current_balance_cents: int | None = 500_000,
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
        current_balance_cents=current_balance_cents,
        available_balance_cents=available_balance_cents,
        currency="USD",
    )

    db.add(account)
    db.commit()
    db.refresh(account)

    return account


def register_and_login(
    client: TestClient,
    prefix: str,
) -> tuple[int, dict[str, str]]:
    email = f"{prefix}-{uuid4().hex}@example.com"
    password = "TestPassword123!"

    create_response = client.post(
        "/users",
        json={
            "email": email,
            "password": password,
        },
    )

    assert create_response.status_code == 201

    login_response = client.post(
        "/users/login",
        json={
            "email": email,
            "password": password,
        },
    )

    assert login_response.status_code == 200

    return create_response.json()["id"], {
        "Authorization": (
            f"Bearer {login_response.json()['access_token']}"
        )
    }


def test_affordable_purchase() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "affordable")

        create_account(
            db,
            user,
            available_balance_cents=500_000,
        )

        result = simulate_major_purchase(
            db,
            user.id,
            MajorPurchaseSimulationRequest(
                purchase_name="Laptop",
                purchase_amount_cents=200_000,
                purchase_date=TEST_DATE + timedelta(days=7),
                horizon_days=30,
            ),
            as_of=TEST_DATE,
        )

        assert result.affordability_status == "affordable"
        assert result.safe_to_spend_before_purchase_cents == 500_000
        assert result.safe_to_spend_after_purchase_cents == 300_000
        assert result.shortfall_after_purchase_cents == 0
        assert result.recommended_max_purchase_cents == 375_000
        assert result.purchase_impact_percent == 40.0


def test_caution_purchase() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "caution")

        create_account(
            db,
            user,
            available_balance_cents=500_000,
        )

        result = simulate_major_purchase(
            db,
            user.id,
            MajorPurchaseSimulationRequest(
                purchase_name="Vacation",
                purchase_amount_cents=400_000,
                purchase_date=TEST_DATE + timedelta(days=10),
            ),
            as_of=TEST_DATE,
        )

        assert result.affordability_status == "caution"
        assert result.safe_to_spend_after_purchase_cents == 100_000
        assert result.shortfall_after_purchase_cents == 0
        assert len(result.alternatives) == 2


def test_not_affordable_purchase() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "not-affordable")

        create_account(
            db,
            user,
            available_balance_cents=300_000,
        )

        result = simulate_major_purchase(
            db,
            user.id,
            MajorPurchaseSimulationRequest(
                purchase_name="Car",
                purchase_amount_cents=450_000,
                purchase_date=TEST_DATE + timedelta(days=5),
            ),
            as_of=TEST_DATE,
        )

        assert result.affordability_status == "not_affordable"
        assert result.safe_to_spend_after_purchase_cents == 0
        assert result.shortfall_after_purchase_cents == 150_000
        assert result.purchase_impact_percent == 150.0


def test_respects_reserve_and_essential_spending() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "reserve")

        create_account(
            db,
            user,
            available_balance_cents=600_000,
        )

        result = simulate_major_purchase(
            db,
            user.id,
            MajorPurchaseSimulationRequest(
                purchase_name="Furniture",
                purchase_amount_cents=250_000,
                purchase_date=TEST_DATE + timedelta(days=8),
                safety_reserve_cents=150_000,
                essential_spending_cents=100_000,
            ),
            as_of=TEST_DATE,
        )

        assert result.safe_to_spend_before_purchase_cents == 350_000
        assert result.safe_to_spend_after_purchase_cents == 100_000
        assert result.affordability_status == "affordable"


def test_rejects_purchase_date_before_calculation_date() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "past-date")

        create_account(db, user)

        try:
            simulate_major_purchase(
                db,
                user.id,
                MajorPurchaseSimulationRequest(
                    purchase_name="Phone",
                    purchase_amount_cents=100_000,
                    purchase_date=TEST_DATE - timedelta(days=1),
                ),
                as_of=TEST_DATE,
            )
        except ValueError as exc:
            assert str(exc) == (
                "purchase date cannot be before the calculation date"
            )
        else:
            raise AssertionError("expected ValueError")


def test_rejects_purchase_date_outside_horizon() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "outside-horizon")

        create_account(db, user)

        try:
            simulate_major_purchase(
                db,
                user.id,
                MajorPurchaseSimulationRequest(
                    purchase_name="Trip",
                    purchase_amount_cents=100_000,
                    purchase_date=TEST_DATE + timedelta(days=31),
                    horizon_days=30,
                ),
                as_of=TEST_DATE,
            )
        except ValueError as exc:
            assert str(exc) == (
                "purchase date must fall within the selected horizon"
            )
        else:
            raise AssertionError("expected ValueError")


def test_major_purchase_endpoint(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client,
        "major-purchase-endpoint",
    )

    with TestingSessionLocal() as db:
        user = db.get(User, user_id)

        assert user is not None

        create_account(
            db,
            user,
            available_balance_cents=500_000,
        )

    response = client.post(
        f"/users/{user_id}/major-purchase/simulate",
        headers=headers,
        json={
            "purchase_name": "Laptop",
            "purchase_amount_cents": 200_000,
            "purchase_date": (
                date.today() + timedelta(days=7)
            ).isoformat(),
            "safety_reserve_cents": 0,
            "essential_spending_cents": 0,
            "horizon_days": 30,
        },
    )

    assert response.status_code == 200

    payload = response.json()

    assert payload["purchase_name"] == "Laptop"
    assert payload["affordability_status"] == "affordable"
    assert payload["safe_to_spend_before_purchase_cents"] == 500_000
    assert payload["safe_to_spend_after_purchase_cents"] == 300_000
    assert payload["shortfall_after_purchase_cents"] == 0
    assert payload["recommended_max_purchase_cents"] == 375_000
    assert payload["safe_to_spend"]["safe_to_spend_cents"] == 500_000


def create_goal(
    db: Session,
    user: User,
    *,
    name: str = "Vacation",
    target_cents: int = 600_000,
    saved_cents: int = 0,
    target_date: date | None = date(2027, 8, 4),
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


def seed_income(db: Session, user: User) -> None:
    for month in (5, 6, 7):
        transaction = Transaction(
            user_id=user.id,
            posted_on=date(2026, month, 1),
            description="Paycheck",
            amount_cents=300_000,
            category="Income",
        )
        db.add(transaction)
    db.commit()


def test_goal_impacts_included_in_purchase_simulation() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "purchase-goal-impact")

        create_account(db, user, available_balance_cents=500_000)
        seed_income(db, user)
        create_goal(db, user, name="Vacation")

        result = simulate_major_purchase(
            db,
            user.id,
            MajorPurchaseSimulationRequest(
                purchase_name="Laptop",
                purchase_amount_cents=200_000,
                purchase_date=TEST_DATE + timedelta(days=7),
                horizon_days=30,
            ),
            as_of=TEST_DATE,
        )

        # Existing fields remain intact alongside the new list.
        assert result.affordability_status == "affordable"
        assert result.safe_to_spend_after_purchase_cents == 300_000

        assert len(result.goal_impacts) == 1
        impact = result.goal_impacts[0]
        assert impact.goal_name == "Vacation"
        assert impact.status in (
            "unaffected",
            "reduced",
            "delayed",
            "at_risk",
            "impossible",
        )


def test_goal_impacts_empty_when_no_active_goals_in_purchase() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "purchase-no-goals")

        create_account(db, user, available_balance_cents=500_000)

        result = simulate_major_purchase(
            db,
            user.id,
            MajorPurchaseSimulationRequest(
                purchase_name="Laptop",
                purchase_amount_cents=200_000,
                purchase_date=TEST_DATE + timedelta(days=7),
                horizon_days=30,
            ),
            as_of=TEST_DATE,
        )

        assert result.goal_impacts == []


def test_major_purchase_endpoint_blocks_other_user(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client,
        "major-purchase-owner",
    )
    other_user_id, _ = register_and_login(
        client,
        "major-purchase-other",
    )

    response = client.post(
        f"/users/{other_user_id}/major-purchase/simulate",
        headers=headers,
        json={
            "purchase_name": "Laptop",
            "purchase_amount_cents": 200_000,
            "purchase_date": (
                date.today() + timedelta(days=7)
            ).isoformat(),
            "horizon_days": 30,
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "you cannot access another user's data"
    )
