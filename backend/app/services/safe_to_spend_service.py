from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Budget,
    FinancialAccount,
    PlaidItem,
    RecurringItem,
    Transaction,
)
from app.schemas import (
    SafeToSpendBreakdownOut,
    SafeToSpendObligationOut,
    SafeToSpendOut,
    SafeToSpendRequest,
)

LIQUID_ACCOUNT_TYPES = {
    "depository",
    "cash",
}

BUDGET_OBLIGATION_CONFIDENCE_SCORE = 75.0


def calculate_safe_to_spend(
    db: Session,
    user_id: int,
    payload: SafeToSpendRequest,
    *,
    as_of: date | None = None,
) -> SafeToSpendOut:
    calculation_date = as_of or date.today()
    through_date = calculation_date + timedelta(
        days=payload.horizon_days
    )

    liquid_balance_cents, balance_warnings = _get_liquid_balance(
        db,
        user_id,
    )

    recurring_obligations = _get_upcoming_obligations(
        db,
        user_id,
        calculation_date,
        through_date,
    )

    budget_obligations = _get_budget_obligations(
        db,
        user_id,
        calculation_date,
        through_date,
        recurring_obligations,
    )

    obligations = sorted(
        recurring_obligations + budget_obligations,
        key=lambda obligation: (
            obligation.expected_date,
            obligation.source,
            obligation.name,
        ),
    )

    upcoming_obligations_cents = sum(
        obligation.amount_cents
        for obligation in obligations
    )

    raw_safe_to_spend_cents = (
        liquid_balance_cents
        - upcoming_obligations_cents
        - payload.essential_spending_cents
        - payload.safety_reserve_cents
    )

    safe_to_spend_cents = max(
        raw_safe_to_spend_cents,
        0,
    )
    shortfall_cents = max(
        -raw_safe_to_spend_cents,
        0,
    )

    warnings = list(balance_warnings)

    if not recurring_obligations and not budget_obligations:
        warnings.append(
            "No active recurring or budget obligations were "
            "found for the selected period."
        )

    confidence_score = _calculate_confidence(
        obligations,
        has_liquid_balance=liquid_balance_cents > 0,
    )

    return SafeToSpendOut(
        as_of=calculation_date,
        through_date=through_date,
        horizon_days=payload.horizon_days,
        safe_to_spend_cents=safe_to_spend_cents,
        shortfall_cents=shortfall_cents,
        status=_determine_status(
            raw_safe_to_spend_cents,
            liquid_balance_cents,
        ),
        confidence_score=confidence_score,
        breakdown=SafeToSpendBreakdownOut(
            liquid_balance_cents=liquid_balance_cents,
            upcoming_obligations_cents=(
                upcoming_obligations_cents
            ),
            essential_spending_cents=(
                payload.essential_spending_cents
            ),
            safety_reserve_cents=(
                payload.safety_reserve_cents
            ),
        ),
        obligations=obligations,
        warnings=warnings,
    )


def _get_liquid_balance(
    db: Session,
    user_id: int,
) -> tuple[int, list[str]]:
    statement = (
        select(FinancialAccount)
        .join(
            PlaidItem,
            FinancialAccount.plaid_item_id == PlaidItem.id,
        )
        .where(
            PlaidItem.user_id == user_id,
            PlaidItem.status == "active",
            FinancialAccount.account_type.in_(
                LIQUID_ACCOUNT_TYPES
            ),
        )
    )

    accounts = list(db.scalars(statement).all())
    warnings: list[str] = []

    if not accounts:
        warnings.append(
            "No active liquid accounts were found."
        )
        return 0, warnings

    balance_cents = 0

    for account in accounts:
        if account.available_balance_cents is not None:
            balance_cents += account.available_balance_cents
            continue

        if account.current_balance_cents is not None:
            balance_cents += account.current_balance_cents
            warnings.append(
                f"{account.name} used its current balance because "
                "an available balance was not provided."
            )
            continue

        warnings.append(
            f"{account.name} was excluded because no balance "
            "was available."
        )

    return balance_cents, warnings


def _get_upcoming_obligations(
    db: Session,
    user_id: int,
    as_of: date,
    through_date: date,
) -> list[SafeToSpendObligationOut]:
    statement = (
        select(RecurringItem)
        .where(
            RecurringItem.user_id == user_id,
            RecurringItem.status == "active",
            RecurringItem.next_payment >= as_of,
            RecurringItem.next_payment <= through_date,
        )
        .order_by(
            RecurringItem.next_payment,
            RecurringItem.id,
        )
    )

    items = list(db.scalars(statement).all())

    return [
        SafeToSpendObligationOut(
            name=item.merchant,
            amount_cents=item.amount_cents,
            expected_date=item.next_payment,
            category=item.category,
            confidence_score=item.confidence_score,
            source="recurring",
        )
        for item in items
    ]


def _get_budget_obligations(
    db: Session,
    user_id: int,
    as_of: date,
    through_date: date,
    recurring_obligations: list[SafeToSpendObligationOut],
) -> list[SafeToSpendObligationOut]:
    months = _months_in_range(as_of, through_date)

    budgets = list(
        db.scalars(
            select(Budget)
            .where(
                Budget.user_id == user_id,
                Budget.month.in_(months),
            )
            .order_by(Budget.month, Budget.category)
        ).all()
    )

    if not budgets:
        return []

    spent_by_month_category = _get_spent_by_month_category(
        db,
        user_id,
        {budget.month for budget in budgets},
    )

    recurring_by_month_category = _get_recurring_by_month_category(
        recurring_obligations,
    )

    obligations = []

    for budget in budgets:
        spent_cents = spent_by_month_category.get(
            (budget.month, budget.category),
            0,
        )
        remaining_cents = budget.limit_cents - spent_cents

        if remaining_cents <= 0:
            continue

        matching_recurring_cents = recurring_by_month_category.get(
            (budget.month, _normalize_category(budget.category)),
            0,
        )

        adjusted_remaining_cents = max(
            remaining_cents - matching_recurring_cents,
            0,
        )

        if adjusted_remaining_cents <= 0:
            continue

        _, month_end = _month_bounds(budget.month)
        month_last_day = month_end - timedelta(days=1)
        expected_date = min(month_last_day, through_date)

        obligations.append(
            SafeToSpendObligationOut(
                name=f"{budget.category} budget",
                amount_cents=adjusted_remaining_cents,
                expected_date=expected_date,
                category=budget.category,
                confidence_score=BUDGET_OBLIGATION_CONFIDENCE_SCORE,
                source="budget",
            )
        )

    return obligations


def _get_recurring_by_month_category(
    recurring_obligations: list[SafeToSpendObligationOut],
) -> dict[tuple[str, str], int]:
    recurring_by_month_category: dict[tuple[str, str], int] = {}

    for obligation in recurring_obligations:
        month = (
            f"{obligation.expected_date.year:04d}"
            f"-{obligation.expected_date.month:02d}"
        )
        key = (month, _normalize_category(obligation.category))
        recurring_by_month_category[key] = (
            recurring_by_month_category.get(key, 0)
            + obligation.amount_cents
        )

    return recurring_by_month_category


def _normalize_category(category: str | None) -> str:
    if category is None:
        return ""

    return " ".join(category.split()).lower()


def _get_spent_by_month_category(
    db: Session,
    user_id: int,
    months: set[str],
) -> dict[tuple[str, str], int]:
    spent_by_month_category: dict[tuple[str, str], int] = {}

    for month in months:
        start, end = _month_bounds(month)

        statement = select(Transaction).where(
            Transaction.user_id == user_id,
            Transaction.posted_on >= start,
            Transaction.posted_on < end,
            Transaction.amount_cents < 0,
        )

        for transaction in db.scalars(statement).all():
            key = (month, transaction.category)
            spent_by_month_category[key] = (
                spent_by_month_category.get(key, 0)
                + abs(transaction.amount_cents)
            )

    return spent_by_month_category


def _months_in_range(as_of: date, through_date: date) -> list[str]:
    months = []
    year, month_number = as_of.year, as_of.month

    while (year, month_number) <= (
        through_date.year,
        through_date.month,
    ):
        months.append(f"{year:04d}-{month_number:02d}")

        if month_number == 12:
            year += 1
            month_number = 1
        else:
            month_number += 1

    return months


def _month_bounds(month: str) -> tuple[date, date]:
    year, month_number = map(int, month.split("-"))
    start = date(year, month_number, 1)

    if month_number == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month_number + 1, 1)

    return start, end


def _calculate_confidence(
    obligations: list[SafeToSpendObligationOut],
    *,
    has_liquid_balance: bool,
) -> float:
    if obligations:
        recurring_confidence = sum(
            obligation.confidence_score
            for obligation in obligations
        ) / len(obligations)
    else:
        recurring_confidence = 70.0

    balance_confidence = 100.0 if has_liquid_balance else 0.0

    return round(
        (balance_confidence * 0.6)
        + (recurring_confidence * 0.4),
        1,
    )


def _determine_status(
    raw_safe_to_spend_cents: int,
    liquid_balance_cents: int,
) -> str:
    if raw_safe_to_spend_cents < 0:
        return "negative"

    limited_threshold_cents = max(
        round(liquid_balance_cents * 0.1),
        10000,
    )

    if raw_safe_to_spend_cents < limited_threshold_cents:
        return "limited"

    return "safe"