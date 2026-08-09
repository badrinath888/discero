"""Deterministic proactive Recommendation Engine.

Combines existing deterministic services (Safe-to-Spend, goal-conflict
detection, budget progress, cash-flow forecast confidence, monthly
insights) into a single ranked list answering "what should I do next?"
No LLM is involved anywhere in this module -- every number and every
piece of reasoning traces back to a real deterministic service call.
Ranking is a pure function of severity, so results are stable and
reproducible for the same underlying data.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
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
from app.schemas import (
    RecommendationOut,
    RecommendationSourceSignalOut,
    RecommendationsOut,
    SafeToSpendRequest,
)
from app.services.goal_intelligence_service import evaluate_goal_intelligence
from app.services.major_purchase_service import (
    _average_monthly_income_cents,
)
from app.services.safe_to_spend_service import calculate_safe_to_spend

_MAX_RECOMMENDATIONS = 8

_SEVERITY_WEIGHT = {
    "critical": 5,
    "warning": 4,
    "opportunity": 3,
    "positive": 2,
    "informational": 1,
}


def _currency(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    return f"{sign}${abs(cents) / 100:,.2f}"


def _percent(value: float) -> str:
    return f"{value:.0f}%"


def _signal(label: str, value_display: str) -> RecommendationSourceSignalOut:
    return RecommendationSourceSignalOut(
        label=label, value_display=value_display
    )


def _rule_no_linked_accounts(
    db: Session, user_id: int, as_of: date
) -> RecommendationOut | None:
    return RecommendationOut(
        id="no-linked-accounts",
        category="data_quality",
        severity="warning",
        priority=0,
        title="Connect a bank account to unlock full intelligence",
        summary=(
            "Safe-to-Spend, forecasting, and liquidity insights all "
            "need at least one connected account."
        ),
        why="No linked accounts were found for this user.",
        recommended_action="Connect a bank account to get started.",
        confidence=None,
        source_signals=[],
        deep_link="/accounts",
        evaluated_at=as_of,
    )


def _rule_no_recurring_detected(
    db: Session, user_id: int, as_of: date
) -> RecommendationOut | None:
    count = db.scalar(
        select(func.count())
        .select_from(RecurringItem)
        .where(RecurringItem.user_id == user_id)
    )

    if count:
        return None

    return RecommendationOut(
        id="no-recurring-detected",
        category="data_quality",
        severity="informational",
        priority=0,
        title="No recurring bills detected yet",
        summary=(
            "FinSight hasn't identified any recurring bills or "
            "subscriptions from your transaction history."
        ),
        why=(
            "Recurring-payment detection needs a consistent pattern "
            "of matching transactions for a merchant."
        ),
        recommended_action=(
            "Sync more transaction history to improve recurring-bill "
            "tracking and forecasts."
        ),
        confidence=None,
        source_signals=[],
        deep_link="/recurring",
        evaluated_at=as_of,
    )


def _rule_goal_conflict(
    db: Session, user_id: int, as_of: date
) -> RecommendationOut | None:
    has_goals = db.scalar(
        select(func.count())
        .select_from(SavingsGoal)
        .where(SavingsGoal.user_id == user_id)
    )

    if not has_goals:
        return None

    capacity = _average_monthly_income_cents(db, user_id, as_of)
    result = evaluate_goal_intelligence(
        db, user_id, monthly_capacity_cents=capacity, as_of=as_of
    )

    if result.conflict_status == "no_conflict":
        return None

    shortfall = result.total_shortfall_cents
    severity = "critical" if result.conflict_status == "conflict" else "warning"

    pressure_goal = next(
        (
            g
            for g in result.goals
            if g.goal_id == result.largest_pressure_goal_id
        ),
        None,
    )

    # Prefer a specific, named goal over a vague aggregate figure --
    # "X needs $Y more/month" is more actionable than "your goals need
    # $Y/month" when one goal is clearly driving the gap.
    if pressure_goal and pressure_goal.monthly_gap_cents > 0:
        title = (
            f"{pressure_goal.name} needs "
            f"{_currency(pressure_goal.monthly_gap_cents)} more per "
            "month to stay on track"
        )
    elif shortfall > 0:
        title = f"Close your {_currency(shortfall)}/month goal gap"
    else:
        title = "Your goals are tightly funded"

    action_parts = []
    if shortfall > 0:
        action_parts.append(
            f"Increase monthly savings by {_currency(shortfall)}"
        )
    if pressure_goal and pressure_goal.suggested_feasible_target_date:
        action_parts.append(
            f"moving {pressure_goal.name}'s target date to "
            f"{pressure_goal.suggested_feasible_target_date.strftime('%B %Y')}"
            " would fit your current capacity"
        )
    action = (
        (", or ".join(action_parts) + ".")
        if action_parts
        else "Your capacity covers your goals with little room to spare."
    )

    return RecommendationOut(
        id="goal-conflict",
        category="goals",
        severity=severity,
        priority=0,
        title=title,
        summary=result.explanation,
        why=(
            f"Your goals require {_currency(result.total_required_cents)}"
            f"/month but your current capacity is "
            f"{_currency(result.total_capacity_cents)}/month."
        ),
        recommended_action=action,
        impact=(
            f"{_currency(shortfall)}/month shortfall" if shortfall > 0 else None
        ),
        confidence=result.confidence_score,
        source_signals=[
            _signal(
                "Monthly capacity",
                _currency(result.total_capacity_cents),
            ),
            _signal(
                "Required monthly",
                _currency(result.total_required_cents),
            ),
            _signal("Monthly shortfall", _currency(shortfall)),
        ],
        deep_link="/goals",
        evaluated_at=as_of,
    )


def _rule_budget_overage(
    db: Session, user_id: int, current_user: User, as_of: date
) -> RecommendationOut | None:
    from app.routers.budgets import budget_progress

    month = as_of.strftime("%Y-%m")
    has_budgets = db.scalar(
        select(func.count())
        .select_from(Budget)
        .where(Budget.user_id == user_id, Budget.month == month)
    )

    if not has_budgets:
        return None

    progress = budget_progress(
        user_id=user_id, month=month, db=db, current_user=current_user
    )
    overspent = [item for item in progress if item.overspent]

    if not overspent:
        return None

    worst = max(overspent, key=lambda item: item.percent_used)
    severity = "critical" if worst.percent_used >= 150 else "warning"

    return RecommendationOut(
        id=f"budget-overage-{worst.category}",
        category="budget",
        severity=severity,
        priority=0,
        title=(
            f"{worst.category} is {round(worst.percent_used)}% over budget"
        ),
        summary=(
            f"You've spent {_currency(worst.spent_cents)} of your "
            f"{_currency(worst.limit_cents)} {worst.category} budget "
            "this month."
        ),
        why=(
            f"{worst.category} spending exceeded its limit by "
            f"{_currency(worst.over_budget_cents)}."
        ),
        recommended_action=(
            f"Reduce {worst.category} spending by "
            f"{_currency(worst.over_budget_cents)} to eliminate this "
            "month's overage."
        ),
        impact=f"{_currency(worst.over_budget_cents)} over budget",
        confidence=None,
        source_signals=[
            _signal("Spent", _currency(worst.spent_cents)),
            _signal("Limit", _currency(worst.limit_cents)),
            _signal("Over by", _currency(worst.over_budget_cents)),
        ],
        deep_link="/budgets",
        evaluated_at=as_of,
    )


def _rule_safe_to_spend(
    db: Session, user_id: int, as_of: date
) -> RecommendationOut | None:
    result = calculate_safe_to_spend(
        db, user_id, SafeToSpendRequest(), as_of=as_of
    )

    if result.status == "negative":
        severity = "critical"
        title = "Your safe-to-spend is negative"
        action = (
            "Avoid new discretionary spending and review upcoming "
            "obligations."
        )
    elif result.status == "limited":
        severity = "warning"
        title = "Your safe-to-spend is limited"
        action = "Spend carefully until obligations clear or income arrives."
    else:
        # Only surface a positive note when there's real confidence
        # behind it -- otherwise this would be a fabricated metric.
        if result.confidence_score < 45:
            return None
        severity = "positive"
        title = "Your safe-to-spend position is healthy"
        action = "You have room for planned purchases or extra savings."

    why = (
        f"A projected shortfall of {_currency(result.shortfall_cents)} "
        "against upcoming obligations, essential spending, and your "
        "safety reserve."
        if result.shortfall_cents > 0
        else (
            "This reflects your liquid balance after upcoming "
            "obligations, essential spending, and your safety reserve."
        )
    )

    return RecommendationOut(
        id="safe-to-spend-status",
        category="liquidity",
        severity=severity,
        priority=0,
        title=title,
        summary=(
            f"You have {_currency(result.safe_to_spend_cents)} safe to "
            f"spend through {result.through_date.isoformat()}."
        ),
        why=why,
        recommended_action=action,
        impact=(
            f"{_currency(result.shortfall_cents)} shortfall"
            if result.shortfall_cents > 0
            else None
        ),
        confidence=result.confidence_score,
        source_signals=[
            _signal("Safe to spend", _currency(result.safe_to_spend_cents)),
            _signal("Shortfall", _currency(result.shortfall_cents)),
        ],
        deep_link="/decisions",
        evaluated_at=as_of,
    )


def _rule_forecast_confidence(
    db: Session, user_id: int, current_user: User, as_of: date
) -> RecommendationOut | None:
    from app.routers.transactions import cash_flow_forecast

    result = cash_flow_forecast(
        user_id=user_id, as_of=as_of, db=db, current_user=current_user
    )
    confidence = result.confidence

    if confidence.level == "high":
        return None

    negative_factors = [
        factor for factor in confidence.factors if factor.impact == "negative"
    ]
    top_factor = (
        min(negative_factors, key=lambda factor: factor.score)
        if negative_factors
        else None
    )
    severity = "warning" if confidence.level == "low" else "informational"

    return RecommendationOut(
        id="forecast-confidence",
        category="forecast",
        severity=severity,
        priority=0,
        title=(
            f"Forecast confidence is {confidence.level} "
            f"({round(confidence.score)}%)"
        ),
        summary=(
            top_factor.detail
            if top_factor
            else "Your cash-flow forecast currently has moderate uncertainty."
        ),
        why=(
            top_factor.label
            if top_factor
            else "Limited transaction/account history reduces forecast precision."
        ),
        recommended_action=(
            confidence.recommendations[0]
            if confidence.recommendations
            else "Sync more transaction history to improve forecast accuracy."
        ),
        confidence=confidence.score,
        source_signals=[
            _signal(factor.label, f"{round(factor.score)}%")
            for factor in negative_factors[:3]
        ],
        deep_link="/forecast",
        evaluated_at=as_of,
    )


def _rule_spending_trend(
    db: Session, user_id: int, current_user: User, as_of: date
) -> RecommendationOut | None:
    from app.routers.transactions import monthly_insights

    month = as_of.strftime("%Y-%m")
    result = monthly_insights(
        user_id=user_id, month=month, db=db, current_user=current_user
    )
    change = result.spending_change_percent

    if change is None:
        return None

    if change <= -10:
        return RecommendationOut(
            id="spending-trend-down",
            category="spending",
            severity="positive",
            priority=0,
            title="Your spending decreased this month",
            summary=(
                f"Spending is down {_percent(abs(change))} versus "
                f"{result.previous_month}."
            ),
            why=(
                f"You spent {_currency(abs(result.spending_change_cents))} "
                f"less than {result.previous_month}."
            ),
            recommended_action=(
                "Keep up the trend, or redirect the difference toward "
                "a savings goal."
            ),
            impact=f"{_currency(abs(result.spending_change_cents))} less spent",
            confidence=None,
            source_signals=[
                _signal("This month", _currency(result.spending_cents)),
            ],
            deep_link="/insights",
            evaluated_at=as_of,
        )

    if change >= 20:
        return RecommendationOut(
            id="spending-trend-up",
            category="spending",
            severity="warning",
            priority=0,
            title=f"Spending increased {round(change)}% this month",
            summary=(
                f"You spent {_currency(result.spending_cents)} this "
                f"month, up from {result.previous_month}."
            ),
            why="Month-over-month spending rose materially.",
            recommended_action="Review recent transactions to see what changed.",
            impact=f"{_currency(result.spending_change_cents)} more spent",
            confidence=None,
            source_signals=[
                _signal("This month", _currency(result.spending_cents)),
            ],
            deep_link="/insights",
            evaluated_at=as_of,
        )

    return None


def evaluate_recommendations(
    db: Session,
    user_id: int,
    current_user: User,
    *,
    as_of: date | None = None,
) -> RecommendationsOut:
    calculation_date = as_of or date.today()

    has_accounts = bool(
        db.scalar(
            select(func.count())
            .select_from(FinancialAccount)
            .join(PlaidItem)
            .where(PlaidItem.user_id == user_id)
        )
    )
    has_transactions = bool(
        db.scalar(
            select(func.count())
            .select_from(Transaction)
            .where(Transaction.user_id == user_id)
        )
    )

    candidates: list[RecommendationOut | None] = [
        _rule_goal_conflict(db, user_id, calculation_date),
    ]

    if has_accounts:
        candidates.append(
            _rule_budget_overage(
                db, user_id, current_user, calculation_date
            )
        )
        candidates.append(_rule_safe_to_spend(db, user_id, calculation_date))
        candidates.append(
            _rule_forecast_confidence(
                db, user_id, current_user, calculation_date
            )
        )
    else:
        candidates.append(
            _rule_no_linked_accounts(db, user_id, calculation_date)
        )

    if has_transactions:
        candidates.append(
            _rule_spending_trend(db, user_id, current_user, calculation_date)
        )
        candidates.append(
            _rule_no_recurring_detected(db, user_id, calculation_date)
        )

    recommendations = [c for c in candidates if c is not None]
    # Deterministic, reproducible order: severity first, then a stable
    # tie-break on id so ties never reorder between identical requests.
    recommendations.sort(
        key=lambda rec: (-_SEVERITY_WEIGHT[rec.severity], rec.id)
    )

    ranked = [
        rec.model_copy(update={"priority": index + 1})
        for index, rec in enumerate(recommendations[:_MAX_RECOMMENDATIONS])
    ]

    return RecommendationsOut(
        as_of=calculation_date, recommendations=ranked
    )
