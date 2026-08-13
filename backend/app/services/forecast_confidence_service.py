from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Budget, FinancialAccount, Transaction
from app.schemas import (
    ForecastConfidenceFactorOut,
    ForecastConfidenceOut,
    MonthlyForecastConfidenceOut,
)

# Each factor's weight is a fixed, documented share of the overall
# 0-100 score. Weights sum to exactly 100, so the overall score is a
# straightforward weighted average of the individual factor scores
# (each of which is itself bounded to [0, 100]) — the result is
# always bounded to [0, 100] with no further clamping required.
_FACTOR_WEIGHTS: dict[str, float] = {
    "transaction_history": 16.0,
    "recent_coverage": 13.0,
    "linked_accounts": 13.0,
    "recurring_confidence": 13.0,
    "missing_balances": 9.0,
    "stale_data": 9.0,
    "horizon_length": 8.0,
    "income_consistency": 6.0,
    "spending_volatility": 6.0,
    "budget_coverage": 7.0,
}

_FACTOR_LABELS: dict[str, str] = {
    "transaction_history": "Transaction history depth",
    "recent_coverage": "Recent transaction coverage",
    "linked_accounts": "Linked liquid accounts",
    "recurring_confidence": "Recurring-obligation confidence",
    "missing_balances": "Account balance completeness",
    "stale_data": "Data freshness",
    "horizon_length": "Forecast horizon length",
    "income_consistency": "Income consistency",
    "spending_volatility": "Spending volatility",
    "budget_coverage": "Budget coverage",
}

# Recommendations are only generated for factors that reflect a data
# *quality* problem the user can act on (sync, connect, confirm,
# budget). Horizon length and volatility are excluded on purpose:
# they describe the shape of the forecast/spending itself, not a
# fixable data gap.
_RECOMMENDATION_TEXT: dict[str, str] = {
    "transaction_history": (
        "Import more historical transactions to strengthen the "
        "forecast baseline."
    ),
    "recent_coverage": (
        "Sync recent activity so the forecast reflects your latest "
        "spending."
    ),
    "linked_accounts": (
        "Connect a checking or cash account so Discero can track "
        "your real balance."
    ),
    "recurring_confidence": (
        "Review detected recurring payments to sharpen bill "
        "predictions."
    ),
    "missing_balances": (
        "Reconnect accounts with missing balances so available "
        "funds are accurate."
    ),
    "stale_data": (
        "Sync your accounts — recent transactions are missing."
    ),
    "budget_coverage": (
        "Set a budget for this month to improve spending "
        "predictability."
    ),
}

_TRANSACTION_HISTORY_TARGET_DAYS = 180
_RECENT_COVERAGE_WINDOW_DAYS = 30
_RECENT_COVERAGE_TARGET_COUNT = 10
_TARGET_LIQUID_ACCOUNTS = 2
_DEFAULT_RECURRING_CONFIDENCE = 40.0
_STALE_DATA_TARGET_DAYS = 30
_TRAILING_MONTHS_FOR_VOLATILITY = 6
_DEFAULT_VOLATILITY_SCORE = 50.0
_MONTHLY_CONFIDENCE_TARGET_COUNT = 8
_MONTHLY_CONFIDENCE_LOOKBACK_MONTHS = 6
_RECOMMENDATION_THRESHOLD = 55.0
_MAX_RECOMMENDATIONS = 5

# Confidence-level thresholds. "High" means the data quality signals
# are, on average, solidly above their healthy baselines; "low" means
# they are, on average, below the midpoint.
_HIGH_CONFIDENCE_THRESHOLD = 80.0
_MEDIUM_CONFIDENCE_THRESHOLD = 55.0


def calculate_forecast_confidence(
    db: Session,
    user_id: int,
    *,
    as_of: date,
    days_remaining: int,
    days_in_month: int,
    transactions: list[Transaction],
    liquid_accounts: list[FinancialAccount],
    recurring_items: list[dict],
) -> ForecastConfidenceOut:
    scores: dict[str, float] = {}
    details: dict[str, str] = {}

    scores["transaction_history"], details["transaction_history"] = (
        _transaction_history_factor(transactions, as_of)
    )
    scores["recent_coverage"], details["recent_coverage"] = (
        _recent_coverage_factor(transactions, as_of)
    )
    scores["linked_accounts"], details["linked_accounts"] = (
        _linked_accounts_factor(liquid_accounts)
    )
    scores["recurring_confidence"], details["recurring_confidence"] = (
        _recurring_confidence_factor(recurring_items)
    )
    scores["missing_balances"], details["missing_balances"] = (
        _missing_balances_factor(liquid_accounts)
    )
    scores["stale_data"], details["stale_data"] = _stale_data_factor(
        transactions, as_of
    )
    scores["horizon_length"], details["horizon_length"] = (
        _horizon_length_factor(days_remaining, days_in_month)
    )
    scores["income_consistency"], details["income_consistency"] = (
        _volatility_factor(transactions, as_of, positive_only=True)
    )
    scores["spending_volatility"], details["spending_volatility"] = (
        _volatility_factor(transactions, as_of, positive_only=False)
    )
    scores["budget_coverage"], details["budget_coverage"] = (
        _budget_coverage_factor(db, user_id, as_of)
    )

    factors = [
        ForecastConfidenceFactorOut(
            key=key,
            label=_FACTOR_LABELS[key],
            weight=weight,
            score=round(scores[key], 1),
            impact=_impact(scores[key]),
            detail=details[key],
        )
        for key, weight in _FACTOR_WEIGHTS.items()
    ]

    overall_score = round(
        sum(
            scores[key] * weight / 100
            for key, weight in _FACTOR_WEIGHTS.items()
        ),
        1,
    )

    return ForecastConfidenceOut(
        score=overall_score,
        level=_confidence_level(overall_score),
        factors=factors,
        recommendations=_build_recommendations(factors),
        monthly_confidence=_monthly_confidence(transactions, as_of),
    )


def _impact(score: float) -> str:
    if score >= 70:
        return "positive"

    if score <= 40:
        return "negative"

    return "neutral"


def _confidence_level(score: float) -> str:
    if score >= _HIGH_CONFIDENCE_THRESHOLD:
        return "high"

    if score >= _MEDIUM_CONFIDENCE_THRESHOLD:
        return "medium"

    return "low"


def _transaction_history_factor(
    transactions: list[Transaction],
    as_of: date,
) -> tuple[float, str]:
    if not transactions:
        return 0.0, "No transaction history is available yet."

    earliest = min(
        transaction.posted_on for transaction in transactions
    )
    span_days = max((as_of - earliest).days, 0)
    score = min(
        span_days / _TRANSACTION_HISTORY_TARGET_DAYS * 100,
        100.0,
    )

    return score, (
        f"{span_days} days of transaction history "
        f"({_TRANSACTION_HISTORY_TARGET_DAYS}+ days is treated as a "
        "mature baseline)."
    )


def _recent_coverage_factor(
    transactions: list[Transaction],
    as_of: date,
) -> tuple[float, str]:
    window_start = as_of - timedelta(
        days=_RECENT_COVERAGE_WINDOW_DAYS
    )
    recent_count = sum(
        1
        for transaction in transactions
        if window_start <= transaction.posted_on <= as_of
    )
    score = min(
        recent_count / _RECENT_COVERAGE_TARGET_COUNT * 100,
        100.0,
    )

    return score, (
        f"{recent_count} transaction(s) in the last "
        f"{_RECENT_COVERAGE_WINDOW_DAYS} days "
        f"({_RECENT_COVERAGE_TARGET_COUNT}+ is treated as healthy "
        "coverage)."
    )


def _linked_accounts_factor(
    liquid_accounts: list[FinancialAccount],
) -> tuple[float, str]:
    count = len(liquid_accounts)
    score = min(count / _TARGET_LIQUID_ACCOUNTS * 100, 100.0)

    return score, (
        f"{count} linked liquid account(s) "
        f"({_TARGET_LIQUID_ACCOUNTS}+ is treated as well covered)."
    )


def _recurring_confidence_factor(
    recurring_items: list[dict],
) -> tuple[float, str]:
    if not recurring_items:
        return _DEFAULT_RECURRING_CONFIDENCE, (
            "No recurring payment patterns were detected yet, so a "
            "moderate default is used."
        )

    average = sum(
        float(item["confidence_score"])
        for item in recurring_items
    ) / len(recurring_items)

    return average, (
        f"Average detection confidence across {len(recurring_items)} "
        "recurring pattern(s)."
    )


def _missing_balances_factor(
    liquid_accounts: list[FinancialAccount],
) -> tuple[float, str]:
    if not liquid_accounts:
        return 0.0, "No linked liquid accounts were found."

    with_balance = sum(
        1
        for account in liquid_accounts
        if account.available_balance_cents is not None
        or account.current_balance_cents is not None
    )
    score = with_balance / len(liquid_accounts) * 100

    return score, (
        f"{with_balance} of {len(liquid_accounts)} linked account(s) "
        "report a usable balance."
    )


def _stale_data_factor(
    transactions: list[Transaction],
    as_of: date,
) -> tuple[float, str]:
    if not transactions:
        return 0.0, "No transactions have been recorded."

    latest = max(
        transaction.posted_on for transaction in transactions
    )
    days_since = max((as_of - latest).days, 0)
    score = max(
        0.0,
        100 - (days_since / _STALE_DATA_TARGET_DAYS * 100),
    )

    return score, f"Most recent transaction was {days_since} day(s) ago."


def _horizon_length_factor(
    days_remaining: int,
    days_in_month: int,
) -> tuple[float, str]:
    if days_in_month <= 0:
        return 100.0, "No remaining days in the forecast period."

    score = max(
        0.0,
        100 - (days_remaining / days_in_month * 100),
    )

    return score, (
        f"{days_remaining} day(s) remain in the forecast period; "
        "confidence naturally declines earlier in the horizon."
    )


def _month_key(value: date) -> str:
    return f"{value.year:04d}-{value.month:02d}"


def _monthly_totals(
    transactions: list[Transaction],
    as_of: date,
    *,
    positive_only: bool,
) -> list[int]:
    totals: dict[str, int] = defaultdict(int)
    current_month = _month_key(as_of)

    for transaction in transactions:
        month = _month_key(transaction.posted_on)

        if month >= current_month:
            continue

        if positive_only and transaction.amount_cents <= 0:
            continue

        if not positive_only and transaction.amount_cents >= 0:
            continue

        totals[month] += abs(transaction.amount_cents)

    recent_months = sorted(totals)[-_TRAILING_MONTHS_FOR_VOLATILITY:]

    return [totals[month] for month in recent_months]


def _volatility_factor(
    transactions: list[Transaction],
    as_of: date,
    *,
    positive_only: bool,
) -> tuple[float, str]:
    label = "Income" if positive_only else "Spending"
    totals = _monthly_totals(
        transactions, as_of, positive_only=positive_only
    )

    if len(totals) < 2:
        return _DEFAULT_VOLATILITY_SCORE, (
            f"Not enough completed months of {label.lower()} "
            "history to measure consistency, so a moderate default "
            "is used."
        )

    mean = sum(totals) / len(totals)

    if mean <= 0:
        return _DEFAULT_VOLATILITY_SCORE, (
            f"No completed months of {label.lower()} were recorded."
        )

    variance = sum(
        (value - mean) ** 2 for value in totals
    ) / len(totals)
    coefficient_of_variation = (variance ** 0.5) / mean
    score = max(0.0, 100 - coefficient_of_variation * 100)

    return score, (
        f"{label} varied by "
        f"{round(coefficient_of_variation * 100, 1)}% across the "
        f"last {len(totals)} completed month(s)."
    )


def _budget_coverage_factor(
    db: Session,
    user_id: int,
    as_of: date,
) -> tuple[float, str]:
    month = _month_key(as_of)

    budget_count = (
        db.scalar(
            select(func.count())
            .select_from(Budget)
            .where(
                Budget.user_id == user_id,
                Budget.month == month,
            )
        )
        or 0
    )

    if budget_count == 0:
        return 30.0, "No budgets are set for the current month."

    return 100.0, (
        f"{budget_count} budget categor"
        f"{'y' if budget_count == 1 else 'ies'} set for the "
        "current month."
    )


def _build_recommendations(
    factors: list[ForecastConfidenceFactorOut],
) -> list[str]:
    weak_factors = [
        factor
        for factor in factors
        if factor.key in _RECOMMENDATION_TEXT
        and factor.score < _RECOMMENDATION_THRESHOLD
    ]
    weak_factors.sort(key=lambda factor: factor.weight, reverse=True)

    return [
        _RECOMMENDATION_TEXT[factor.key]
        for factor in weak_factors[:_MAX_RECOMMENDATIONS]
    ]


def _shift_month(month: str, offset: int) -> str:
    year, month_number = map(int, month.split("-"))
    absolute_month = year * 12 + month_number - 1 + offset

    next_year, next_month = divmod(absolute_month, 12)

    return f"{next_year}-{next_month + 1:02d}"


def _monthly_confidence(
    transactions: list[Transaction],
    as_of: date,
) -> list[MonthlyForecastConfidenceOut]:
    if not transactions:
        return []

    counts: dict[str, int] = defaultdict(int)

    for transaction in transactions:
        counts[_month_key(transaction.posted_on)] += 1

    current_month = _month_key(as_of)
    earliest_month = _shift_month(
        current_month, -_MONTHLY_CONFIDENCE_LOOKBACK_MONTHS
    )

    eligible_months = sorted(
        month
        for month in counts
        if earliest_month <= month < current_month
    )

    return [
        MonthlyForecastConfidenceOut(
            month=month,
            score=round(
                min(
                    counts[month]
                    / _MONTHLY_CONFIDENCE_TARGET_COUNT
                    * 100,
                    100.0,
                ),
                1,
            ),
            transaction_count=counts[month],
        )
        for month in eligible_months
    ]
