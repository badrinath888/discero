from datetime import date, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

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
from app.schemas import SafeToSpendRequest
from app.services.safe_to_spend_service import (
    calculate_current_safe_to_spend,
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
    category: str = "Bills",
    frequency: str = "Monthly",
) -> RecurringItem:
    item = RecurringItem(
        user_id=user.id,
        merchant=merchant,
        normalized_merchant=f"{merchant.upper()}-{uuid4().hex}",
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
    db.refresh(budget)

    return budget


def create_spend_transaction(
    db: Session,
    user: User,
    *,
    posted_on: date,
    amount_cents: int,
    category: str,
) -> Transaction:
    transaction = Transaction(
        user_id=user.id,
        posted_on=posted_on,
        description="Test spend",
        amount_cents=-abs(amount_cents),
        category=category,
    )

    db.add(transaction)
    db.commit()
    db.refresh(transaction)

    return transaction


def create_income_transaction(
    db: Session,
    user: User,
    *,
    posted_on: date,
    amount_cents: int,
) -> Transaction:
    transaction = Transaction(
        user_id=user.id,
        posted_on=posted_on,
        description="Test income",
        amount_cents=abs(amount_cents),
        category="Income",
    )

    db.add(transaction)
    db.commit()
    db.refresh(transaction)

    return transaction


def create_goal(
    db: Session,
    user: User,
    *,
    target_cents: int,
    target_date: date | None,
    saved_cents: int = 0,
    name: str = "Test Goal",
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


def test_includes_remaining_monthly_budget_obligation() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "budget-remaining")

        create_account(
            db,
            user,
            available_balance_cents=500_000,
        )

        create_budget(
            db,
            user,
            category="Groceries",
            month="2026-08",
            limit_cents=50_000,
        )

        result = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(),
            as_of=TEST_DATE,
        )

        assert len(result.obligations) == 1

        obligation = result.obligations[0]

        assert obligation.source == "budget"
        assert obligation.category == "Groceries"
        assert obligation.name == "Groceries budget"
        assert obligation.amount_cents == 50_000
        assert result.breakdown.upcoming_obligations_cents == 50_000


def test_partially_spent_budget_subtracts_remaining_amount_only() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "budget-partial")

        create_account(
            db,
            user,
            available_balance_cents=500_000,
        )

        create_budget(
            db,
            user,
            category="Groceries",
            month="2026-08",
            limit_cents=50_000,
        )

        create_spend_transaction(
            db,
            user,
            posted_on=TEST_DATE,
            amount_cents=20_000,
            category="Groceries",
        )

        result = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(),
            as_of=TEST_DATE,
        )

        assert len(result.obligations) == 1
        assert result.obligations[0].amount_cents == 30_000


def test_fully_spent_budget_is_excluded() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "budget-full")

        create_account(
            db,
            user,
            available_balance_cents=500_000,
        )

        create_budget(
            db,
            user,
            category="Groceries",
            month="2026-08",
            limit_cents=50_000,
        )

        create_spend_transaction(
            db,
            user,
            posted_on=TEST_DATE,
            amount_cents=50_000,
            category="Groceries",
        )

        result = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(),
            as_of=TEST_DATE,
        )

        assert result.obligations == []


def test_overspent_budget_is_excluded() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "budget-overspent")

        create_account(
            db,
            user,
            available_balance_cents=500_000,
        )

        create_budget(
            db,
            user,
            category="Groceries",
            month="2026-08",
            limit_cents=50_000,
        )

        create_spend_transaction(
            db,
            user,
            posted_on=TEST_DATE,
            amount_cents=70_000,
            category="Groceries",
        )

        result = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(),
            as_of=TEST_DATE,
        )

        assert result.obligations == []


def test_budget_spending_outside_its_own_month_is_ignored() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "budget-month-scope")

        create_account(
            db,
            user,
            available_balance_cents=500_000,
        )

        create_budget(
            db,
            user,
            category="Groceries",
            month="2026-08",
            limit_cents=50_000,
        )

        create_spend_transaction(
            db,
            user,
            posted_on=date(2026, 7, 15),
            amount_cents=40_000,
            category="Groceries",
        )

        result = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(),
            as_of=TEST_DATE,
        )

        assert len(result.obligations) == 1
        assert result.obligations[0].amount_cents == 50_000


def test_budget_obligations_ignore_another_users_data() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "budget-owner")
        other_user = create_user(db, "budget-other-owner")

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

        create_budget(
            db,
            other_user,
            category="Groceries",
            month="2026-08",
            limit_cents=100_000,
        )

        create_spend_transaction(
            db,
            other_user,
            posted_on=TEST_DATE,
            amount_cents=10_000,
            category="Groceries",
        )

        result = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(),
            as_of=TEST_DATE,
        )

        assert result.obligations == []
        assert result.breakdown.upcoming_obligations_cents == 0


def test_budget_outside_horizon_is_excluded() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "budget-outside-horizon")

        create_account(
            db,
            user,
            available_balance_cents=500_000,
        )

        create_budget(
            db,
            user,
            category="Travel",
            month="2026-10",
            limit_cents=100_000,
        )

        result = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(horizon_days=30),
            as_of=TEST_DATE,
        )

        assert result.obligations == []


def test_horizon_crossing_months_includes_applicable_budgets() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "budget-crossing-months")
        as_of = date(2026, 8, 25)

        create_account(
            db,
            user,
            available_balance_cents=500_000,
        )

        create_budget(
            db,
            user,
            category="Groceries",
            month="2026-08",
            limit_cents=40_000,
        )

        create_budget(
            db,
            user,
            category="Dining",
            month="2026-09",
            limit_cents=30_000,
        )

        result = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(horizon_days=10),
            as_of=as_of,
        )

        assert result.through_date == date(2026, 9, 4)
        assert len(result.obligations) == 2

        by_category = {
            obligation.category: obligation
            for obligation in result.obligations
        }

        assert by_category["Groceries"].amount_cents == 40_000
        assert by_category["Groceries"].expected_date == date(
            2026, 8, 31
        )
        assert by_category["Dining"].amount_cents == 30_000
        assert by_category["Dining"].expected_date == date(
            2026, 9, 4
        )


def test_matching_recurring_expense_reduces_budget_obligation() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "offset-partial")

        create_account(
            db,
            user,
            available_balance_cents=500_000,
        )

        create_recurring_item(
            db,
            user,
            merchant="Rent",
            amount_cents=60_000,
            next_payment=TEST_DATE + timedelta(days=5),
            category="Housing",
        )

        create_budget(
            db,
            user,
            category="Housing",
            month="2026-08",
            limit_cents=100_000,
        )

        result = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(),
            as_of=TEST_DATE,
        )

        recurring = [
            o for o in result.obligations if o.source == "recurring"
        ]
        budget = [
            o for o in result.obligations if o.source == "budget"
        ]

        assert len(recurring) == 1
        assert recurring[0].amount_cents == 60_000

        assert len(budget) == 1
        assert budget[0].amount_cents == 40_000
        assert result.breakdown.upcoming_obligations_cents == 100_000


def test_recurring_equal_to_remaining_budget_removes_obligation() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "offset-equal")

        create_account(
            db,
            user,
            available_balance_cents=500_000,
        )

        create_recurring_item(
            db,
            user,
            merchant="Rent",
            amount_cents=100_000,
            next_payment=TEST_DATE + timedelta(days=5),
            category="Housing",
        )

        create_budget(
            db,
            user,
            category="Housing",
            month="2026-08",
            limit_cents=100_000,
        )

        result = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(),
            as_of=TEST_DATE,
        )

        budget = [
            o for o in result.obligations if o.source == "budget"
        ]

        assert budget == []
        assert result.breakdown.upcoming_obligations_cents == 100_000


def test_recurring_larger_than_budget_removes_obligation() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "offset-larger")

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
            category="Housing",
        )

        create_budget(
            db,
            user,
            category="Housing",
            month="2026-08",
            limit_cents=100_000,
        )

        result = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(),
            as_of=TEST_DATE,
        )

        budget = [
            o for o in result.obligations if o.source == "budget"
        ]
        recurring = [
            o for o in result.obligations if o.source == "recurring"
        ]

        assert budget == []
        assert len(recurring) == 1
        assert recurring[0].amount_cents == 150_000
        assert result.breakdown.upcoming_obligations_cents == 150_000


def test_different_categories_are_not_offset() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "offset-different-category")

        create_account(
            db,
            user,
            available_balance_cents=500_000,
        )

        create_recurring_item(
            db,
            user,
            merchant="Streaming",
            amount_cents=50_000,
            next_payment=TEST_DATE + timedelta(days=5),
            category="Entertainment",
        )

        create_budget(
            db,
            user,
            category="Housing",
            month="2026-08",
            limit_cents=100_000,
        )

        result = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(),
            as_of=TEST_DATE,
        )

        budget = [
            o for o in result.obligations if o.source == "budget"
        ]

        assert len(budget) == 1
        assert budget[0].amount_cents == 100_000
        assert result.breakdown.upcoming_obligations_cents == 150_000


def test_recurring_in_another_month_is_not_offset() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "offset-different-month")

        create_account(
            db,
            user,
            available_balance_cents=500_000,
        )

        create_recurring_item(
            db,
            user,
            merchant="Rent",
            amount_cents=90_000,
            next_payment=date(2026, 9, 2),
            category="Housing",
        )

        create_budget(
            db,
            user,
            category="Housing",
            month="2026-08",
            limit_cents=100_000,
        )

        result = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(horizon_days=30),
            as_of=TEST_DATE,
        )

        budget = [
            o for o in result.obligations if o.source == "budget"
        ]

        assert len(budget) == 1
        assert budget[0].amount_cents == 100_000
        assert result.breakdown.upcoming_obligations_cents == 190_000


def test_category_offset_matching_is_case_insensitive() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "offset-case-insensitive")

        create_account(
            db,
            user,
            available_balance_cents=500_000,
        )

        create_recurring_item(
            db,
            user,
            merchant="Rent",
            amount_cents=60_000,
            next_payment=TEST_DATE + timedelta(days=5),
            category="  housing  ",
        )

        create_budget(
            db,
            user,
            category="Housing",
            month="2026-08",
            limit_cents=100_000,
        )

        result = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(),
            as_of=TEST_DATE,
        )

        budget = [
            o for o in result.obligations if o.source == "budget"
        ]

        assert len(budget) == 1
        assert budget[0].amount_cents == 40_000


def test_recurring_and_budget_obligations_combine() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "budget-and-recurring")

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

        create_budget(
            db,
            user,
            category="Groceries",
            month="2026-08",
            limit_cents=50_000,
        )

        result = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(),
            as_of=TEST_DATE,
        )

        assert len(result.obligations) == 2
        assert result.breakdown.upcoming_obligations_cents == 200_000

        sources = {
            obligation.source for obligation in result.obligations
        }

        assert sources == {"recurring", "budget"}
        assert result.warnings == []


def test_no_obligations_warning_only_when_both_kinds_are_absent() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "budget-warning")

        create_account(
            db,
            user,
            available_balance_cents=500_000,
        )

        create_budget(
            db,
            user,
            category="Groceries",
            month="2026-08",
            limit_cents=50_000,
        )

        result = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(),
            as_of=TEST_DATE,
        )

        assert not any(
            "recurring" in warning.lower()
            for warning in result.warnings
        )

        no_obligations_result = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(),
            as_of=date(2026, 12, 1),
        )

        assert any(
            "no active recurring or budget obligations" in warning.lower()
            for warning in no_obligations_result.warnings
        )


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


def test_safe_to_spend_endpoint_includes_budget_source(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client,
        "safe-to-spend-budget-endpoint",
    )
    current_month = date.today().strftime("%Y-%m")

    with TestingSessionLocal() as db:
        user = db.get(User, user_id)

        assert user is not None

        create_account(
            db,
            user,
            available_balance_cents=500_000,
        )

        create_budget(
            db,
            user,
            category="Groceries",
            month=current_month,
            limit_cents=50_000,
        )

    response = client.post(
        f"/users/{user_id}/safe-to-spend",
        headers=headers,
        json={
            "safety_reserve_cents": 0,
            "essential_spending_cents": 0,
            "horizon_days": 30,
        },
    )

    assert response.status_code == 200

    payload = response.json()
    budget_obligations = [
        obligation
        for obligation in payload["obligations"]
        if obligation["source"] == "budget"
    ]

    assert len(budget_obligations) == 1
    assert budget_obligations[0]["category"] == "Groceries"
    assert budget_obligations[0]["amount_cents"] == 50_000
    assert budget_obligations[0]["name"] == "Groceries budget"


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

# --- Multi-occurrence recurring obligations (recurrence-horizon fix) -----


def test_monthly_bill_counted_once_in_thirty_day_horizon() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "monthly-30")
        create_account(db, user)
        create_recurring_item(
            db,
            user,
            merchant="Rent",
            amount_cents=150_000,
            next_payment=date(2026, 8, 15),
        )

        result = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(horizon_days=30),
            as_of=TEST_DATE,
        )

        assert result.breakdown.upcoming_obligations_cents == 150_000
        recurring = [o for o in result.obligations if o.source == "recurring"]
        assert [o.expected_date for o in recurring] == [date(2026, 8, 15)]


def test_monthly_bill_counted_twice_in_sixty_day_horizon() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "monthly-60")
        create_account(db, user)
        create_recurring_item(
            db,
            user,
            merchant="Rent",
            amount_cents=150_000,
            next_payment=date(2026, 8, 15),
        )

        result = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(horizon_days=60),
            as_of=TEST_DATE,
        )

        assert result.breakdown.upcoming_obligations_cents == 300_000
        recurring = [o for o in result.obligations if o.source == "recurring"]
        assert [o.expected_date for o in recurring] == [
            date(2026, 8, 15),
            date(2026, 9, 15),
        ]


def test_monthly_bill_counted_three_times_in_ninety_day_horizon() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "monthly-90")
        create_account(db, user)
        create_recurring_item(
            db,
            user,
            merchant="Rent",
            amount_cents=150_000,
            next_payment=date(2026, 8, 15),
        )

        result = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(horizon_days=90),
            as_of=TEST_DATE,
        )

        assert result.breakdown.upcoming_obligations_cents == 450_000
        recurring = [o for o in result.obligations if o.source == "recurring"]
        assert [o.expected_date for o in recurring] == [
            date(2026, 8, 15),
            date(2026, 9, 15),
            date(2026, 10, 15),
        ]


def test_weekly_bill_counts_every_occurrence_in_horizon() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "weekly")
        create_account(db, user)
        create_recurring_item(
            db,
            user,
            merchant="Groceries",
            amount_cents=8_000,
            next_payment=date(2026, 8, 6),
            frequency="Weekly",
        )

        result = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(horizon_days=30),
            as_of=TEST_DATE,
        )

        # Aug 6, 13, 20, 27, Sep 3 -- 5 occurrences.
        assert result.breakdown.upcoming_obligations_cents == 40_000
        recurring = [o for o in result.obligations if o.source == "recurring"]
        assert len(recurring) == 5


def test_biweekly_bill_counts_every_occurrence_in_horizon() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "biweekly")
        create_account(db, user)
        create_recurring_item(
            db,
            user,
            merchant="Cleaning",
            amount_cents=12_000,
            next_payment=date(2026, 8, 5),
            frequency="Biweekly",
        )

        result = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(horizon_days=60),
            as_of=TEST_DATE,
        )

        # Aug 5, 19, Sep 2, 16, 30 -- 5 occurrences.
        assert result.breakdown.upcoming_obligations_cents == 60_000
        recurring = [o for o in result.obligations if o.source == "recurring"]
        assert len(recurring) == 5


def test_stale_next_payment_still_counts_future_occurrence() -> None:
    """next_payment before as_of (sync lag) must not hide a real
    future occurrence once projected forward -- and must never count
    anything before as_of either."""
    with TestingSessionLocal() as db:
        user = create_user(db, "stale-next-payment")
        create_account(db, user)
        create_recurring_item(
            db,
            user,
            merchant="Rent",
            amount_cents=150_000,
            next_payment=date(2026, 7, 15),  # before TEST_DATE
        )

        result = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(horizon_days=30),
            as_of=TEST_DATE,
        )

        recurring = [o for o in result.obligations if o.source == "recurring"]
        assert [o.expected_date for o in recurring] == [date(2026, 8, 15)]
        assert all(o.expected_date >= TEST_DATE for o in recurring)


def test_next_payment_exactly_on_through_date_is_included() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "boundary-through")
        create_account(db, user)
        create_recurring_item(
            db,
            user,
            merchant="Rent",
            amount_cents=150_000,
            next_payment=date(2026, 9, 3),  # exactly as_of + 30 days
        )

        result = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(horizon_days=30),
            as_of=TEST_DATE,
        )

        assert result.through_date == date(2026, 9, 3)
        assert result.breakdown.upcoming_obligations_cents == 150_000


def test_next_payment_just_after_through_date_is_excluded() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "boundary-after")
        create_account(db, user)
        create_recurring_item(
            db,
            user,
            merchant="Rent",
            amount_cents=150_000,
            next_payment=date(2026, 9, 4),  # one day past horizon
        )

        result = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(horizon_days=30),
            as_of=TEST_DATE,
        )

        assert result.breakdown.upcoming_obligations_cents == 0


def test_inactive_recurring_item_never_counted() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "inactive")
        create_account(db, user)
        create_recurring_item(
            db,
            user,
            merchant="Cancelled Gym",
            amount_cents=150_000,
            next_payment=date(2026, 8, 15),
            status="dismissed",
        )

        result = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(horizon_days=90),
            as_of=TEST_DATE,
        )

        assert result.breakdown.upcoming_obligations_cents == 0


def test_zero_amount_recurring_item_contributes_nothing() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "zero-amount")
        create_account(db, user)
        create_recurring_item(
            db,
            user,
            merchant="Free Trial",
            amount_cents=0,
            next_payment=date(2026, 8, 15),
        )

        result = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(horizon_days=90),
            as_of=TEST_DATE,
        )

        assert result.breakdown.upcoming_obligations_cents == 0
        recurring = [o for o in result.obligations if o.source == "recurring"]
        # Still projected/listed (three $0 occurrences) -- just
        # financially inert, not silently dropped from the breakdown.
        assert len(recurring) == 3


def test_multiple_distinct_recurring_items_each_count_independently() -> (
    None
):
    with TestingSessionLocal() as db:
        user = create_user(db, "multiple-items")
        create_account(db, user)
        create_recurring_item(
            db,
            user,
            merchant="Rent",
            amount_cents=150_000,
            next_payment=date(2026, 8, 15),
        )
        create_recurring_item(
            db,
            user,
            merchant="Rent",
            amount_cents=150_000,
            next_payment=date(2026, 8, 15),
        )

        result = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(horizon_days=30),
            as_of=TEST_DATE,
        )

        # Two separate records with identical merchant/amount/date
        # still both count -- not deduplicated.
        assert result.breakdown.upcoming_obligations_cents == 300_000
        recurring = [o for o in result.obligations if o.source == "recurring"]
        assert len(recurring) == 2


def test_unsupported_frequency_falls_back_to_single_occurrence() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "unsupported-frequency")
        create_account(db, user)
        create_recurring_item(
            db,
            user,
            merchant="Insurance",
            amount_cents=150_000,
            next_payment=date(2026, 8, 15),
            frequency="Quarterly",
        )

        result = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(horizon_days=90),
            as_of=TEST_DATE,
        )

        # Never fabricates a quarterly cadence -- only the one known
        # date is counted, even across a 90-day horizon.
        assert result.breakdown.upcoming_obligations_cents == 150_000
        recurring = [o for o in result.obligations if o.source == "recurring"]
        assert len(recurring) == 1


def test_goal_reserve_ignored_unless_requested() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "goal-reserve-default")

        create_account(db, user, available_balance_cents=500_000)
        create_goal(
            db,
            user,
            target_cents=200_000,
            target_date=date(2026, 10, 4),
        )

        default_result = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(),
            as_of=TEST_DATE,
        )

        assert default_result.breakdown.goal_reserve_cents == 0
        assert default_result.safe_to_spend_cents == 500_000


def test_goal_reserve_included_when_requested() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "goal-reserve-included")

        create_account(db, user, available_balance_cents=500_000)
        # 200,000 remaining over 2 months (Aug 4 -> Oct 4) -> 100,000/mo,
        # fully within a 30-day horizon.
        create_goal(
            db,
            user,
            target_cents=200_000,
            target_date=date(2026, 10, 4),
        )

        result = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(include_goal_reserve=True),
            as_of=TEST_DATE,
        )

        assert result.breakdown.goal_reserve_cents == 100_000
        assert result.safe_to_spend_cents == 400_000


def test_multiple_goals_combine_into_goal_reserve() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "multi-goal-reserve")

        create_account(db, user, available_balance_cents=1_000_000)
        create_goal(
            db,
            user,
            target_cents=200_000,
            target_date=date(2026, 10, 4),
        )
        create_goal(
            db,
            user,
            target_cents=90_000,
            target_date=date(2026, 9, 4),
        )

        result = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(include_goal_reserve=True),
            as_of=TEST_DATE,
        )

        # goal 1: 200,000 / 2 months = 100,000; goal 2: 90,000 / 1 month
        # = 90,000.
        assert result.breakdown.goal_reserve_cents == 190_000


def test_completed_goal_is_not_reserved() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "completed-goal")

        create_account(db, user, available_balance_cents=500_000)
        create_goal(
            db,
            user,
            target_cents=100_000,
            saved_cents=100_000,
            target_date=date(2026, 10, 4),
        )

        result = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(include_goal_reserve=True),
            as_of=TEST_DATE,
        )

        assert result.breakdown.goal_reserve_cents == 0


def test_projected_income_ignored_unless_requested() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "income-default")

        create_account(db, user, available_balance_cents=200_000)
        create_income_transaction(
            db,
            user,
            posted_on=date(2026, 7, 15),
            amount_cents=300_000,
        )

        default_result = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(),
            as_of=TEST_DATE,
        )

        assert default_result.breakdown.projected_income_cents == 0


def test_projected_income_included_when_requested() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "income-included")

        create_account(db, user, available_balance_cents=200_000)
        create_income_transaction(
            db,
            user,
            posted_on=date(2026, 7, 15),
            amount_cents=300_000,
        )

        result = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(include_projected_income=True),
            as_of=TEST_DATE,
        )

        assert result.breakdown.projected_income_cents == 300_000
        assert result.safe_to_spend_cents == 500_000


def test_projected_income_excludes_current_month() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "income-current-month")

        create_account(db, user, available_balance_cents=200_000)
        create_income_transaction(
            db,
            user,
            posted_on=TEST_DATE,
            amount_cents=900_000,
        )

        result = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(include_projected_income=True),
            as_of=TEST_DATE,
        )

        # Only COMPLETED months are averaged -- the in-progress current
        # month is never counted as realized income.
        assert result.breakdown.projected_income_cents == 0


def test_safe_to_spend_never_negative_with_goals_and_income() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "shortfall-with-goal-and-income")

        create_account(db, user, available_balance_cents=100_000)
        create_recurring_item(
            db,
            user,
            merchant="Rent",
            amount_cents=150_000,
            next_payment=TEST_DATE + timedelta(days=5),
        )
        create_goal(
            db,
            user,
            target_cents=200_000,
            target_date=date(2026, 10, 4),
        )

        result = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(
                include_goal_reserve=True,
                include_projected_income=True,
            ),
            as_of=TEST_DATE,
        )

        assert result.safe_to_spend_cents == 0
        assert result.shortfall_cents == 150_000


def test_confidence_drivers_reflect_recognized_data() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "confidence-drivers-positive")

        create_account(db, user, available_balance_cents=500_000)
        create_recurring_item(
            db,
            user,
            merchant="Rent",
            amount_cents=150_000,
            next_payment=TEST_DATE + timedelta(days=5),
            confidence_score=95.0,
        )

        result = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(),
            as_of=TEST_DATE,
        )

        assert result.confidence_level in {"high", "medium", "low"}
        codes = {driver.code for driver in result.confidence_drivers}
        assert "LIQUID_BALANCE_FOUND" in codes
        assert "OBLIGATIONS_WELL_RECOGNIZED" in codes


def test_confidence_drivers_flag_missing_data() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "confidence-drivers-negative")

        result = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(),
            as_of=TEST_DATE,
        )

        codes = {driver.code for driver in result.confidence_drivers}
        assert "NO_LIQUID_BALANCE" in codes
        assert "NO_OBLIGATIONS_RECOGNIZED" in codes


def test_explanation_reflects_shortfall() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "explanation-shortfall")

        create_account(db, user, available_balance_cents=50_000)
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
            SafeToSpendRequest(),
            as_of=TEST_DATE,
        )

        codes = [item.code for item in result.explanation]
        assert "SHORTFALL" in codes
        assert "RESULT" not in codes


def test_explanation_reflects_positive_result() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "explanation-positive")

        create_account(db, user, available_balance_cents=500_000)

        result = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(),
            as_of=TEST_DATE,
        )

        codes = [item.code for item in result.explanation]
        assert "RESULT" in codes
        assert "SHORTFALL" not in codes
        assert codes[-1] == "CONFIDENCE"


def test_safe_to_spend_endpoint_includes_income_and_goal_reserve(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client,
        "safe-to-spend-v2-endpoint",
    )

    with TestingSessionLocal() as db:
        user = db.get(User, user_id)

        assert user is not None

        create_account(db, user, available_balance_cents=500_000)
        create_goal(
            db,
            user,
            target_cents=200_000,
            target_date=date.today() + timedelta(days=200),
        )
        create_income_transaction(
            db,
            user,
            posted_on=date.today().replace(day=1) - timedelta(days=1),
            amount_cents=100_000,
        )

    response = client.post(
        f"/users/{user_id}/safe-to-spend",
        headers=headers,
        json={
            "safety_reserve_cents": 0,
            "essential_spending_cents": 0,
            "horizon_days": 30,
            "include_projected_income": True,
            "include_goal_reserve": True,
        },
    )

    assert response.status_code == 200

    payload = response.json()

    assert payload["breakdown"]["goal_reserve_cents"] > 0
    assert payload["breakdown"]["projected_income_cents"] == 100_000
    assert payload["confidence_level"] in {"high", "medium", "low"}
    assert isinstance(payload["confidence_drivers"], list)
    assert isinstance(payload["explanation"], list)


def test_current_safe_to_spend_diverges_from_bare_default() -> None:
    """Regression fixture for the production Overview-vs-Copilot
    mismatch: with a goal and income present, the canonical CURRENT
    calculation (always enriched) and the bare-default
    `SafeToSpendRequest()` calculation (both flags False) must
    disagree. This is the exact shape of bug that shipped: a caller
    silently using the unenriched defaults instead of the canonical
    current-safe-to-spend path.
    """
    with TestingSessionLocal() as db:
        user = create_user(db, "current-vs-default-divergence")

        create_account(db, user, available_balance_cents=500_000)
        create_goal(
            db,
            user,
            target_cents=200_000,
            target_date=date(2026, 10, 4),
        )
        create_income_transaction(
            db,
            user,
            posted_on=date(2026, 7, 15),
            amount_cents=300_000,
        )

        current = calculate_current_safe_to_spend(
            db,
            user.id,
            as_of=TEST_DATE,
        )
        bare_default = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(),
            as_of=TEST_DATE,
        )

        assert current.breakdown.projected_income_cents == 300_000
        assert current.breakdown.goal_reserve_cents == 100_000
        assert bare_default.breakdown.projected_income_cents == 0
        assert bare_default.breakdown.goal_reserve_cents == 0
        assert current.safe_to_spend_cents != bare_default.safe_to_spend_cents


def test_current_safe_to_spend_honors_user_provided_assumptions() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "current-honors-user-assumptions")

        create_account(db, user, available_balance_cents=500_000)

        result = calculate_current_safe_to_spend(
            db,
            user.id,
            safety_reserve_cents=50_000,
            essential_spending_cents=25_000,
            horizon_days=45,
            as_of=TEST_DATE,
        )

        assert result.breakdown.safety_reserve_cents == 50_000
        assert result.breakdown.essential_spending_cents == 25_000
        assert result.horizon_days == 45


def test_scenario_default_request_still_excludes_income_and_goal_reserve() -> (
    None
):
    """Guards that `calculate_safe_to_spend`'s global defaults -- what
    every scenario caller (Major Purchase, Buy Now vs Wait, Stress
    Test, Recommendations, Scenario Comparison, What-If, Goal
    Conflict) relies on -- are unchanged by the new
    `calculate_current_safe_to_spend` wrapper.
    """
    with TestingSessionLocal() as db:
        user = create_user(db, "scenario-defaults-unchanged")

        create_account(db, user, available_balance_cents=500_000)
        create_goal(
            db,
            user,
            target_cents=200_000,
            target_date=date(2026, 10, 4),
        )
        create_income_transaction(
            db,
            user,
            posted_on=date(2026, 7, 15),
            amount_cents=300_000,
        )

        result = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(),
            as_of=TEST_DATE,
        )

        assert result.breakdown.projected_income_cents == 0
        assert result.breakdown.goal_reserve_cents == 0


def test_current_safe_to_spend_endpoint_ignores_client_supplied_flags(
    client: TestClient,
) -> None:
    """The Overview dashboard endpoint always returns the canonical
    enriched CURRENT figure -- even if a request body explicitly sends
    include_projected_income/include_goal_reserve as False, or omits
    them entirely.
    """
    user_id, headers = register_and_login(
        client,
        "current-flag-independent",
    )

    with TestingSessionLocal() as db:
        user = db.get(User, user_id)

        assert user is not None

        create_account(db, user, available_balance_cents=500_000)
        create_goal(
            db,
            user,
            target_cents=200_000,
            target_date=date.today() + timedelta(days=60),
        )
        create_income_transaction(
            db,
            user,
            posted_on=date.today().replace(day=1) - timedelta(days=1),
            amount_cents=100_000,
        )

    for body_flags in (
        {},
        {"include_projected_income": False, "include_goal_reserve": False},
    ):
        response = client.post(
            f"/users/{user_id}/safe-to-spend",
            headers=headers,
            json={
                "safety_reserve_cents": 0,
                "essential_spending_cents": 0,
                "horizon_days": 30,
                **body_flags,
            },
        )

        assert response.status_code == 200

        payload = response.json()

        assert payload["breakdown"]["goal_reserve_cents"] > 0
        assert payload["breakdown"]["projected_income_cents"] == 100_000
