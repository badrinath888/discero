from datetime import date
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.models import (
    Budget,
    FinancialAccount,
    PlaidItem,
    RecurringItem,
    SavingsGoal,
    Transaction,
    User,
)
from app.schemas import BuyNowVsWaitRequest
from app.services.buy_now_vs_wait_service import evaluate_buy_now_vs_wait
from tests.conftest import TestingSessionLocal


TEST_DATE = date(2026, 8, 9)


def create_user(db: Session, prefix: str = "buy-now-vs-wait") -> User:
    user = User(
        email=f"{prefix}-{uuid4().hex}@example.com",
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
    next_payment: date,
    amount_cents: int,
    confidence_score: float = 90.0,
) -> RecurringItem:
    item = RecurringItem(
        user_id=user.id,
        merchant=f"Bill-{uuid4().hex[:8]}",
        normalized_merchant=f"bill-{uuid4().hex}",
        amount_cents=amount_cents,
        frequency="Monthly",
        last_payment=next_payment,
        next_payment=next_payment,
        status="active",
        confidence_score=confidence_score,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def create_budget(
    db: Session,
    user: User,
    *,
    month: str,
    limit_cents: int,
    category: str = "Shopping",
) -> Budget:
    budget = Budget(
        user_id=user.id,
        category=category,
        month=month,
        limit_cents=limit_cents,
    )
    db.add(budget)
    db.commit()
    db.refresh(budget)
    return budget


def seed_income(
    db: Session, user: User, *, monthly_amount_cents: int = 200_000
) -> None:
    for month in (5, 6, 7):
        db.add(
            Transaction(
                user_id=user.id,
                financial_account_id=None,
                amount_cents=monthly_amount_cents,
                posted_on=date(2026, month, 15),
                description="Paycheck",
                category="income",
            )
        )
    db.commit()


def create_goal(
    db: Session,
    user: User,
    *,
    target_cents: int,
    target_date: date,
) -> SavingsGoal:
    goal = SavingsGoal(
        user_id=user.id,
        name="Goal",
        target_cents=target_cents,
        saved_cents=0,
        target_date=target_date,
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


def test_both_affordable_now_better() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "now-better")
        create_account(db, user, available_balance_cents=500_000)
        # Falls outside NOW's [Aug9, Sep8] window, inside WAIT's
        # [Sep13, Oct13] window -- waiting means this bill comes due
        # first and eats into the buffer.
        create_recurring_item(
            db, user, next_payment=date(2026, 9, 20), amount_cents=100_000
        )

        result = evaluate_buy_now_vs_wait(
            db,
            user.id,
            BuyNowVsWaitRequest(
                purchase_name="TV",
                purchase_amount_cents=100_000,
                buy_now_date=date(2026, 8, 11),
                wait_until_date=date(2026, 9, 13),
                horizon_days=30,
            ),
            as_of=TEST_DATE,
        )

        assert result.now.simulation.affordability_status == "affordable"
        assert result.wait.simulation.affordability_status == "affordable"
        assert result.buffer_difference_cents == -100_000
        assert result.recommended_timing == "buy_now"
        assert result.key_driver == "buffer"
        assert "$1,000.00" in result.reason


def test_both_affordable_wait_better() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "wait-better")
        create_account(db, user, available_balance_cents=500_000)
        # A RECURRING bill can no longer be "avoided" by waiting a few
        # weeks -- it just recurs at its next cadence step instead (see
        # test_recurring_monthly_bill_recurs_in_both_now_and_wait
        # below), so this scenario now uses a calendar-month-scoped
        # BUDGET obligation instead: August's budget genuinely does
        # not apply once WAIT's evaluation date has rolled into
        # September.
        create_budget(db, user, month="2026-08", limit_cents=100_000)

        result = evaluate_buy_now_vs_wait(
            db,
            user.id,
            BuyNowVsWaitRequest(
                purchase_name="TV",
                purchase_amount_cents=100_000,
                buy_now_date=date(2026, 8, 11),
                wait_until_date=date(2026, 9, 5),
                horizon_days=30,
            ),
            as_of=TEST_DATE,
        )

        assert result.now.simulation.affordability_status == "affordable"
        assert result.wait.simulation.affordability_status == "affordable"
        assert result.buffer_difference_cents == 100_000
        assert result.recommended_timing == "wait"
        assert result.key_driver == "buffer"
        assert "$1,000.00" in result.reason
        assert result.caveat is None
        # Short horizon and no confidence drop -- the base methodology
        # disclosure must still be present and unembellished.
        assert (
            "does not predict the income or spending" in result.assumption
        )
        assert "directional rather than a precise forecast" not in (
            result.assumption
        )


def test_now_unaffordable_wait_affordable() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "now-unaffordable")
        create_account(db, user, available_balance_cents=300_000)
        # See test_both_affordable_wait_better -- a budget obligation
        # is used here for the same reason (a recurring bill would now
        # correctly recur in both windows instead of disappearing).
        create_budget(db, user, month="2026-08", limit_cents=250_000)

        result = evaluate_buy_now_vs_wait(
            db,
            user.id,
            BuyNowVsWaitRequest(
                purchase_name="Appliance",
                purchase_amount_cents=60_000,
                buy_now_date=date(2026, 8, 11),
                wait_until_date=date(2026, 9, 5),
                horizon_days=30,
            ),
            as_of=TEST_DATE,
        )

        assert result.now.simulation.affordability_status == "not_affordable"
        assert result.wait.simulation.affordability_status != "not_affordable"
        assert result.recommended_timing == "wait"
        assert result.key_driver == "affordability"


def test_recurring_monthly_bill_recurs_in_both_now_and_wait() -> None:
    """Regression test for the recurrence-counting fix, updated for the
    Time-Aware Engine 2.0 known-cashflow advance.

    A recurring bill due before WAIT's evaluation date is no longer
    dropped from WAIT's obligations entirely (single stored
    `next_payment`, not projected forward) -- its next monthly
    occurrence correctly lands inside WAIT's own horizon window too.
    But a real monthly bill due BEFORE the wait date (Aug 14, inside
    the [today, wait date) gap) will genuinely already have been paid
    by the time the wait date arrives -- WAIT 2.0 now advances the
    known balance across that gap, so WAIT correctly ends up paying
    for BOTH the Aug 14 occurrence (via the advance) and the Sep 14
    occurrence (inside its own horizon), while NOW's own horizon only
    ever reaches the single Aug 14 occurrence. Waiting is genuinely
    worse here, by exactly one bill -- it is no longer misrepresented
    as equivalent.
    """
    with TestingSessionLocal() as db:
        user = create_user(db, "recurs-both")
        create_account(db, user, available_balance_cents=500_000)
        # Due Aug 14 -- inside NOW's [Aug9, Sep8] window AND inside the
        # gap WAIT 2.0 advances across ([Aug9, Aug29)). Its next
        # monthly occurrence, Sep 14, falls inside WAIT's own
        # [Aug29, Sep28] horizon window too.
        create_recurring_item(
            db, user, next_payment=date(2026, 8, 14), amount_cents=100_000
        )

        result = evaluate_buy_now_vs_wait(
            db,
            user.id,
            BuyNowVsWaitRequest(
                purchase_name="TV",
                purchase_amount_cents=100_000,
                buy_now_date=date(2026, 8, 11),
                wait_until_date=date(2026, 8, 29),
                horizon_days=30,
            ),
            as_of=TEST_DATE,
        )

        now_obligation = next(
            o
            for o in result.now.simulation.safe_to_spend.obligations
            if o.source == "recurring"
        )
        wait_obligation = next(
            o
            for o in result.wait.simulation.safe_to_spend.obligations
            if o.source == "recurring"
        )
        assert now_obligation.expected_date == date(2026, 8, 14)
        assert wait_obligation.expected_date == date(2026, 9, 14)
        assert now_obligation.amount_cents == wait_obligation.amount_cents

        # WAIT is worse by exactly one bill: the Aug 14 occurrence
        # already paid via the gap advance, on top of the Sep 14
        # occurrence still inside its own horizon.
        assert result.buffer_difference_cents == -100_000
        assert result.recommended_timing == "buy_now"
        assert result.key_driver == "buffer"
        assert "$1,000.00" in result.reason


def test_both_unaffordable() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "both-unaffordable")
        create_account(db, user, available_balance_cents=100_000)

        result = evaluate_buy_now_vs_wait(
            db,
            user.id,
            BuyNowVsWaitRequest(
                purchase_name="Car",
                purchase_amount_cents=200_000,
                buy_now_date=date(2026, 8, 11),
                wait_until_date=date(2026, 8, 20),
                horizon_days=30,
            ),
            as_of=TEST_DATE,
        )

        assert result.now.simulation.affordability_status == "not_affordable"
        assert result.wait.simulation.affordability_status == "not_affordable"
        assert result.recommended_timing == "neither"
        assert result.key_driver == "affordability"


def test_effectively_equivalent_outcomes() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "equivalent")
        create_account(db, user, available_balance_cents=500_000)

        result = evaluate_buy_now_vs_wait(
            db,
            user.id,
            BuyNowVsWaitRequest(
                purchase_name="Furniture",
                purchase_amount_cents=100_000,
                buy_now_date=date(2026, 8, 11),
                wait_until_date=date(2026, 8, 20),
                horizon_days=30,
            ),
            as_of=TEST_DATE,
        )

        assert result.buffer_difference_cents == 0
        assert result.recommended_timing == "either"
        assert result.key_driver == "equivalent"
        assert result.caveat is None
        assert "not financially meaningful" in result.reason


def test_future_horizon_lower_confidence_adds_caveat() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "low-confidence")
        create_account(db, user, available_balance_cents=500_000)
        # Small amount (stays under the buffer materiality threshold)
        # but a low confidence score, only inside WAIT's window.
        create_recurring_item(
            db,
            user,
            next_payment=date(2026, 9, 10),
            amount_cents=1_000,
            confidence_score=20.0,
        )

        result = evaluate_buy_now_vs_wait(
            db,
            user.id,
            BuyNowVsWaitRequest(
                purchase_name="Gadget",
                purchase_amount_cents=50_000,
                buy_now_date=date(2026, 8, 11),
                wait_until_date=date(2026, 8, 29),
                horizon_days=30,
            ),
            as_of=TEST_DATE,
        )

        assert result.confidence_difference <= -10
        assert result.key_driver == "confidence"
        assert result.recommended_timing == "buy_now"
        # Confidence-drop case: the base assumption is still present,
        # PLUS the stronger, conditional confidence warning.
        assert (
            "does not predict the income or spending" in result.assumption
        )
        assert result.caveat is not None
        assert "directional" in result.caveat


def test_long_wait_horizon_strengthens_assumption_wording() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "long-horizon")
        create_account(db, user, available_balance_cents=500_000)

        result = evaluate_buy_now_vs_wait(
            db,
            user.id,
            BuyNowVsWaitRequest(
                purchase_name="Furniture",
                purchase_amount_cents=100_000,
                buy_now_date=date(2026, 8, 11),
                wait_until_date=date(2026, 9, 28),
                horizon_days=30,
            ),
            as_of=TEST_DATE,
        )

        assert result.recommended_timing == "either"
        # No confidence drop here -- the long-horizon disclosure lives
        # in `assumption`, not a conditional `caveat`.
        assert result.caveat is None
        assert "does not predict the income or spending" in result.assumption
        assert "directional rather than a precise forecast" in (
            result.assumption
        )


def test_invalid_wait_date_before_buy_now_date() -> None:
    with pytest.raises(ValidationError):
        BuyNowVsWaitRequest(
            purchase_name="TV",
            purchase_amount_cents=100_000,
            buy_now_date=date(2026, 8, 20),
            wait_until_date=date(2026, 8, 10),
        )


def test_invalid_wait_date_equal_to_buy_now_date() -> None:
    with pytest.raises(ValidationError):
        BuyNowVsWaitRequest(
            purchase_name="TV",
            purchase_amount_cents=100_000,
            buy_now_date=date(2026, 8, 20),
            wait_until_date=date(2026, 8, 20),
        )


def test_buy_now_date_before_calculation_date_rejected() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "past-buy-date")
        create_account(db, user)

        with pytest.raises(ValueError):
            evaluate_buy_now_vs_wait(
                db,
                user.id,
                BuyNowVsWaitRequest(
                    purchase_name="TV",
                    purchase_amount_cents=100_000,
                    buy_now_date=date(2026, 8, 1),
                    wait_until_date=date(2026, 8, 20),
                ),
                as_of=TEST_DATE,
            )


def test_goal_impact_differs_between_now_and_wait() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "goal-impact")
        create_account(db, user, available_balance_cents=300_000)
        seed_income(db, user, monthly_amount_cents=200_000)
        create_goal(
            db, user, target_cents=600_000, target_date=date(2027, 8, 9)
        )
        # Inside NOW's window AND inside the gap WAIT 2.0 advances
        # across -- this bill genuinely reduces the balance available
        # by the wait date too, just not as sharply as it reduces
        # NOW's own tighter capacity window.
        create_recurring_item(
            db, user, next_payment=date(2026, 8, 14), amount_cents=100_000
        )

        result = evaluate_buy_now_vs_wait(
            db,
            user.id,
            BuyNowVsWaitRequest(
                purchase_name="Appliance",
                purchase_amount_cents=250_000,
                buy_now_date=date(2026, 8, 11),
                wait_until_date=date(2026, 8, 29),
                horizon_days=30,
            ),
            as_of=TEST_DATE,
        )

        now_delay = result.now.simulation.goal_impacts[0].delay_months
        wait_delay = result.wait.simulation.goal_impacts[0].delay_months

        # Waiting is still less disruptive to the goal than buying now
        # (the bill and the purchase compete less tightly for capacity
        # from the advanced-forward vantage point), but it is no
        # longer misrepresented as having zero impact -- the known
        # bill is visible to WAIT too now.
        assert now_delay > 0
        assert wait_delay > 0
        assert now_delay > wait_delay
        assert result.goal_impact_note is not None
        assert "Buying now delays your goals" in result.goal_impact_note


def test_no_fabricated_caveat_when_nothing_warrants_one() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "no-fabrication")
        create_account(db, user, available_balance_cents=500_000)

        result = evaluate_buy_now_vs_wait(
            db,
            user.id,
            BuyNowVsWaitRequest(
                purchase_name="Furniture",
                purchase_amount_cents=100_000,
                buy_now_date=date(2026, 8, 11),
                wait_until_date=date(2026, 8, 20),
                horizon_days=30,
            ),
            as_of=TEST_DATE,
        )

        assert result.caveat is None
        assert result.confidence_difference == 0.0
        # The methodology assumption is not a "caveat" -- it's always
        # present, plain, and not fabricated into alarming language
        # just because nothing else warrants a warning.
        assert (
            "does not predict the income or spending" in result.assumption
        )
        assert "directional rather than a precise forecast" not in (
            result.assumption
        )


def test_wait_advances_liquid_balance_before_purchase() -> None:
    """The core Time-Aware Engine 2.0 fix: WAIT's starting balance for
    its own safe-to-spend window must already reflect a known
    obligation due before the wait date, not the unmodified current
    balance re-labeled with a future date.
    """
    with TestingSessionLocal() as db:
        user = create_user(db, "wait-advances")
        create_account(db, user, available_balance_cents=500_000)
        create_recurring_item(
            db, user, next_payment=date(2026, 8, 14), amount_cents=75_000
        )

        result = evaluate_buy_now_vs_wait(
            db,
            user.id,
            BuyNowVsWaitRequest(
                purchase_name="Gadget",
                purchase_amount_cents=1_000,
                buy_now_date=date(2026, 8, 11),
                wait_until_date=date(2026, 8, 29),
                horizon_days=30,
            ),
            as_of=TEST_DATE,
        )

        assert (
            result.wait.simulation.safe_to_spend.breakdown.liquid_balance_cents
            == 425_000
        )
        assert (
            "known recurring obligations and projected income"
            in result.assumption
        )


def test_wait_horizon_obligations_still_counted_after_advance() -> None:
    """A bill inside the gap AND a separate bill inside WAIT's own
    post-wait horizon must both be reflected -- the advance must never
    replace or shadow WAIT's own safe-to-spend obligations window.
    """
    with TestingSessionLocal() as db:
        user = create_user(db, "wait-both-windows")
        create_account(db, user, available_balance_cents=500_000)
        # Inside the gap [Aug9, Aug29).
        create_recurring_item(
            db, user, next_payment=date(2026, 8, 14), amount_cents=50_000
        )
        # Inside WAIT's own [Aug29, Sep28] horizon, outside the gap.
        create_recurring_item(
            db, user, next_payment=date(2026, 9, 5), amount_cents=30_000
        )

        result = evaluate_buy_now_vs_wait(
            db,
            user.id,
            BuyNowVsWaitRequest(
                purchase_name="Gadget",
                purchase_amount_cents=1_000,
                buy_now_date=date(2026, 8, 11),
                wait_until_date=date(2026, 8, 29),
                horizon_days=30,
            ),
            as_of=TEST_DATE,
        )

        # 500_000 - 50_000 (Aug 14 occurrence, via the gap advance)
        # - 50_000 (its next Sep 14 occurrence, inside WAIT's own
        # horizon) - 30_000 (the Sep 5 bill, also inside WAIT's own
        # horizon) - 1_000 (purchase) = 369_000.
        assert (
            result.wait.simulation.safe_to_spend_after_purchase_cents
            == 369_000
        )


def test_buy_now_vs_wait_endpoint_blocks_other_user(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "bnw-owner")

    response = client.post(
        f"/users/{user_id + 1}/major-purchase/buy-now-vs-wait",
        headers=headers,
        json={
            "purchase_name": "TV",
            "purchase_amount_cents": 100_000,
            "buy_now_date": "2026-08-11",
            "wait_until_date": "2026-08-20",
        },
    )

    assert response.status_code == 403


def test_buy_now_vs_wait_endpoint_returns_real_result(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "bnw-endpoint")

    response = client.post(
        f"/users/{user_id}/major-purchase/buy-now-vs-wait",
        headers=headers,
        json={
            "purchase_name": "Furniture",
            "purchase_amount_cents": 100_000,
            "buy_now_date": str(date.today()),
            "wait_until_date": str(date.today().replace(day=28)),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["recommended_timing"] in (
        "buy_now",
        "wait",
        "either",
        "neither",
    )
    assert "now" in body and "wait" in body


def test_buy_now_vs_wait_endpoint_rejects_invalid_dates(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "bnw-invalid")

    response = client.post(
        f"/users/{user_id}/major-purchase/buy-now-vs-wait",
        headers=headers,
        json={
            "purchase_name": "TV",
            "purchase_amount_cents": 100_000,
            "buy_now_date": "2026-08-20",
            "wait_until_date": "2026-08-10",
        },
    )

    assert response.status_code == 422
