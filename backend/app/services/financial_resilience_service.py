"""Financial Resilience / Emergency Runway.

Answers "how many months could I survive if income stopped?" using the
SAME liquid-balance definition as `safe_to_spend_service` (reused via
`LIQUID_ACCOUNT_TYPES`, not redefined) and no new balance-aggregation
formula.

Monthly burn is either:
- user-provided (an explicit override, including a legitimate $0) --
  the ONLY case allowed to call itself "essential spending", or
- derived from the average of the last few COMPLETED months' total
  spending (the same trailing-window averaging convention already
  used by `_average_monthly_income_cents` elsewhere in this codebase).

Discero does not yet classify transactions as "essential" vs.
"discretionary". A derived figure is a spending BASELINE, not an
essential-only number, and every user-facing string (`headline`,
`why`, `what_this_means`, `suggested_actions`, `spending_basis_label`)
is generated separately per `essential_spending_source` so a derived
estimate is never worded as if it were a precise essential-expense
figure -- see `_WHAT_THIS_MEANS_*` / `_ACTIONS_*` below.

Runway and 30/60/90-day coverage are plain integer-cents division and
multiplication; there is no separate formula for "coverage" vs.
"income-loss scenario" -- both are the same horizon calculation
(liquid funds depleting at the burn rate with no offsetting income),
just reported from two angles.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FinancialAccount, PlaidItem, Transaction
from app.schemas import FinancialResilienceOut, ResilienceHorizonOut
from app.services.safe_to_spend_service import LIQUID_ACCOUNT_TYPES

_TRAILING_MONTHS_FOR_SPENDING_AVERAGE = 3
_COVERAGE_HORIZONS_DAYS = (30, 60, 90)
_DAYS_PER_MONTH = 30

# Deterministic resilience bands, in months of essential-expense
# runway. Documented and tested at each boundary.
_RESILIENCE_BANDS: tuple[tuple[float, str], ...] = (
    (12.0, "very_strong"),
    (6.0, "strong"),
    (3.0, "fair"),
    (1.0, "weak"),
)

_STATUS_LABEL = {
    "critical": "critically short",
    "weak": "weak",
    "fair": "fair",
    "strong": "strong",
    "very_strong": "very strong",
}

# Only the user-provided path may call itself an "emergency runway"
# over "essential spending" -- a derived figure is reframed as
# "spending coverage" at a recent "spending pace" throughout, per the
# product requirement to never present total spending as if Discero
# knows which transactions are essential.
_WHAT_THIS_MEANS_USER_PROVIDED = {
    "critical": (
        "If income stopped today, your liquid cash would not cover "
        "even one month of essential spending."
    ),
    "weak": (
        "You could cover essential spending for a little over a "
        "month, but not long enough to absorb a real income gap."
    ),
    "fair": (
        "You have a moderate buffer, but it would not comfortably "
        "cover an extended income gap."
    ),
    "strong": (
        "You have a solid buffer that would cover several months "
        "without income."
    ),
    "very_strong": (
        "You have a year or more of essential spending covered by "
        "liquid cash."
    ),
}

_WHAT_THIS_MEANS_DERIVED = {
    "critical": (
        "If income stopped today, your liquid cash would not cover "
        "even one month at your recent spending pace."
    ),
    "weak": (
        "You could cover a little over a month at your recent "
        "spending pace, but not long enough to absorb a real income "
        "gap."
    ),
    "fair": (
        "You have a moderate buffer at your recent spending pace, "
        "but it would not comfortably cover an extended income gap."
    ),
    "strong": (
        "You have a solid buffer that would cover several months at "
        "your recent spending pace without income."
    ),
    "very_strong": (
        "You have a year or more of coverage at your recent "
        "spending pace."
    ),
}

_ACTIONS_USER_PROVIDED = {
    "critical": [
        "Prioritize building even a small liquid cash buffer before "
        "anything else.",
        "Review essential spending for anything that can be cut "
        "immediately.",
    ],
    "weak": [
        "Redirect any available monthly capacity toward a cash "
        "buffer until you reach 3 months of runway.",
    ],
    "fair": [
        "Keep building your buffer toward 6 months of essential "
        "spending.",
    ],
    "strong": [
        "Maintain your current buffer; consider directing extra "
        "capacity toward other goals.",
    ],
    "very_strong": [
        "Your buffer is strong -- extra capacity can go toward "
        "goals or investments.",
    ],
}

_ACTIONS_DERIVED = {
    "critical": [
        "Prioritize building even a small liquid cash buffer before "
        "anything else.",
        "Review your recent spending for anything that can be cut "
        "immediately.",
    ],
    "weak": [
        "Redirect any available monthly capacity toward a cash "
        "buffer until you reach 3 months of coverage.",
    ],
    "fair": [
        "Keep building your buffer toward 6 months of spending "
        "coverage.",
    ],
    "strong": [
        "Maintain your current buffer; consider directing extra "
        "capacity toward other goals.",
    ],
    "very_strong": [
        "Your buffer is strong -- extra capacity can go toward "
        "goals or investments.",
    ],
}


def _currency(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    return f"{sign}${abs(cents) / 100:,.2f}"


def _classify_band(runway_months: float) -> str:
    for threshold, label in _RESILIENCE_BANDS:
        if runway_months >= threshold:
            return label

    return "critical"


def _liquid_balance_and_count(
    db: Session, user_id: int
) -> tuple[int, int, list[str]]:
    statement = (
        select(FinancialAccount)
        .join(
            PlaidItem,
            FinancialAccount.plaid_item_id == PlaidItem.id,
        )
        .where(
            PlaidItem.user_id == user_id,
            PlaidItem.status == "active",
            FinancialAccount.account_type.in_(LIQUID_ACCOUNT_TYPES),
        )
    )

    accounts = list(db.scalars(statement).all())
    warnings: list[str] = []

    if not accounts:
        warnings.append("No active liquid accounts were found.")
        return 0, 0, warnings

    balance_cents = 0
    counted = 0

    for account in accounts:
        if account.available_balance_cents is not None:
            balance_cents += account.available_balance_cents
            counted += 1
        elif account.current_balance_cents is not None:
            balance_cents += account.current_balance_cents
            counted += 1
        else:
            warnings.append(
                f"{account.name} was excluded because no balance "
                "was available."
            )

    return balance_cents, counted, warnings


def _average_monthly_spending_cents(
    db: Session, user_id: int, as_of: date
) -> tuple[int, int]:
    """Returns (average_monthly_spending_cents, months_of_data)."""
    transactions = list(
        db.scalars(
            select(Transaction).where(
                Transaction.user_id == user_id,
                Transaction.amount_cents < 0,
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

        totals[month] = totals.get(month, 0) + (
            -transaction.amount_cents
        )

    recent = sorted(totals)[-_TRAILING_MONTHS_FOR_SPENDING_AVERAGE:]

    if not recent:
        return 0, 0

    average = round(sum(totals[month] for month in recent) / len(recent))

    return average, len(recent)


def _essential_confidence(
    source: str, months_of_data: int
) -> tuple[float, str | None]:
    if source == "user_provided":
        return 100.0, None

    if months_of_data == 0:
        return 0.0, (
            "No spending history was found, so a spending baseline "
            "could not be estimated -- this figure is $0 until you "
            "either add transaction history or provide a monthly "
            "amount."
        )

    if months_of_data < _TRAILING_MONTHS_FOR_SPENDING_AVERAGE:
        return 55.0, (
            f"Only {months_of_data} month(s) of spending history "
            "were available, so treat the spending baseline as a "
            "rough estimate."
        )

    return 90.0, None


def _horizon_metrics(
    liquid_balance_cents: int, monthly_essential_cents: int
) -> list[ResilienceHorizonOut]:
    horizons = []

    for horizon_days in _COVERAGE_HORIZONS_DAYS:
        required_cents = round(
            monthly_essential_cents * horizon_days / _DAYS_PER_MONTH
        )
        remaining_cents = max(liquid_balance_cents - required_cents, 0)
        shortfall_cents = max(required_cents - liquid_balance_cents, 0)
        coverage_percent = (
            round(min(liquid_balance_cents / required_cents, 1.0) * 100, 1)
            if required_cents > 0
            else 100.0
        )

        horizons.append(
            ResilienceHorizonOut(
                horizon_days=horizon_days,
                required_essential_cents=required_cents,
                remaining_liquid_cents=remaining_cents,
                shortfall_cents=shortfall_cents,
                coverage_percent=coverage_percent,
            )
        )

    return horizons


def _spending_basis_label(source: str) -> str:
    return (
        "Monthly essential spending"
        if source == "user_provided"
        else "Monthly spending baseline"
    )


def _build_explanation(
    *,
    status: str,
    liquid_balance_cents: int,
    monthly_essential_cents: int,
    essential_source: str,
    runway_months: float | None,
) -> tuple[str, str]:
    is_explicit = essential_source == "user_provided"
    concept = "emergency runway" if is_explicit else "spending coverage"
    headline = f"Your {concept} is {_STATUS_LABEL[status]}"

    if monthly_essential_cents <= 0:
        spending_phrase = (
            "no essential spending" if is_explicit else "no recent spending"
        )
        why = (
            f"You have {_currency(liquid_balance_cents)} in liquid "
            f"accounts and {spending_phrase}, so there is currently no "
            "burn rate to run out against."
        )
        return headline, why

    runway_display = (
        f"{runway_months} month(s)" if runway_months is not None else "0 months"
    )

    if is_explicit:
        why = (
            f"You have {_currency(liquid_balance_cents)} in liquid "
            f"accounts against {_currency(monthly_essential_cents)}"
            "/month in essential spending you provided -- "
            f"{runway_display} of essential-expense coverage."
        )
    else:
        # Matches the product's own required example wording: never
        # call an uncategorized spending total "essential expenses".
        why = (
            f"Your liquid cash ({_currency(liquid_balance_cents)}) "
            f"covers approximately {runway_display} at your recent "
            f"spending pace of {_currency(monthly_essential_cents)}"
            "/month, estimated from your total spending because "
            "Discero does not yet classify essential vs. "
            "discretionary expenses."
        )

    return headline, why


def evaluate_financial_resilience(
    db: Session,
    user_id: int,
    *,
    essential_spending_cents: int | None = None,
    as_of: date | None = None,
) -> FinancialResilienceOut:
    calculation_date = as_of or date.today()

    liquid_balance_cents, liquid_account_count, balance_warnings = (
        _liquid_balance_and_count(db, user_id)
    )

    if essential_spending_cents is not None:
        monthly_essential_cents = essential_spending_cents
        essential_source = "user_provided"
        months_of_spending_data = 0
    else:
        monthly_essential_cents, months_of_spending_data = (
            _average_monthly_spending_cents(
                db, user_id, calculation_date
            )
        )
        essential_source = "derived"

    if monthly_essential_cents <= 0:
        runway_months: float | None = None
        runway_days: int | None = None
        status = "very_strong"
    else:
        raw_ratio = liquid_balance_cents / monthly_essential_cents
        runway_months = round(raw_ratio, 1)
        runway_days = round(raw_ratio * _DAYS_PER_MONTH)
        status = _classify_band(raw_ratio)

    horizons = _horizon_metrics(
        liquid_balance_cents, monthly_essential_cents
    )

    essential_confidence, essential_note = _essential_confidence(
        essential_source, months_of_spending_data
    )
    balance_confidence = 100.0 if liquid_account_count > 0 else 0.0
    confidence_score = round(
        (balance_confidence * 0.5) + (essential_confidence * 0.5), 1
    )

    warnings = list(balance_warnings)
    if essential_note:
        warnings.append(essential_note)

    headline, why = _build_explanation(
        status=status,
        liquid_balance_cents=liquid_balance_cents,
        monthly_essential_cents=monthly_essential_cents,
        essential_source=essential_source,
        runway_months=runway_months,
    )
    is_explicit = essential_source == "user_provided"
    what_this_means = (
        _WHAT_THIS_MEANS_USER_PROVIDED if is_explicit else _WHAT_THIS_MEANS_DERIVED
    )[status]
    suggested_actions = (
        _ACTIONS_USER_PROVIDED if is_explicit else _ACTIONS_DERIVED
    )[status]

    return FinancialResilienceOut(
        as_of=calculation_date,
        liquid_balance_cents=liquid_balance_cents,
        liquid_account_count=liquid_account_count,
        monthly_essential_cents=monthly_essential_cents,
        essential_spending_source=essential_source,
        spending_basis_label=_spending_basis_label(essential_source),
        months_of_spending_data=months_of_spending_data,
        runway_months=runway_months,
        runway_days=runway_days,
        resilience_status=status,
        horizons=horizons,
        confidence_score=confidence_score,
        data_quality_note=essential_note,
        headline=headline,
        why=why,
        what_this_means=what_this_means,
        suggested_actions=suggested_actions,
        warnings=warnings,
    )
