from datetime import date, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from sqlalchemy.orm import Session

from app.models import (
    FinancialAccount,
    PlaidItem,
    RecurringItem,
    User,
)
from app.schemas import SafeToSpendRequest
from app.services.safe_to_spend_service import (
    calculate_safe_to_spend,
)
from tests.conftest import TestingSessionLocal


TEST_DATE = date(2026, 8, 4)


def create_user(
    db: Session,
    email_prefix: str = "safe-to-spend",
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
    name: str = "Checking",
    account_type: str = "depository",
    available_balance_cents: int | None = 500_000,
    current_balance_cents: int | None = 500_000,
    item_status: str = "active",
) -> FinancialAccount:
    item = PlaidItem(
        user_id=user.id,
        provider_item_id=f"item-{uuid4().hex}",
        institution_name="Test Bank",
        access_token_ciphertext="encrypted-test-token",
        status=item_status,
    )

    db.add(item)
    db.flush()

    account = FinancialAccount(
        plaid_item_id=item.id,
        provider_account_id=f"account-{uuid4().hex}",
        name=name,
        account_type=account_type,
        current_balance_cents=current_balance_cents,
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
    status: str = "active",
    confidence_score: float = 90.0,
) -> RecurringItem:
    item = RecurringItem(
        user_id=user.id,
        merchant=merchant,
        normalized_merchant=f"{merchant.upper()}-{uuid4().hex}",
        category="Bills",
        amount_cents=amount_cents,
        frequency="Monthly",
        last_payment=next_payment - timedelta(days=30),
        next_payment=next_payment,
        status=status,
        confidence_score=confidence_score,
    )

    db.add(item)
    db.commit()
    db.refresh(item)

    return item


def test_calculates_safe_to_spend() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)

        create_account(
            db,
            user,
            available_balance_cents=500_000,
        )

        create_recurring_item(
            db,
            user,
            merchant="Rent",
            amount_cents=150_000,
            next_payment=TEST_DATE + timedelta(days=5),
        )

        result = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(
                safety_reserve_cents=100_000,
                essential_spending_cents=50_000,
                horizon_days=30,
            ),
            as_of=TEST_DATE,
        )

        assert result.safe_to_spend_cents == 200_000
        assert result.shortfall_cents == 0
        assert result.status == "safe"
        assert result.breakdown.liquid_balance_cents == 500_000
        assert result.breakdown.upcoming_obligations_cents == 150_000
        assert len(result.obligations) == 1
        assert result.obligations[0].name == "Rent"


def test_uses_current_balance_when_available_balance_missing() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "balance-fallback")

        create_account(
            db,
            user,
            name="Savings",
            available_balance_cents=None,
            current_balance_cents=275_000,
        )

        result = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(),
            as_of=TEST_DATE,
        )

        assert result.breakdown.liquid_balance_cents == 275_000
        assert any(
            "used its current balance" in warning
            for warning in result.warnings
        )

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

def test_excludes_non_liquid_and_inactive_accounts() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "account-filter")

        create_account(
            db,
            user,
            name="Checking",
            available_balance_cents=300_000,
        )

        create_account(
            db,
            user,
            name="Credit Card",
            account_type="credit",
            available_balance_cents=900_000,
        )

        create_account(
            db,
            user,
            name="Inactive Checking",
            available_balance_cents=400_000,
            item_status="inactive",
        )

        result = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(),
            as_of=TEST_DATE,
        )

        assert result.breakdown.liquid_balance_cents == 300_000


def test_filters_recurring_items_by_status_and_horizon() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "obligation-filter")

        create_account(
            db,
            user,
            available_balance_cents=600_000,
        )

        create_recurring_item(
            db,
            user,
            merchant="Insurance",
            amount_cents=80_000,
            next_payment=TEST_DATE + timedelta(days=10),
        )

        create_recurring_item(
            db,
            user,
            merchant="Cancelled Subscription",
            amount_cents=20_000,
            next_payment=TEST_DATE + timedelta(days=8),
            status="cancelled",
        )

        create_recurring_item(
            db,
            user,
            merchant="Future Bill",
            amount_cents=100_000,
            next_payment=TEST_DATE + timedelta(days=45),
        )

        result = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(horizon_days=30),
            as_of=TEST_DATE,
        )

        assert result.breakdown.upcoming_obligations_cents == 80_000
        assert len(result.obligations) == 1
        assert result.obligations[0].name == "Insurance"


def test_returns_negative_status_and_shortfall() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "negative-result")

        create_account(
            db,
            user,
            available_balance_cents=200_000,
        )

        create_recurring_item(
            db,
            user,
            merchant="Rent",
            amount_cents=150_000,
            next_payment=TEST_DATE + timedelta(days=3),
        )

        result = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(
                safety_reserve_cents=100_000,
                essential_spending_cents=50_000,
            ),
            as_of=TEST_DATE,
        )

        assert result.safe_to_spend_cents == 0
        assert result.shortfall_cents == 100_000
        assert result.status == "negative"


def test_does_not_include_another_users_data() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "owner")
        other_user = create_user(db, "other-owner")

        create_account(
            db,
            user,
            available_balance_cents=250_000,
        )

        create_account(
            db,
            other_user,
            available_balance_cents=900_000,
        )

        create_recurring_item(
            db,
            other_user,
            merchant="Other User Rent",
            amount_cents=200_000,
            next_payment=TEST_DATE + timedelta(days=5),
        )

        result = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(),
            as_of=TEST_DATE,
        )

        assert result.breakdown.liquid_balance_cents == 250_000
        assert result.breakdown.upcoming_obligations_cents == 0
        assert result.safe_to_spend_cents == 250_000

def test_safe_to_spend_endpoint(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client,
        "safe-to-spend-endpoint",
    )

    with TestingSessionLocal() as db:
        user = db.get(User, user_id)

        assert user is not None

        create_account(
            db,
            user,
            available_balance_cents=500_000,
        )

        create_recurring_item(
            db,
            user,
            merchant="Rent",
            amount_cents=150_000,
            next_payment=date.today() + timedelta(days=5),
        )

    response = client.post(
        f"/users/{user_id}/safe-to-spend",
        headers=headers,
        json={
            "safety_reserve_cents": 100_000,
            "essential_spending_cents": 50_000,
            "horizon_days": 30,
        },
    )

    assert response.status_code == 200

    payload = response.json()

    assert payload["safe_to_spend_cents"] == 200_000
    assert payload["shortfall_cents"] == 0
    assert payload["status"] == "safe"
    assert payload["breakdown"]["liquid_balance_cents"] == 500_000
    assert (
        payload["breakdown"]["upcoming_obligations_cents"]
        == 150_000
    )
    assert len(payload["obligations"]) == 1
    assert payload["obligations"][0]["name"] == "Rent"


def test_safe_to_spend_endpoint_blocks_other_user(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client,
        "safe-to-spend-owner",
    )
    other_user_id, _ = register_and_login(
        client,
        "safe-to-spend-other",
    )

    response = client.post(
        f"/users/{other_user_id}/safe-to-spend",
        headers=headers,
        json={
            "safety_reserve_cents": 0,
            "essential_spending_cents": 0,
            "horizon_days": 30,
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "you cannot access another user's data"
    )