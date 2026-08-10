from datetime import date, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import (
    FinancialAccount,
    PlaidItem,
    RecurringItem,
    Transaction,
    User,
)
from app.services.recurring_intelligence_service import (
    evaluate_recurring_intelligence,
)
from tests.conftest import TestingSessionLocal


TEST_DATE = date(2026, 8, 9)


def create_user(
    db: Session,
    email_prefix: str = "recurring-intel",
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
    available_balance_cents: int = 500_000,
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
    normalized_merchant: str,
    amount_cents: int,
    next_payment: date,
    frequency: str = "Monthly",
    status: str = "active",
    confidence_score: float = 90.0,
    category: str | None = "Bills",
) -> RecurringItem:
    item = RecurringItem(
        user_id=user.id,
        merchant=merchant,
        normalized_merchant=normalized_merchant,
        category=category,
        amount_cents=amount_cents,
        frequency=frequency,
        last_payment=next_payment - timedelta(days=30),
        next_payment=next_payment,
        status=status,
        confidence_score=confidence_score,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def create_transaction(
    db: Session,
    user: User,
    *,
    posted_on: date,
    amount_cents: int,
    merchant_name: str,
    category: str = "Bills",
    pending: bool = False,
) -> Transaction:
    transaction = Transaction(
        user_id=user.id,
        posted_on=posted_on,
        description=merchant_name,
        merchant_name=merchant_name,
        amount_cents=amount_cents,
        category=category,
        pending=pending,
    )
    db.add(transaction)
    db.commit()
    db.refresh(transaction)
    return transaction


def register_and_login(
    client: TestClient,
    prefix: str,
) -> tuple[int, dict[str, str]]:
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


def test_no_recurring_items_returns_empty_result() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "no-items")
        create_account(db, user)

        result = evaluate_recurring_intelligence(db, user.id, as_of=TEST_DATE)

        assert result.burden.active_recurring_count == 0
        assert result.burden.monthly_recurring_cents == 0
        assert result.upcoming == []
        assert result.amount_changes == []
        assert result.new_recurring == []
        assert result.possibly_missing == []
        assert result.possible_duplicates == []
        assert result.data_quality_note == (
            "No active recurring items were found."
        )


def test_stable_recurring_amount_not_flagged() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "stable")
        create_account(db, user)
        create_recurring_item(
            db,
            user,
            merchant="Netflix",
            normalized_merchant="NETFLIX",
            amount_cents=1_500,
            next_payment=date(2026, 8, 15),
        )
        for month in (4, 5, 6, 7):
            create_transaction(
                db,
                user,
                posted_on=date(2026, month, 15),
                amount_cents=-1_500,
                merchant_name="Netflix",
            )

        result = evaluate_recurring_intelligence(db, user.id, as_of=TEST_DATE)

        assert result.amount_changes == []
        assert result.new_recurring == []


def test_meaningful_increase_flagged() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "increase")
        create_account(db, user)
        create_recurring_item(
            db,
            user,
            merchant="Netflix",
            normalized_merchant="NETFLIX",
            amount_cents=1_800,
            next_payment=date(2026, 8, 15),
        )
        for month, amount in zip((4, 5, 6, 7), (1_500, 1_500, 1_500, 1_800)):
            create_transaction(
                db,
                user,
                posted_on=date(2026, month, 15),
                amount_cents=-amount,
                merchant_name="Netflix",
            )

        result = evaluate_recurring_intelligence(db, user.id, as_of=TEST_DATE)

        assert len(result.amount_changes) == 1
        change = result.amount_changes[0]
        assert change.status == "increased"
        assert change.baseline_amount_cents == 1_500
        assert change.current_amount_cents == 1_800
        assert change.change_cents == 300
        assert change.change_percent == 20.0
        assert change.occurrences_considered == 4


def test_meaningful_decrease_flagged() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "decrease")
        create_account(db, user)
        create_recurring_item(
            db,
            user,
            merchant="Gym",
            normalized_merchant="GYM",
            amount_cents=1_600,
            next_payment=date(2026, 8, 15),
        )
        for month, amount in zip((4, 5, 6, 7), (2_000, 2_000, 2_000, 1_600)):
            create_transaction(
                db,
                user,
                posted_on=date(2026, month, 15),
                amount_cents=-amount,
                merchant_name="Gym",
            )

        result = evaluate_recurring_intelligence(db, user.id, as_of=TEST_DATE)

        assert len(result.amount_changes) == 1
        change = result.amount_changes[0]
        assert change.status == "decreased"
        assert change.baseline_amount_cents == 2_000
        assert change.current_amount_cents == 1_600
        assert change.change_cents == -400
        assert change.change_percent == -20.0


def test_tiny_change_ignored() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "tiny-change")
        create_account(db, user)
        create_recurring_item(
            db,
            user,
            merchant="Netflix",
            normalized_merchant="NETFLIX",
            amount_cents=1_520,
            next_payment=date(2026, 8, 15),
        )
        for month, amount in zip((4, 5, 6, 7), (1_500, 1_500, 1_500, 1_520)):
            create_transaction(
                db,
                user,
                posted_on=date(2026, month, 15),
                amount_cents=-amount,
                merchant_name="Netflix",
            )

        result = evaluate_recurring_intelligence(db, user.id, as_of=TEST_DATE)

        assert result.amount_changes == []


def test_insufficient_history_never_flagged_as_change() -> None:
    # Only 3 matching transactions -- even with a huge swing between
    # them, there isn't enough history for a reliable baseline, so this
    # must surface as "new", never as a change.
    with TestingSessionLocal() as db:
        user = create_user(db, "insufficient-history")
        create_account(db, user)
        create_recurring_item(
            db,
            user,
            merchant="Widget Co",
            normalized_merchant="WIDGET CO",
            amount_cents=5_000,
            next_payment=date(2026, 8, 15),
        )
        for month, amount in zip((5, 6, 7), (1_000, 1_000, 5_000)):
            create_transaction(
                db,
                user,
                posted_on=date(2026, month, 15),
                amount_cents=-amount,
                merchant_name="Widget Co",
            )

        result = evaluate_recurring_intelligence(db, user.id, as_of=TEST_DATE)

        assert result.amount_changes == []
        assert len(result.new_recurring) == 1
        assert result.new_recurring[0].occurrences_seen == 3


def test_new_recurring_payment_reported() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "new-item")
        create_account(db, user)
        create_recurring_item(
            db,
            user,
            merchant="Widget Co",
            normalized_merchant="WIDGET CO",
            amount_cents=2_000,
            next_payment=date(2026, 8, 20),
        )
        create_transaction(
            db,
            user,
            posted_on=date(2026, 7, 20),
            amount_cents=-2_000,
            merchant_name="Widget Co",
        )

        result = evaluate_recurring_intelligence(db, user.id, as_of=TEST_DATE)

        assert len(result.new_recurring) == 1
        new_item = result.new_recurring[0]
        assert new_item.merchant == "Widget Co"
        assert new_item.occurrences_seen == 1
        assert new_item.last_payment == date(2026, 7, 20)


def test_possibly_missing_payment_flagged_with_safe_language() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "missing")
        create_account(db, user)
        create_recurring_item(
            db,
            user,
            merchant="Gym",
            normalized_merchant="GYM",
            amount_cents=4_000,
            # Monthly grace is 10 days -- 20 days overdue clears it.
            next_payment=TEST_DATE - timedelta(days=20),
        )

        result = evaluate_recurring_intelligence(db, user.id, as_of=TEST_DATE)

        assert len(result.possibly_missing) == 1
        missing = result.possibly_missing[0]
        assert missing.days_overdue == 20
        assert "has not seen" in missing.message.lower()
        assert "cancel" not in missing.message.lower()


def test_missing_payment_not_flagged_when_already_paid() -> None:
    # next_payment is stale (needs a refresh) but a real transaction
    # posted on/after it -- must not be reported as missing.
    with TestingSessionLocal() as db:
        user = create_user(db, "already-paid")
        create_account(db, user)
        stale_next_payment = TEST_DATE - timedelta(days=20)
        create_recurring_item(
            db,
            user,
            merchant="Gym",
            normalized_merchant="GYM",
            amount_cents=4_000,
            next_payment=stale_next_payment,
        )
        create_transaction(
            db,
            user,
            posted_on=stale_next_payment + timedelta(days=2),
            amount_cents=-4_000,
            merchant_name="Gym",
        )

        result = evaluate_recurring_intelligence(db, user.id, as_of=TEST_DATE)

        assert result.possibly_missing == []


def test_missing_payment_suppressed_by_near_amount_match() -> None:
    # A transaction within the recurring amount tolerance (20%, $1
    # floor) still counts as "the expected payment" even if it isn't
    # exactly equal -- amounts drift slightly (e.g. a small price
    # change) without that meaning the payment never happened.
    with TestingSessionLocal() as db:
        user = create_user(db, "near-amount-match")
        create_account(db, user)
        stale_next_payment = TEST_DATE - timedelta(days=20)
        create_recurring_item(
            db,
            user,
            merchant="Gym",
            normalized_merchant="GYM",
            amount_cents=4_000,
            next_payment=stale_next_payment,
        )
        # $42.00 vs a $40.00 expectation -- 5% off, well within the
        # 20% tolerance.
        create_transaction(
            db,
            user,
            posted_on=stale_next_payment + timedelta(days=2),
            amount_cents=-4_200,
            merchant_name="Gym",
        )

        result = evaluate_recurring_intelligence(db, user.id, as_of=TEST_DATE)

        assert result.possibly_missing == []


def test_missing_payment_not_suppressed_by_unrelated_merchant() -> None:
    # Regression: a Netflix payment goes missing, but unrelated
    # Starbucks/grocery transactions exist after the due date. Those
    # must never suppress the Netflix missing-payment signal.
    with TestingSessionLocal() as db:
        user = create_user(db, "unrelated-merchant")
        create_account(db, user)
        stale_next_payment = TEST_DATE - timedelta(days=20)
        create_recurring_item(
            db,
            user,
            merchant="Netflix",
            normalized_merchant="NETFLIX",
            amount_cents=2_000,
            next_payment=stale_next_payment,
        )
        create_transaction(
            db,
            user,
            posted_on=stale_next_payment + timedelta(days=1),
            amount_cents=-650,
            merchant_name="Starbucks",
        )
        create_transaction(
            db,
            user,
            posted_on=stale_next_payment + timedelta(days=3),
            amount_cents=-8_400,
            merchant_name="Grocery Store",
        )

        result = evaluate_recurring_intelligence(db, user.id, as_of=TEST_DATE)

        assert len(result.possibly_missing) == 1
        assert result.possibly_missing[0].merchant == "Netflix"


def test_missing_payment_not_suppressed_by_same_dollar_unrelated_charge() -> (
    None
):
    # An unrelated merchant charging the exact same dollar amount must
    # not be mistaken for the expected payment -- merchant identity
    # matters, not just the amount.
    with TestingSessionLocal() as db:
        user = create_user(db, "same-dollar-unrelated")
        create_account(db, user)
        stale_next_payment = TEST_DATE - timedelta(days=20)
        create_recurring_item(
            db,
            user,
            merchant="Netflix",
            normalized_merchant="NETFLIX",
            amount_cents=2_000,
            next_payment=stale_next_payment,
        )
        create_transaction(
            db,
            user,
            posted_on=stale_next_payment + timedelta(days=2),
            amount_cents=-2_000,
            merchant_name="Hardware Store",
        )

        result = evaluate_recurring_intelligence(db, user.id, as_of=TEST_DATE)

        assert len(result.possibly_missing) == 1
        assert result.possibly_missing[0].merchant == "Netflix"


def test_missing_payment_not_suppressed_by_wildly_different_amount() -> None:
    # Regression for the amount-tolerance bug: a same-merchant
    # transaction for a wildly different amount (e.g. a one-off $2
    # purchase from the same store as a $20 subscription) is not
    # evidence the subscription payment happened.
    with TestingSessionLocal() as db:
        user = create_user(db, "wildly-different-amount")
        create_account(db, user)
        stale_next_payment = TEST_DATE - timedelta(days=20)
        create_recurring_item(
            db,
            user,
            merchant="Netflix",
            normalized_merchant="NETFLIX",
            amount_cents=2_000,
            next_payment=stale_next_payment,
        )
        create_transaction(
            db,
            user,
            posted_on=stale_next_payment + timedelta(days=2),
            amount_cents=-200,
            merchant_name="Netflix",
        )

        result = evaluate_recurring_intelligence(db, user.id, as_of=TEST_DATE)

        assert len(result.possibly_missing) == 1
        assert result.possibly_missing[0].merchant == "Netflix"


def test_missing_payment_not_flagged_within_grace_window() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "within-grace")
        create_account(db, user)
        create_recurring_item(
            db,
            user,
            merchant="Gym",
            normalized_merchant="GYM",
            amount_cents=4_000,
            next_payment=TEST_DATE - timedelta(days=3),
        )

        result = evaluate_recurring_intelligence(db, user.id, as_of=TEST_DATE)

        assert result.possibly_missing == []


def test_duplicate_detection_strong_case() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "duplicate-strong")
        create_account(db, user)
        create_recurring_item(
            db,
            user,
            merchant="Netflix",
            normalized_merchant="NETFLIX",
            amount_cents=1_800,
            next_payment=date(2026, 8, 15),
        )
        create_recurring_item(
            db,
            user,
            merchant="Netflix.com",
            normalized_merchant="NETFLIX COM",
            amount_cents=1_850,
            next_payment=date(2026, 8, 20),
        )

        result = evaluate_recurring_intelligence(db, user.id, as_of=TEST_DATE)

        assert len(result.possible_duplicates) == 1
        pair = result.possible_duplicates[0]
        assert {pair.merchant_a, pair.merchant_b} == {
            "Netflix",
            "Netflix.com",
        }


def test_duplicate_avoided_when_amounts_differ_materially() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "duplicate-amount-mismatch")
        create_account(db, user)
        create_recurring_item(
            db,
            user,
            merchant="Amazon",
            normalized_merchant="AMAZON",
            amount_cents=500,
            next_payment=date(2026, 8, 15),
        )
        create_recurring_item(
            db,
            user,
            merchant="Amazon Web Services",
            normalized_merchant="AMAZON WEB SERVICES",
            amount_cents=15_000,
            next_payment=date(2026, 8, 20),
        )

        result = evaluate_recurring_intelligence(db, user.id, as_of=TEST_DATE)

        assert result.possible_duplicates == []


def test_duplicate_avoided_when_frequency_differs() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "duplicate-frequency-mismatch")
        create_account(db, user)
        create_recurring_item(
            db,
            user,
            merchant="Netflix",
            normalized_merchant="NETFLIX",
            amount_cents=1_800,
            next_payment=date(2026, 8, 15),
            frequency="Monthly",
        )
        create_recurring_item(
            db,
            user,
            merchant="Netflix.com",
            normalized_merchant="NETFLIX COM",
            amount_cents=1_800,
            next_payment=date(2026, 8, 13),
            frequency="Weekly",
        )

        result = evaluate_recurring_intelligence(db, user.id, as_of=TEST_DATE)

        assert result.possible_duplicates == []


def test_monthly_burden_and_income_share() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "burden")
        create_account(db, user)

        create_recurring_item(
            db,
            user,
            merchant="Gym",
            normalized_merchant="GYM",
            amount_cents=1_200,
            next_payment=date(2026, 8, 20),
            frequency="Weekly",
        )
        create_recurring_item(
            db,
            user,
            merchant="Cleaning",
            normalized_merchant="CLEANING",
            amount_cents=1_200,
            next_payment=date(2026, 8, 15),
            frequency="Biweekly",
        )
        create_recurring_item(
            db,
            user,
            merchant="Rent",
            normalized_merchant="RENT",
            amount_cents=3_000,
            next_payment=date(2026, 8, 15),
            frequency="Monthly",
        )

        for month in (5, 6, 7):
            create_transaction(
                db,
                user,
                posted_on=date(2026, month, 1),
                amount_cents=200_00,
                merchant_name="Paycheck",
                category="Income",
            )

        result = evaluate_recurring_intelligence(db, user.id, as_of=TEST_DATE)

        assert result.burden.active_recurring_count == 3
        assert result.burden.monthly_recurring_cents == 5_200 + 2_600 + 3_000
        assert result.burden.percent_of_income == round(
            result.burden.monthly_recurring_cents / 20_000 * 100, 1
        )


def test_thirty_sixty_ninety_day_obligation_totals() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "horizons")
        create_account(db, user)
        create_recurring_item(
            db,
            user,
            merchant="Rent",
            normalized_merchant="RENT",
            amount_cents=150_000,
            next_payment=date(2026, 8, 15),
            frequency="Monthly",
        )

        result = evaluate_recurring_intelligence(db, user.id, as_of=TEST_DATE)

        assert result.burden.next_30_days_cents == 150_000
        assert result.burden.next_60_days_cents == 300_000
        assert result.burden.next_90_days_cents == 450_000


def test_upcoming_obligation_fields() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "upcoming")
        create_account(db, user)
        create_recurring_item(
            db,
            user,
            merchant="Rent",
            normalized_merchant="RENT",
            amount_cents=150_000,
            next_payment=date(2026, 8, 20),
        )

        result = evaluate_recurring_intelligence(db, user.id, as_of=TEST_DATE)

        assert len(result.upcoming) == 1
        obligation = result.upcoming[0]
        assert obligation.merchant == "Rent"
        assert obligation.amount_cents == 150_000
        assert obligation.frequency == "Monthly"
        assert obligation.days_until_due == 11


def test_paused_and_dismissed_items_excluded() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "excluded-status")
        create_account(db, user)
        create_recurring_item(
            db,
            user,
            merchant="Paused Sub",
            normalized_merchant="PAUSED SUB",
            amount_cents=1_000,
            next_payment=date(2026, 8, 15),
            status="paused",
        )
        create_recurring_item(
            db,
            user,
            merchant="Dismissed Sub",
            normalized_merchant="DISMISSED SUB",
            amount_cents=1_000,
            next_payment=date(2026, 8, 15),
            status="dismissed",
        )

        result = evaluate_recurring_intelligence(db, user.id, as_of=TEST_DATE)

        assert result.burden.active_recurring_count == 0


def test_recurring_intelligence_endpoint_requires_authentication(
    client: TestClient,
) -> None:
    response = client.get("/users/1/recurring-intelligence")
    assert response.status_code == 401


def test_recurring_intelligence_endpoint_blocks_other_user(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "recurring-intel-owner")
    other_user_id, _ = register_and_login(client, "recurring-intel-other")

    response = client.get(
        f"/users/{other_user_id}/recurring-intelligence",
        headers=headers,
    )

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "you cannot access another user's data"
    )


def test_recurring_intelligence_endpoint_returns_real_data(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "recurring-intel-real")

    response = client.get(
        f"/users/{user_id}/recurring-intelligence",
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["burden"]["active_recurring_count"] == 0
    assert payload["data_quality_note"] == (
        "No active recurring items were found."
    )
