from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FinancialAccount, PlaidItem, RecurringItem
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

    obligations = _get_upcoming_obligations(
        db,
        user_id,
        calculation_date,
        through_date,
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

    if not obligations:
        warnings.append(
            "No active recurring obligations were found "
            "for the selected period."
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