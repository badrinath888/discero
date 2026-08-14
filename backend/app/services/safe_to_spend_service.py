from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Budget,
    FinancialAccount,
    PlaidItem,
    RecurringItem,
    SavingsGoal,
    Transaction,
)
from app.recurring import project_occurrences
from app.schemas import (
    SafeToSpendBreakdownOut,
    SafeToSpendConfidenceDriverOut,
    SafeToSpendExplanationOut,
    SafeToSpendObligationOut,
    SafeToSpendOut,
    SafeToSpendRequest,
)
from app.services.goal_conflict_detection_service import (
    _months_remaining,
    _required_monthly_amount,
)

LIQUID_ACCOUNT_TYPES = {
    "depository",
    "cash",
}

BUDGET_OBLIGATION_CONFIDENCE_SCORE = 75.0

_DAYS_PER_MONTH = 30
_TRAILING_MONTHS_FOR_INCOME_AVERAGE = 3

# Matches the high/medium/low thresholds `forecast_confidence_service`
# already uses, so a given score reads the same way everywhere in the
# app rather than each feature inventing its own cutoffs.
_HIGH_CONFIDENCE_THRESHOLD = 80.0
_MEDIUM_CONFIDENCE_THRESHOLD = 55.0


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

    projected_income_cents = (
        _get_projected_income_cents(
            db,
            user_id,
            calculation_date,
            payload.horizon_days,
        )
        if payload.include_projected_income
        else 0
    )

    goal_reserve_cents = (
        _get_goal_reserve_cents(
            db,
            user_id,
            calculation_date,
            payload.horizon_days,
        )
        if payload.include_goal_reserve
        else 0
    )

    raw_safe_to_spend_cents = (
        liquid_balance_cents
        + projected_income_cents
        - upcoming_obligations_cents
        - payload.essential_spending_cents
        - goal_reserve_cents
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
    confidence_level = _confidence_level(confidence_score)
    confidence_drivers = _build_confidence_drivers(
        obligations,
        liquid_balance_cents=liquid_balance_cents,
        warnings=warnings,
    )

    breakdown = SafeToSpendBreakdownOut(
        liquid_balance_cents=liquid_balance_cents,
        projected_income_cents=projected_income_cents,
        upcoming_obligations_cents=upcoming_obligations_cents,
        essential_spending_cents=payload.essential_spending_cents,
        goal_reserve_cents=goal_reserve_cents,
        safety_reserve_cents=payload.safety_reserve_cents,
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
        confidence_level=confidence_level,
        confidence_drivers=confidence_drivers,
        breakdown=breakdown,
        obligations=obligations,
        explanation=_build_explanation(
            breakdown=breakdown,
            safe_to_spend_cents=safe_to_spend_cents,
            shortfall_cents=shortfall_cents,
            through_date=through_date,
            confidence_level=confidence_level,
        ),
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
    """Every KNOWN occurrence of each active recurring item in the window.

    A recurring item's stored `next_payment` is only its FIRST future
    occurrence -- over a 60/90-day horizon a monthly bill can recur
    2-3 times and a weekly one 8-13 times. This reuses the same
    deterministic `app.recurring.project_occurrences` helper the
    Forecast horizon outlook uses (Weekly/Biweekly/Monthly, the only
    frequencies the app actually produces), rather than a second
    recurrence formula, so a bill is counted once per real due date
    instead of once per item regardless of horizon length.

    The query has no lower bound on `next_payment`: an item whose
    stored `next_payment` is slightly stale (e.g. sync lag, now
    before `as_of`) can still have a genuine future occurrence inside
    the window once projected forward. `project_occurrences` itself
    filters to `>= as_of`, so nothing before `as_of` is ever counted
    -- this only recovers occurrences that were being silently missed,
    it never counts something earlier than before.

    Fetches all candidate items in a single query (not one query per
    item) and projects each item's occurrences in memory, bounded by
    the requested horizon -- no per-occurrence database round trips.
    """
    statement = (
        select(RecurringItem)
        .where(
            RecurringItem.user_id == user_id,
            RecurringItem.status == "active",
            RecurringItem.next_payment <= through_date,
        )
        .order_by(
            RecurringItem.next_payment,
            RecurringItem.id,
        )
    )

    items = list(db.scalars(statement).all())

    obligations: list[SafeToSpendObligationOut] = []

    for item in items:
        occurrences = project_occurrences(
            item.next_payment,
            item.frequency,
            as_of=as_of,
            through_date=through_date,
        )

        obligations.extend(
            SafeToSpendObligationOut(
                name=item.merchant,
                amount_cents=item.amount_cents,
                expected_date=occurrence,
                category=item.category,
                confidence_score=item.confidence_score,
                source="recurring",
            )
            for occurrence in occurrences
        )

    return obligations


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


def _prorate_monthly_to_horizon(
    monthly_cents: int,
    horizon_days: int,
) -> int:
    return round(monthly_cents * horizon_days / _DAYS_PER_MONTH)


def _get_projected_income_cents(
    db: Session,
    user_id: int,
    as_of: date,
    horizon_days: int,
) -> int:
    """Average of the last few COMPLETED months' income, prorated to
    the horizon.

    This is a duplicate of `major_purchase_service._average_monthly_
    income_cents` (same trailing-window convention used throughout
    the app for income/spending baselines) rather than an import,
    because `major_purchase_service` already imports from this
    module -- importing back would create a circular dependency.
    """
    transactions = list(
        db.scalars(
            select(Transaction).where(
                Transaction.user_id == user_id,
                Transaction.amount_cents > 0,
            )
        ).all()
    )

    current_month = f"{as_of.year:04d}-{as_of.month:02d}"
    totals: dict[str, int] = {}

    for transaction in transactions:
        month = (
            f"{transaction.posted_on.year:04d}"
            f"-{transaction.posted_on.month:02d}"
        )

        if month >= current_month:
            continue

        totals[month] = totals.get(month, 0) + transaction.amount_cents

    recent = sorted(totals)[-_TRAILING_MONTHS_FOR_INCOME_AVERAGE:]

    if not recent:
        return 0

    average_monthly_cents = round(
        sum(totals[month] for month in recent) / len(recent)
    )

    return _prorate_monthly_to_horizon(average_monthly_cents, horizon_days)


def _get_goal_reserve_cents(
    db: Session,
    user_id: int,
    as_of: date,
    horizon_days: int,
) -> int:
    """Required monthly contributions across active goals, prorated to
    the horizon.

    Reuses the same `_required_monthly_amount` / `_months_remaining`
    helpers `goal_conflict_detection_service` and `goal_impact_service`
    already use to size a goal's required pace, so this can never
    diverge from how goal funding requirements are calculated
    elsewhere in the app. Only goals with a target date and a
    positive remaining amount contribute -- an open-ended goal has no
    deadline-driven amount that must be protected within this
    horizon.
    """
    goals = list(
        db.scalars(
            select(SavingsGoal).where(
                SavingsGoal.user_id == user_id,
                SavingsGoal.saved_cents < SavingsGoal.target_cents,
            )
        ).all()
    )

    total_required_monthly_cents = 0

    for goal in goals:
        remaining_cents = max(goal.target_cents - goal.saved_cents, 0)
        months_remaining = _months_remaining(as_of, goal.target_date)
        total_required_monthly_cents += _required_monthly_amount(
            remaining_cents,
            months_remaining,
            goal.target_date,
        )

    return _prorate_monthly_to_horizon(
        total_required_monthly_cents,
        horizon_days,
    )


def _confidence_level(confidence_score: float) -> str:
    if confidence_score >= _HIGH_CONFIDENCE_THRESHOLD:
        return "high"

    if confidence_score >= _MEDIUM_CONFIDENCE_THRESHOLD:
        return "medium"

    return "low"


def _build_confidence_drivers(
    obligations: list[SafeToSpendObligationOut],
    *,
    liquid_balance_cents: int,
    warnings: list[str],
) -> list[SafeToSpendConfidenceDriverOut]:
    drivers: list[SafeToSpendConfidenceDriverOut] = []

    if liquid_balance_cents > 0:
        drivers.append(
            SafeToSpendConfidenceDriverOut(
                code="LIQUID_BALANCE_FOUND",
                direction="positive",
                message=(
                    "A liquid balance was found across your active "
                    "accounts."
                ),
            )
        )
    else:
        drivers.append(
            SafeToSpendConfidenceDriverOut(
                code="NO_LIQUID_BALANCE",
                direction="negative",
                message=(
                    "No active liquid accounts were found, so "
                    "available funds are $0."
                ),
            )
        )

    if obligations:
        average_obligation_confidence = round(
            sum(
                obligation.confidence_score
                for obligation in obligations
            )
            / len(obligations),
            1,
        )

        if average_obligation_confidence >= 75.0:
            drivers.append(
                SafeToSpendConfidenceDriverOut(
                    code="OBLIGATIONS_WELL_RECOGNIZED",
                    direction="positive",
                    message=(
                        f"Upcoming obligations have an average "
                        f"detection confidence of "
                        f"{average_obligation_confidence}%."
                    ),
                )
            )
        else:
            drivers.append(
                SafeToSpendConfidenceDriverOut(
                    code="OBLIGATIONS_LOW_CONFIDENCE",
                    direction="negative",
                    message=(
                        f"Upcoming obligations have a lower average "
                        f"detection confidence of "
                        f"{average_obligation_confidence}%, so some "
                        "estimates may be imprecise."
                    ),
                )
            )
    else:
        drivers.append(
            SafeToSpendConfidenceDriverOut(
                code="NO_OBLIGATIONS_RECOGNIZED",
                direction="negative",
                message=(
                    "No recurring or budget obligations were found "
                    "for this period, so this estimate may be "
                    "incomplete."
                ),
            )
        )

    if warnings:
        drivers.append(
            SafeToSpendConfidenceDriverOut(
                code="DATA_QUALITY_WARNINGS",
                direction="negative",
                message=(
                    f"{len(warnings)} data-quality warning(s) were "
                    "raised for this calculation."
                ),
            )
        )

    return drivers


def _build_explanation(
    *,
    breakdown: SafeToSpendBreakdownOut,
    safe_to_spend_cents: int,
    shortfall_cents: int,
    through_date: date,
    confidence_level: str,
) -> list[SafeToSpendExplanationOut]:
    explanation: list[SafeToSpendExplanationOut] = []

    explanation.append(
        SafeToSpendExplanationOut(
            code="LIQUID_BALANCE",
            amount_cents=breakdown.liquid_balance_cents,
            message=(
                f"Your liquid balance is "
                f"{_currency(breakdown.liquid_balance_cents)} across "
                "active linked accounts."
            ),
        )
    )

    if breakdown.projected_income_cents > 0:
        explanation.append(
            SafeToSpendExplanationOut(
                code="PROJECTED_INCOME",
                amount_cents=breakdown.projected_income_cents,
                message=(
                    "Expected income within this period adds "
                    f"{_currency(breakdown.projected_income_cents)} "
                    "to available funds."
                ),
            )
        )

    if breakdown.upcoming_obligations_cents > 0:
        explanation.append(
            SafeToSpendExplanationOut(
                code="UPCOMING_OBLIGATIONS",
                amount_cents=breakdown.upcoming_obligations_cents,
                message=(
                    "Your safe-to-spend amount protects "
                    f"{_currency(breakdown.upcoming_obligations_cents)} "
                    "for upcoming obligations."
                ),
            )
        )

    if breakdown.essential_spending_cents > 0:
        explanation.append(
            SafeToSpendExplanationOut(
                code="ESSENTIAL_SPENDING",
                amount_cents=breakdown.essential_spending_cents,
                message=(
                    f"{_currency(breakdown.essential_spending_cents)} "
                    "is set aside for essential spending during this "
                    "period."
                ),
            )
        )

    if breakdown.goal_reserve_cents > 0:
        explanation.append(
            SafeToSpendExplanationOut(
                code="GOAL_RESERVE",
                amount_cents=breakdown.goal_reserve_cents,
                message=(
                    f"{_currency(breakdown.goal_reserve_cents)} is "
                    "reserved for active savings goals during this "
                    "period."
                ),
            )
        )

    if breakdown.safety_reserve_cents > 0:
        explanation.append(
            SafeToSpendExplanationOut(
                code="SAFETY_RESERVE",
                amount_cents=breakdown.safety_reserve_cents,
                message=(
                    f"{_currency(breakdown.safety_reserve_cents)} is "
                    "being maintained as your safety reserve."
                ),
            )
        )

    if shortfall_cents > 0:
        explanation.append(
            SafeToSpendExplanationOut(
                code="SHORTFALL",
                amount_cents=shortfall_cents,
                message=(
                    "Safe-to-spend is $0 because protected "
                    "obligations exceed available resources by "
                    f"{_currency(shortfall_cents)}."
                ),
            )
        )
    else:
        explanation.append(
            SafeToSpendExplanationOut(
                code="RESULT",
                amount_cents=safe_to_spend_cents,
                message=(
                    f"You can safely spend "
                    f"{_currency(safe_to_spend_cents)} through "
                    f"{through_date.isoformat()} after protecting "
                    "known obligations."
                ),
            )
        )

    explanation.append(
        SafeToSpendExplanationOut(
            code="CONFIDENCE",
            amount_cents=None,
            message=f"Confidence in this calculation is {confidence_level}.",
        )
    )

    return explanation


def _currency(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    return f"{sign}${abs(cents) / 100:,.2f}"