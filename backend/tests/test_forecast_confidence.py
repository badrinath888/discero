from datetime import date, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import (
    Budget,
    FinancialAccount,
    PlaidItem,
    Transaction,
    User,
)
from app.recurring import detect_recurring
from app.services.forecast_confidence_service import (
    _FACTOR_WEIGHTS,
    _confidence_level,
    calculate_forecast_confidence,
)
from tests.conftest import TestingSessionLocal


def create_user(
    db: Session,
    email_prefix: str = "forecast-confidence",
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
    available_balance_cents: int | None = 100_000,
    current_balance_cents: int | None = 100_000,
    status: str = "active",
) -> FinancialAccount:
    item = PlaidItem(
        user_id=user.id,
        provider_item_id=f"item-{uuid4().hex}",
        access_token_ciphertext="encrypted-test-token",
        status=status,
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

    return account


def create_transaction(
    db: Session,
    user: User,
    *,
    posted_on: date,
    amount_cents: int,
    merchant: str,
    category: str = "General",
) -> Transaction:
    transaction = Transaction(
        user_id=user.id,
        posted_on=posted_on,
        description=merchant,
        merchant_name=merchant,
        amount_cents=amount_cents,
        category=category,
    )

    db.add(transaction)
    db.commit()

    return transaction


def create_budget(
    db: Session,
    user: User,
    *,
    category: str,
    month: str,
    limit_cents: int,
) -> Budget:
    budget = Budget(
        user_id=user.id,
        category=category,
        month=month,
        limit_cents=limit_cents,
    )

    db.add(budget)
    db.commit()

    return budget


def _seed_strong_data(db: Session, user: User) -> None:
    create_account(db, user, available_balance_cents=500_000)
    create_account(db, user, available_balance_cents=200_000)

    create_budget(
        db,
        user,
        category="Groceries",
        month="2026-08",
        limit_cents=100_000,
    )

    for month in range(2, 9):
        create_transaction(
            db,
            user,
            posted_on=date(2026, month, 1),
            amount_cents=250_000,
            merchant="Employer Payroll",
            category="Income",
        )
        create_transaction(
            db,
            user,
            posted_on=date(2026, month, 1),
            amount_cents=-120_000,
            merchant="Rent Payment",
            category="Housing",
        )

        for day in (3, 6, 9, 12, 15, 18, 21, 24, 27):
            create_transaction(
                db,
                user,
                posted_on=date(2026, month, day),
                amount_cents=-5_000,
                merchant=f"Groceries day {day}",
                category="Groceries",
            )

    create_transaction(
        db,
        user,
        posted_on=date(2026, 8, 14),
        amount_cents=-2_000,
        merchant="Coffee Shop",
        category="Dining",
    )


def test_high_confidence_forecast_with_strong_data(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    with TestingSessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None

        _seed_strong_data(db, user)

    response = client.get(
        f"/users/{user_id}/summary/cash-flow-forecast",
        params={"as_of": "2026-08-15"},
        headers=auth_headers,
    )

    assert response.status_code == 200

    confidence = response.json()["confidence"]

    assert confidence["level"] == "high"
    assert confidence["score"] >= 80
    assert len(confidence["factors"]) == 10
    assert sum(
        factor["weight"] for factor in confidence["factors"]
    ) == 100
    assert confidence["recommendations"] == []
    assert len(confidence["monthly_confidence"]) > 0

    for entry in confidence["monthly_confidence"]:
        assert 0 <= entry["score"] <= 100
        assert entry["transaction_count"] > 0


def test_medium_confidence_forecast_with_partial_data(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    with TestingSessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None

        create_account(db, user, available_balance_cents=50_000)

        create_transaction(
            db,
            user,
            posted_on=date(2026, 5, 5),
            amount_cents=200_000,
            merchant="Payroll",
            category="Income",
        )
        create_transaction(
            db,
            user,
            posted_on=date(2026, 6, 5),
            amount_cents=200_000,
            merchant="Payroll",
            category="Income",
        )
        create_transaction(
            db,
            user,
            posted_on=date(2026, 7, 5),
            amount_cents=200_000,
            merchant="Payroll",
            category="Income",
        )

        create_transaction(
            db,
            user,
            posted_on=date(2026, 5, 10),
            amount_cents=-60_000,
            merchant="Spend A",
            category="Shopping",
        )
        create_transaction(
            db,
            user,
            posted_on=date(2026, 6, 10),
            amount_cents=-100_000,
            merchant="Spend B",
            category="Shopping",
        )
        create_transaction(
            db,
            user,
            posted_on=date(2026, 7, 10),
            amount_cents=-160_000,
            merchant="Spend C",
            category="Shopping",
        )

        create_transaction(
            db,
            user,
            posted_on=date(2026, 8, 15) - timedelta(days=130),
            amount_cents=-1_000,
            merchant="Old One",
            category="Misc",
        )

        for index, day in enumerate([1, 3, 6, 9, 12, 14]):
            create_transaction(
                db,
                user,
                posted_on=date(2026, 8, day),
                amount_cents=-2_000 - index * 100,
                merchant=f"Recent {index}",
                category="Misc",
            )

    response = client.get(
        f"/users/{user_id}/summary/cash-flow-forecast",
        params={"as_of": "2026-08-15"},
        headers=auth_headers,
    )

    assert response.status_code == 200

    confidence = response.json()["confidence"]

    assert confidence["level"] == "medium"
    assert 55 <= confidence["score"] < 80


def test_low_confidence_forecast_with_sparse_data(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    response = client.get(
        f"/users/{user_id}/summary/cash-flow-forecast",
        params={"as_of": "2026-08-15"},
        headers=auth_headers,
    )

    assert response.status_code == 200

    confidence = response.json()["confidence"]

    assert confidence["level"] == "low"
    assert confidence["score"] < 30
    assert len(confidence["recommendations"]) > 0
    assert confidence["monthly_confidence"] == []


def test_confidence_decreases_for_longer_horizon(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    with TestingSessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None

        create_account(db, user, available_balance_cents=100_000)

        for offset in range(20):
            create_transaction(
                db,
                user,
                posted_on=date(2025, 12, 1) + timedelta(days=offset * 5),
                amount_cents=-1_000,
                merchant=f"Old {offset}",
                category="Misc",
            )

    early_response = client.get(
        f"/users/{user_id}/summary/cash-flow-forecast",
        params={"as_of": "2026-08-02"},
        headers=auth_headers,
    )
    late_response = client.get(
        f"/users/{user_id}/summary/cash-flow-forecast",
        params={"as_of": "2026-08-30"},
        headers=auth_headers,
    )

    assert early_response.status_code == 200
    assert late_response.status_code == 200

    early_confidence = early_response.json()["confidence"]
    late_confidence = late_response.json()["confidence"]

    early_horizon_factor = next(
        factor
        for factor in early_confidence["factors"]
        if factor["key"] == "horizon_length"
    )
    late_horizon_factor = next(
        factor
        for factor in late_confidence["factors"]
        if factor["key"] == "horizon_length"
    )

    assert early_horizon_factor["score"] < late_horizon_factor["score"]
    assert early_confidence["score"] < late_confidence["score"]


def test_existing_forecast_behavior_still_works_alongside_confidence(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    with TestingSessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None

        item = PlaidItem(
            user_id=user.id,
            provider_item_id="existing-behavior-item",
            access_token_ciphertext="encrypted",
            status="active",
        )
        db.add(item)
        db.flush()

        db.add(
            FinancialAccount(
                plaid_item_id=item.id,
                provider_account_id="existing-behavior-checking",
                name="Checking",
                account_type="depository",
                current_balance_cents=125_000,
                available_balance_cents=120_000,
                currency="USD",
            )
        )
        db.commit()

    response = client.get(
        f"/users/{user_id}/summary/cash-flow-forecast",
        params={"as_of": "2026-02-28"},
        headers=auth_headers,
    )

    assert response.status_code == 200

    body = response.json()

    assert body["as_of"] == "2026-02-28"
    assert body["month_end"] == "2026-02-28"
    assert body["days_remaining"] == 0
    assert body["liquid_balance_cents"] == 120000
    assert body["expected_income_cents"] == 0
    assert body["upcoming_bills_cents"] == 0
    assert body["projected_end_balance_cents"] == 120000
    assert body["low_balance_risk"] is False

    assert "confidence" in body
    assert 0 <= body["confidence"]["score"] <= 100
    assert body["confidence"]["level"] in ("high", "medium", "low")


def _confidence_for_transactions(
    db: Session,
    user: User,
    *,
    as_of: date,
    accounts: list[FinancialAccount],
):
    transactions = list(
        db.query(Transaction)
        .filter(Transaction.user_id == user.id)
        .all()
    )
    recurring = detect_recurring(transactions, as_of=as_of)

    return calculate_forecast_confidence(
        db,
        user.id,
        as_of=as_of,
        days_remaining=16,
        days_in_month=31,
        transactions=transactions,
        liquid_accounts=accounts,
        recurring_items=recurring,
    )


def test_stale_or_missing_balances_reduce_confidence() -> None:
    as_of = date(2026, 8, 15)

    with TestingSessionLocal() as db:
        fresh_user = create_user(db, "fresh-balances")
        fresh_account = create_account(
            db,
            fresh_user,
            available_balance_cents=100_000,
        )
        create_transaction(
            db,
            fresh_user,
            posted_on=date(2026, 6, 1),
            amount_cents=200_000,
            merchant="Payroll",
            category="Income",
        )
        create_transaction(
            db,
            fresh_user,
            posted_on=as_of - timedelta(days=1),
            amount_cents=-50_000,
            merchant="Recent spend",
            category="Shopping",
        )

        stale_user = create_user(db, "stale-balances")
        stale_account = create_account(
            db,
            stale_user,
            available_balance_cents=None,
            current_balance_cents=None,
        )
        create_transaction(
            db,
            stale_user,
            posted_on=date(2026, 6, 1),
            amount_cents=200_000,
            merchant="Payroll",
            category="Income",
        )
        create_transaction(
            db,
            stale_user,
            posted_on=date(2026, 6, 5),
            amount_cents=-50_000,
            merchant="Old spend",
            category="Shopping",
        )

        fresh_result = _confidence_for_transactions(
            db,
            fresh_user,
            as_of=as_of,
            accounts=[fresh_account],
        )
        stale_result = _confidence_for_transactions(
            db,
            stale_user,
            as_of=as_of,
            accounts=[stale_account],
        )

        fresh_missing = next(
            f for f in fresh_result.factors if f.key == "missing_balances"
        )
        stale_missing = next(
            f for f in stale_result.factors if f.key == "missing_balances"
        )
        fresh_stale = next(
            f for f in fresh_result.factors if f.key == "stale_data"
        )
        stale_stale = next(
            f for f in stale_result.factors if f.key == "stale_data"
        )

        assert stale_missing.score < fresh_missing.score
        assert stale_stale.score < fresh_stale.score
        assert stale_result.score < fresh_result.score


def test_low_recurring_confidence_reduces_confidence() -> None:
    as_of = date(2026, 8, 15)

    with TestingSessionLocal() as db:
        jittery_user = create_user(db, "jittery-recurring")
        jittery_account = create_account(db, jittery_user)

        for posted_on, amount in [
            (date(2026, 5, 1), -1_100),
            (date(2026, 5, 25), -1_500),
            (date(2026, 7, 1), -1_050),
            (date(2026, 8, 8), -1_450),
        ]:
            create_transaction(
                db,
                jittery_user,
                posted_on=posted_on,
                amount_cents=amount,
                merchant="Netflix",
                category="Subscriptions",
            )

        regular_user = create_user(db, "regular-recurring")
        regular_account = create_account(db, regular_user)

        for month in range(5, 9):
            create_transaction(
                db,
                regular_user,
                posted_on=date(2026, month, 1),
                amount_cents=-1_500,
                merchant="Netflix",
                category="Subscriptions",
            )

        jittery_result = _confidence_for_transactions(
            db,
            jittery_user,
            as_of=as_of,
            accounts=[jittery_account],
        )
        regular_result = _confidence_for_transactions(
            db,
            regular_user,
            as_of=as_of,
            accounts=[regular_account],
        )

        jittery_recurring = next(
            f
            for f in jittery_result.factors
            if f.key == "recurring_confidence"
        )
        regular_recurring = next(
            f
            for f in regular_result.factors
            if f.key == "recurring_confidence"
        )

        assert jittery_recurring.score < regular_recurring.score
        assert jittery_result.score < regular_result.score


def test_volatile_spending_reduces_confidence() -> None:
    as_of = date(2026, 8, 15)

    with TestingSessionLocal() as db:
        volatile_user = create_user(db, "volatile-spending")
        volatile_account = create_account(db, volatile_user)

        for month, amount in [
            (5, -20_000),
            (6, -200_000),
            (7, -20_000),
        ]:
            create_transaction(
                db,
                volatile_user,
                posted_on=date(2026, month, 1),
                amount_cents=200_000,
                merchant="Payroll",
                category="Income",
            )
            create_transaction(
                db,
                volatile_user,
                posted_on=date(2026, month, 10),
                amount_cents=amount,
                merchant="Spend",
                category="Shopping",
            )

        stable_user = create_user(db, "stable-spending")
        stable_account = create_account(db, stable_user)

        for month in (5, 6, 7):
            create_transaction(
                db,
                stable_user,
                posted_on=date(2026, month, 1),
                amount_cents=200_000,
                merchant="Payroll",
                category="Income",
            )
            create_transaction(
                db,
                stable_user,
                posted_on=date(2026, month, 10),
                amount_cents=-80_000,
                merchant="Spend",
                category="Shopping",
            )

        volatile_result = _confidence_for_transactions(
            db,
            volatile_user,
            as_of=as_of,
            accounts=[volatile_account],
        )
        stable_result = _confidence_for_transactions(
            db,
            stable_user,
            as_of=as_of,
            accounts=[stable_account],
        )

        volatile_factor = next(
            f
            for f in volatile_result.factors
            if f.key == "spending_volatility"
        )
        stable_factor = next(
            f
            for f in stable_result.factors
            if f.key == "spending_volatility"
        )

        assert volatile_factor.score < stable_factor.score
        assert volatile_result.score < stable_result.score


def test_confidence_level_thresholds() -> None:
    assert _confidence_level(100.0) == "high"
    assert _confidence_level(80.0) == "high"
    assert _confidence_level(79.9) == "medium"
    assert _confidence_level(55.0) == "medium"
    assert _confidence_level(54.9) == "low"
    assert _confidence_level(0.0) == "low"


def test_factor_weights_sum_to_one_hundred() -> None:
    assert sum(_FACTOR_WEIGHTS.values()) == 100.0
