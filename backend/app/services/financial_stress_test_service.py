from calendar import monthrange
from datetime import date, timedelta
from math import ceil

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FinancialAccount, PlaidItem, Transaction
from app.recurring import detect_recurring
from app.schemas import (
    FinancialStressTestOut,
    FinancialStressTestRequest,
    ForecastConfidenceOut,
    GoalConflictDetectionRequest,
    SafeToSpendRequest,
    StressAffectedGoalOut,
    StressRecoveryRecommendationOut,
    StressResilienceFactorOut,
)
from app.services.forecast_confidence_service import (
    calculate_forecast_confidence,
)
from app.services.goal_conflict_detection_service import (
    detect_goal_conflicts,
)
from app.services.goal_impact_service import calculate_goal_impacts
from app.services.safe_to_spend_service import (
    calculate_safe_to_spend,
)

_DURATION_REQUIRED_SCENARIOS = {
    "temporary_income_loss",
    "delayed_paycheck",
}

# Scenarios whose dollar impact is derived from real account/
# transaction data rather than a manually entered lump sum.
_DERIVED_AMOUNT_SCENARIOS = {
    "income_reduction",
    "recurring_expense_increase",
    "combined",
}

_MONTHLY_IMPACT_SCENARIOS = {
    "income_reduction",
    "recurring_expense_increase",
    "combined",
}

_SCENARIO_LABELS = {
    "emergency_expense": "emergency expense",
    "temporary_income_loss": "temporary income loss",
    "delayed_paycheck": "delayed paycheck",
    "recurring_bill_increase": "recurring bill increase",
    "income_reduction": "temporary income reduction",
    "one_time_expense": "unexpected one-time expense",
    "recurring_expense_increase": "recurring expense increase",
    "combined": "combined downside scenario",
}

_SCENARIO_RECOMMENDATIONS = {
    "emergency_expense": (
        "Keep an emergency fund earmarked specifically for "
        "unexpected costs like this."
    ),
    "temporary_income_loss": (
        "Look into short-term income sources or unemployment "
        "support to bridge the gap."
    ),
    "delayed_paycheck": (
        "Confirm the revised payroll timeline with your employer "
        "and avoid scheduling large payments until it arrives."
    ),
    "recurring_bill_increase": (
        "Contact the biller to negotiate the increase or look for "
        "a lower-cost alternative."
    ),
    "income_reduction": (
        "Look into short-term income sources or unemployment "
        "support to bridge the gap."
    ),
    "one_time_expense": (
        "Keep an emergency fund earmarked specifically for "
        "unexpected costs like this."
    ),
    "recurring_expense_increase": (
        "Contact the biller to negotiate the increase or look for "
        "a lower-cost alternative."
    ),
    "combined": (
        "Review each contributing factor individually — combined "
        "downside events benefit most from having several small "
        "mitigations rather than one large fix."
    ),
}

_STRAINED_THRESHOLD_RATIO = 0.5
_CONFIDENCE_PENALTY_PER_DAY = 0.3
_MAX_CONFIDENCE_PENALTY = 30.0

_TRAILING_MONTHS_FOR_INCOME_AVERAGE = 3

# Resilience score weights. Each factor is independently bounded to
# [0, 100]; weights sum to 100 so the overall score is a bounded
# weighted average — never fabricated, always derivable from the
# other reported fields.
_RESILIENCE_WEIGHTS = {
    "liquidity_remaining": 35.0,
    "monthly_cash_flow_margin": 20.0,
    "safe_to_spend_reduction": 20.0,
    "goal_disruption": 15.0,
    "recurring_obligation_pressure": 10.0,
}

_RESILIENCE_LABELS = {
    "liquidity_remaining": "Liquidity remaining after stress",
    "monthly_cash_flow_margin": "Monthly cash-flow margin",
    "safe_to_spend_reduction": "Safe-to-spend reduction",
    "goal_disruption": "Goal disruption",
    "recurring_obligation_pressure": "Recurring-obligation pressure",
}

_SEVERITY_THRESHOLDS = (
    (80.0, "low"),
    (60.0, "moderate"),
    (35.0, "high"),
)

_DATA_DISCLAIMER = (
    "This is a simulation based on your current Discero data, not "
    "a probabilistic forecast or financial advice."
)

# Matches financial_resilience_service's existing runway convention
# so a "days of runway" figure means the same thing everywhere in
# Discero.
_DAYS_PER_MONTH = 30

# Which key-driver bucket each non-combined scenario type belongs to,
# for the "biggest source of stress" field. "combined" is resolved
# separately by comparing each component's actual cents impact.
_SCENARIO_KEY_DRIVER = {
    "emergency_expense": "emergency_expense",
    "one_time_expense": "emergency_expense",
    "temporary_income_loss": "income_loss",
    "delayed_paycheck": "income_loss",
    "income_reduction": "income_loss",
    "recurring_bill_increase": "recurring_expense_increase",
    "recurring_expense_increase": "recurring_expense_increase",
}


def run_financial_stress_test(
    db: Session,
    user_id: int,
    payload: FinancialStressTestRequest,
    *,
    as_of: date | None = None,
) -> FinancialStressTestOut:
    calculation_date = as_of or date.today()

    if payload.event_date < calculation_date:
        raise ValueError(
            "event date cannot be before the calculation date"
        )

    if (
        payload.scenario_type in _DURATION_REQUIRED_SCENARIOS
        and payload.duration_days is None
    ):
        raise ValueError(
            "duration_days is required for the "
            f"{_SCENARIO_LABELS[payload.scenario_type]} scenario"
        )

    safe_to_spend = calculate_safe_to_spend(
        db,
        user_id,
        SafeToSpendRequest(
            safety_reserve_cents=payload.safety_reserve_cents,
            essential_spending_cents=(
                payload.essential_spending_cents
            ),
            horizon_days=payload.horizon_days,
        ),
        as_of=calculation_date,
    )

    if payload.event_date > safe_to_spend.through_date:
        raise ValueError(
            "event date must fall within the selected horizon"
        )

    average_monthly_income = _average_monthly_income_cents(
        db, user_id, calculation_date
    )
    recurring_obligations_cents = (
        safe_to_spend.breakdown.upcoming_obligations_cents
    )

    total_impact, monthly_reduction = _resolve_stress_amount(
        payload,
        average_monthly_income_cents=average_monthly_income,
        recurring_obligations_cents=recurring_obligations_cents,
    )

    safe_before = safe_to_spend.safe_to_spend_cents
    raw_safe_after = safe_before - total_impact
    safe_after = max(raw_safe_after, 0)
    shortfall = max(-raw_safe_after, 0)

    risk_level = _determine_risk_level(
        total_impact,
        safe_before,
        shortfall,
    )
    duration_applies = (
        payload.scenario_type in _DURATION_REQUIRED_SCENARIOS
    )
    confidence_score = _calculate_confidence(
        safe_to_spend.confidence_score,
        payload.duration_days if duration_applies else None,
    )
    recovery_days = _estimate_recovery_days(
        payload.scenario_type,
        payload.duration_days,
        shortfall,
    )

    baseline_monthly_capacity = max(
        average_monthly_income - recurring_obligations_cents,
        0,
    )
    adjusted_monthly_capacity = max(
        baseline_monthly_capacity - monthly_reduction,
        0,
    )

    affected_goals: list[StressAffectedGoalOut] = []

    if monthly_reduction > 0:
        affected_goals = _compute_affected_goals(
            db,
            user_id,
            baseline_monthly_capacity_cents=baseline_monthly_capacity,
            monthly_reduction_cents=monthly_reduction,
            as_of=calculation_date,
        )

    goal_impacts = calculate_goal_impacts(
        db,
        user_id,
        baseline_monthly_capacity_cents=baseline_monthly_capacity,
        adjusted_monthly_capacity_cents=adjusted_monthly_capacity,
        as_of=calculation_date,
    )

    resilience_factors = _build_resilience_factors(
        raw_safe_after,
        safe_before,
        total_impact,
        average_monthly_income,
        monthly_reduction,
        recurring_obligations_cents,
        affected_goals,
    )
    resilience_score = round(
        sum(
            factor.score * factor.weight / 100
            for factor in resilience_factors
        ),
        1,
    )
    severity = _determine_severity(resilience_score)

    balance_change = raw_safe_after - safe_before
    balance_change_percent = (
        round(balance_change / safe_before * 100, 1)
        if safe_before > 0
        else 0.0
    )

    net_monthly_cash_flow = (
        baseline_monthly_capacity - monthly_reduction
    )
    runway_days = _runway_days(
        safe_to_spend.breakdown.liquid_balance_cents,
        net_monthly_cash_flow,
    )
    first_shortfall_date = _first_shortfall_date(
        calculation_date=calculation_date,
        through_date=safe_to_spend.through_date,
        event_date=payload.event_date,
        shortfall_cents=shortfall,
        runway_days=runway_days,
    )
    key_driver = _determine_key_driver(
        payload,
        safe_before_cents=safe_before,
        average_monthly_income_cents=average_monthly_income,
        recurring_obligations_cents=recurring_obligations_cents,
    )
    forecast_confidence = _build_forecast_confidence(
        db, user_id, calculation_date
    )
    recovery_recommendation = _build_recovery_recommendation(
        key_driver=key_driver,
        horizon_days=payload.horizon_days,
        shortfall_cents=shortfall,
        safe_before_cents=safe_before,
        total_impact_cents=total_impact,
        net_monthly_cash_flow_cents=net_monthly_cash_flow,
        runway_days=runway_days,
    )
    explanations = _build_explanations(
        horizon_days=payload.horizon_days,
        shortfall_cents=shortfall,
        first_shortfall_date=first_shortfall_date,
        runway_days=runway_days,
        forecast_confidence=forecast_confidence,
    )

    scenario_name = payload.scenario_name

    return FinancialStressTestOut(
        scenario_type=payload.scenario_type,
        scenario_name=scenario_name,
        event_date=payload.event_date,
        duration_days=payload.duration_days,
        as_of=safe_to_spend.as_of,
        through_date=safe_to_spend.through_date,
        risk_level=risk_level,
        severity=severity,
        safe_to_spend_before_stress_cents=safe_before,
        safe_to_spend_after_stress_cents=safe_after,
        total_financial_impact_cents=total_impact,
        shortfall_cents=shortfall,
        baseline_projected_balance_cents=safe_before,
        stressed_projected_balance_cents=raw_safe_after,
        balance_change_cents=balance_change,
        balance_change_percent=balance_change_percent,
        cash_flow_positive=raw_safe_after >= 0,
        resilience_score=resilience_score,
        resilience_factors=resilience_factors,
        affected_goals=affected_goals,
        confidence_score=confidence_score,
        estimated_recovery_days=recovery_days,
        data_disclaimer=_DATA_DISCLAIMER,
        goal_impacts=goal_impacts,
        explanation=_build_explanation(
            scenario_type=payload.scenario_type,
            scenario_name=scenario_name,
            total_impact_cents=total_impact,
            safe_before_cents=safe_before,
            safe_after_cents=safe_after,
            shortfall_cents=shortfall,
            risk_level=risk_level,
        ),
        recommendations=_build_recommendations(
            scenario_type=payload.scenario_type,
            risk_level=risk_level,
            safety_reserve_cents=payload.safety_reserve_cents,
            shortfall_cents=shortfall,
        ),
        safe_to_spend=safe_to_spend,
        runway_days=runway_days,
        first_shortfall_date=first_shortfall_date,
        key_driver=key_driver,
        forecast_confidence=forecast_confidence,
        recovery_recommendation=recovery_recommendation,
        explanations=explanations,
    )


def _determine_risk_level(
    total_impact_cents: int,
    safe_before_cents: int,
    shortfall_cents: int,
) -> str:
    if safe_before_cents <= 0 or shortfall_cents > 0:
        return "critical"

    if total_impact_cents > round(
        safe_before_cents * _STRAINED_THRESHOLD_RATIO
    ):
        return "strained"

    return "resilient"


def _calculate_confidence(
    base_confidence: float,
    duration_days: int | None,
) -> float:
    penalty = min(
        (duration_days or 0) * _CONFIDENCE_PENALTY_PER_DAY,
        _MAX_CONFIDENCE_PENALTY,
    )

    return round(max(base_confidence - penalty, 0.0), 1)


def _estimate_recovery_days(
    scenario_type: str,
    duration_days: int | None,
    shortfall_cents: int,
) -> int | None:
    if scenario_type in _DURATION_REQUIRED_SCENARIOS:
        return duration_days

    if shortfall_cents == 0:
        return 0

    return None


def _derive_temporary_income_loss_cents(
    payload: FinancialStressTestRequest,
    average_monthly_income_cents: int,
) -> int | None:
    """Total income lost across the requested duration when the
    caller didn't supply an explicit stress_amount_cents.

    Models a full (100%) loss of the same authoritative trailing-
    average monthly income income_reduction/combined already use --
    never a model-invented figure, never a partial-loss guess. Returns
    None (never a fabricated 0) when there isn't enough income history
    or duration to derive from, so the caller can raise instead of
    silently modeling a $0 loss.
    """
    if average_monthly_income_cents <= 0 or not payload.duration_days:
        return None

    return round(
        average_monthly_income_cents
        * payload.duration_days
        / _DAYS_PER_MONTH
    )


def _resolve_stress_amount(
    payload: FinancialStressTestRequest,
    *,
    average_monthly_income_cents: int,
    recurring_obligations_cents: int,
) -> tuple[int, int]:
    """Returns (total_impact_cents, monthly_reduction_cents).

    monthly_reduction_cents is the portion of the impact that recurs
    every month (used for goal/cash-flow-margin analysis); one-time
    costs contribute 0 to it.
    """
    scenario_type = payload.scenario_type

    if scenario_type not in _DERIVED_AMOUNT_SCENARIOS:
        stress_amount_cents = payload.stress_amount_cents

        # A full income-loss scenario doesn't force the user to state
        # a dollar amount -- the same authoritative trailing-average
        # income this module already uses for income_reduction/
        # combined stands in for it. An explicitly supplied amount
        # always wins; this only fills a gap.
        if not stress_amount_cents and scenario_type == "temporary_income_loss":
            stress_amount_cents = _derive_temporary_income_loss_cents(
                payload, average_monthly_income_cents
            )

        if not stress_amount_cents:
            if scenario_type == "temporary_income_loss":
                raise ValueError(
                    "I don't have enough income history to estimate "
                    "your normal monthly income for this scenario"
                )

            raise ValueError(
                "stress_amount_cents is required for the "
                f"{_SCENARIO_LABELS[scenario_type]} scenario"
            )

        return stress_amount_cents, 0

    if scenario_type == "income_reduction":
        return _income_reduction_amount(
            payload, average_monthly_income_cents
        )

    if scenario_type == "recurring_expense_increase":
        return _recurring_increase_amount(
            payload, recurring_obligations_cents
        )

    return _combined_amount(
        payload,
        average_monthly_income_cents,
        recurring_obligations_cents,
    )


def _income_reduction_amount(
    payload: FinancialStressTestRequest,
    average_monthly_income_cents: int,
) -> tuple[int, int]:
    if payload.income_reduction_percent is None:
        raise ValueError(
            "income_reduction_percent is required for the "
            "temporary income reduction scenario"
        )

    if average_monthly_income_cents <= 0:
        raise ValueError(
            "not enough income history to model an income "
            "reduction scenario"
        )

    amount = round(
        average_monthly_income_cents
        * payload.income_reduction_percent
        / 100
    )

    return amount, amount


def _recurring_increase_amount(
    payload: FinancialStressTestRequest,
    recurring_obligations_cents: int,
) -> tuple[int, int]:
    if payload.recurring_expense_increase_percent is None:
        raise ValueError(
            "recurring_expense_increase_percent is required for "
            "the recurring expense increase scenario"
        )

    if recurring_obligations_cents <= 0:
        raise ValueError(
            "no recurring obligations were found to model an "
            "increase against"
        )

    amount = round(
        recurring_obligations_cents
        * payload.recurring_expense_increase_percent
        / 100
    )

    return amount, amount


def _combined_amount(
    payload: FinancialStressTestRequest,
    average_monthly_income_cents: int,
    recurring_obligations_cents: int,
) -> tuple[int, int]:
    total = 0
    monthly = 0
    provided = False

    if payload.stress_amount_cents:
        total += payload.stress_amount_cents
        provided = True

    if payload.income_reduction_percent is not None:
        if average_monthly_income_cents <= 0:
            raise ValueError(
                "not enough income history to model an income "
                "reduction component"
            )

        income_amount = round(
            average_monthly_income_cents
            * payload.income_reduction_percent
            / 100
        )
        total += income_amount
        monthly += income_amount
        provided = True

    if payload.recurring_expense_increase_percent is not None:
        if recurring_obligations_cents <= 0:
            raise ValueError(
                "no recurring obligations were found to model an "
                "increase component"
            )

        recurring_amount = round(
            recurring_obligations_cents
            * payload.recurring_expense_increase_percent
            / 100
        )
        total += recurring_amount
        monthly += recurring_amount
        provided = True

    if not provided:
        raise ValueError(
            "at least one of stress_amount_cents, "
            "income_reduction_percent, or "
            "recurring_expense_increase_percent is required for "
            "the combined scenario"
        )

    return total, monthly


def _average_monthly_income_cents(
    db: Session,
    user_id: int,
    as_of: date,
) -> int:
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

    return round(sum(totals[month] for month in recent) / len(recent))


def _compute_affected_goals(
    db: Session,
    user_id: int,
    *,
    baseline_monthly_capacity_cents: int,
    monthly_reduction_cents: int,
    as_of: date,
) -> list[StressAffectedGoalOut]:
    baseline = detect_goal_conflicts(
        db,
        user_id,
        GoalConflictDetectionRequest(
            monthly_savings_capacity_cents=(
                baseline_monthly_capacity_cents
            )
        ),
        as_of=as_of,
    )

    if not baseline.goals:
        return []

    stressed_capacity = max(
        baseline_monthly_capacity_cents - monthly_reduction_cents,
        0,
    )

    stressed = detect_goal_conflicts(
        db,
        user_id,
        GoalConflictDetectionRequest(
            monthly_savings_capacity_cents=stressed_capacity
        ),
        as_of=as_of,
    )
    stressed_by_id = {goal.goal_id: goal for goal in stressed.goals}

    affected: list[StressAffectedGoalOut] = []

    for before in baseline.goals:
        after = stressed_by_id.get(before.goal_id)

        if after is None or (
            after.monthly_shortfall_cents
            <= before.monthly_shortfall_cents
            and after.status == before.status
        ):
            continue

        delay_months = None

        if (
            before.allocated_monthly_cents > 0
            and after.allocated_monthly_cents > 0
            and before.remaining_cents > 0
        ):
            delay_months = ceil(
                before.remaining_cents / after.allocated_monthly_cents
            ) - ceil(
                before.remaining_cents
                / before.allocated_monthly_cents
            )

        affected.append(
            StressAffectedGoalOut(
                goal_id=before.goal_id,
                name=before.name,
                status_before=before.status,
                status_after=after.status,
                monthly_shortfall_before_cents=(
                    before.monthly_shortfall_cents
                ),
                monthly_shortfall_after_cents=(
                    after.monthly_shortfall_cents
                ),
                estimated_delay_months=delay_months,
            )
        )

    return affected


def _liquid_accounts(
    db: Session,
    user_id: int,
) -> list[FinancialAccount]:
    return list(
        db.execute(
            select(FinancialAccount)
            .join(
                PlaidItem,
                FinancialAccount.plaid_item_id == PlaidItem.id,
            )
            .where(
                PlaidItem.user_id == user_id,
                FinancialAccount.account_type == "depository",
            )
        ).scalars()
    )


def _build_forecast_confidence(
    db: Session,
    user_id: int,
    as_of: date,
) -> ForecastConfidenceOut:
    """Reuses Confidence-Aware Forecasting 2.0 as context.

    Mirrors the same inputs the cash-flow-forecast route builds. This
    is not a stress-specific confidence score, and stress severity
    does not feed into it -- a severe outcome with high forecast
    confidence, or a mild outcome with low confidence, are both valid.
    """
    transactions = list(
        db.scalars(
            select(Transaction).where(Transaction.user_id == user_id)
        ).all()
    )
    liquid_accounts = _liquid_accounts(db, user_id)
    recurring_items = detect_recurring(transactions, as_of=as_of)
    days_in_month = monthrange(as_of.year, as_of.month)[1]
    month_end = as_of.replace(day=days_in_month)

    return calculate_forecast_confidence(
        db,
        user_id,
        as_of=as_of,
        days_remaining=max((month_end - as_of).days, 0),
        days_in_month=days_in_month,
        transactions=transactions,
        liquid_accounts=liquid_accounts,
        recurring_items=recurring_items,
    )


def _runway_days(
    liquid_balance_cents: int,
    net_monthly_cash_flow_cents: int,
) -> int | None:
    """Days of stressed liquid runway, or None when unbounded.

    Mirrors financial_resilience_service's runway convention (30-day
    month, liquid balance / monthly burn) so "days of runway" means
    the same thing everywhere in Discero.
    """
    if net_monthly_cash_flow_cents >= 0:
        return None

    if liquid_balance_cents <= 0:
        return 0

    monthly_burn_cents = -net_monthly_cash_flow_cents

    return round(
        liquid_balance_cents / monthly_burn_cents * _DAYS_PER_MONTH
    )


def _first_shortfall_date(
    *,
    calculation_date: date,
    through_date: date,
    event_date: date,
    shortfall_cents: int,
    runway_days: int | None,
) -> date | None:
    """Earliest date liquidity is projected to drop below zero.

    Two independent depletion mechanisms are modeled: an ongoing
    stressed monthly burn (via `runway_days`, only reported when it
    falls within the selected horizon), and the scenario's own
    immediate lump-sum impact (realized on `event_date` whenever it
    leaves a shortfall). The earlier of the two, if any, is reported.
    """
    result: date | None = None

    if runway_days is not None:
        burn_shortfall_date = calculation_date + timedelta(
            days=runway_days
        )

        if burn_shortfall_date <= through_date:
            result = burn_shortfall_date

    if shortfall_cents > 0 and (
        result is None or event_date < result
    ):
        result = event_date

    return result


def _combined_components(
    payload: FinancialStressTestRequest,
    average_monthly_income_cents: int,
    recurring_obligations_cents: int,
) -> dict[str, int]:
    emergency_cents = payload.stress_amount_cents or 0

    income_cents = 0

    if (
        payload.income_reduction_percent is not None
        and average_monthly_income_cents > 0
    ):
        income_cents = round(
            average_monthly_income_cents
            * payload.income_reduction_percent
            / 100
        )

    recurring_cents = 0

    if (
        payload.recurring_expense_increase_percent is not None
        and recurring_obligations_cents > 0
    ):
        recurring_cents = round(
            recurring_obligations_cents
            * payload.recurring_expense_increase_percent
            / 100
        )

    return {
        "emergency_expense": emergency_cents,
        "income_loss": income_cents,
        "recurring_expense_increase": recurring_cents,
    }


def _determine_key_driver(
    payload: FinancialStressTestRequest,
    *,
    safe_before_cents: int,
    average_monthly_income_cents: int,
    recurring_obligations_cents: int,
) -> str:
    if safe_before_cents <= 0:
        return "baseline_shortfall"

    if payload.scenario_type == "combined":
        components = _combined_components(
            payload,
            average_monthly_income_cents,
            recurring_obligations_cents,
        )
        return max(components, key=lambda key: components[key])

    return _SCENARIO_KEY_DRIVER[payload.scenario_type]


def _build_recovery_recommendation(
    *,
    key_driver: str,
    horizon_days: int,
    shortfall_cents: int,
    safe_before_cents: int,
    total_impact_cents: int,
    net_monthly_cash_flow_cents: int,
    runway_days: int | None,
) -> StressRecoveryRecommendationOut:
    if shortfall_cents == 0 and (
        runway_days is None or runway_days >= horizon_days
    ):
        return StressRecoveryRecommendationOut(
            type="no_action_required",
            message=(
                "You remain within your safe-to-spend buffer through "
                f"the {horizon_days}-day horizon; no adjustment is "
                "needed for this scenario."
            ),
            adjustment_cents=None,
            verified=True,
        )

    if shortfall_cents > 0:
        adjustment_cents = shortfall_cents
        # Re-runs the exact formula the stress test itself uses
        # (raw_safe_after = safe_before - total_impact) with the
        # proposed adjustment applied, rather than assuming the
        # arithmetic works out.
        adjusted_raw_safe_after = safe_before_cents - (
            total_impact_cents - adjustment_cents
        )
        verified = adjusted_raw_safe_after >= 0
        outcome = "eliminate the projected shortfall"
        cadence = ""
    else:
        adjustment_cents = -net_monthly_cash_flow_cents
        verified = (
            net_monthly_cash_flow_cents + adjustment_cents
        ) >= 0
        outcome = f"keep your runway beyond the {horizon_days}-day horizon"
        cadence = "/month"

    amount = _format_currency(adjustment_cents)

    if key_driver == "income_loss":
        return StressRecoveryRecommendationOut(
            type="replace_lost_income",
            message=(
                f"Replacing {amount}{cadence} of lost income would "
                f"{outcome}."
            ),
            adjustment_cents=adjustment_cents,
            verified=verified,
        )

    if key_driver == "recurring_expense_increase":
        return StressRecoveryRecommendationOut(
            type="reduce_stress_expense",
            message=(
                f"Reducing the added recurring expense by "
                f"{amount}{cadence} would {outcome}."
            ),
            adjustment_cents=adjustment_cents,
            verified=verified,
        )

    return StressRecoveryRecommendationOut(
        type="preserve_cash_buffer",
        message=(
            f"This scenario creates a {amount} gap; keeping a cash "
            f"buffer of at least that amount would {outcome}."
        ),
        adjustment_cents=adjustment_cents,
        verified=verified,
    )


def _build_explanations(
    *,
    horizon_days: int,
    shortfall_cents: int,
    first_shortfall_date: date | None,
    runway_days: int | None,
    forecast_confidence: ForecastConfidenceOut,
) -> list[str]:
    items: list[str] = []

    if shortfall_cents == 0:
        items.append(
            "Your projected finances remain positive through the "
            f"{horizon_days}-day stress horizon."
        )
    else:
        items.append(
            f"This scenario creates a "
            f"{_format_currency(shortfall_cents)} shortfall against "
            "your safe-to-spend balance."
        )

        if first_shortfall_date is not None:
            items.append(
                "The shortfall is first projected on "
                f"{first_shortfall_date.isoformat()}."
            )

    if runway_days is not None:
        items.append(
            "At the stressed monthly cash-flow margin, your liquid "
            f"balance would last about {runway_days} day(s)."
        )

    items.append(
        f"Forecast confidence is {forecast_confidence.level} "
        f"({round(forecast_confidence.score)}%), based on your "
        "current transaction history and recognized recurring "
        "activity."
    )

    return items


def _build_resilience_factors(
    raw_safe_after_cents: int,
    safe_before_cents: int,
    total_impact_cents: int,
    average_monthly_income_cents: int,
    monthly_reduction_cents: int,
    recurring_obligations_cents: int,
    affected_goals: list[StressAffectedGoalOut],
) -> list[StressResilienceFactorOut]:
    if raw_safe_after_cents <= 0:
        liquidity_score = 0.0
    elif safe_before_cents > 0:
        liquidity_score = min(
            100.0,
            round(
                raw_safe_after_cents / safe_before_cents * 100, 1
            ),
        )
    else:
        liquidity_score = 100.0

    if safe_before_cents > 0:
        impact_percent = min(
            100.0, total_impact_cents / safe_before_cents * 100
        )
        safe_to_spend_score = round(100 - impact_percent, 1)
    else:
        safe_to_spend_score = 0.0

    if average_monthly_income_cents > 0:
        margin_percent = min(
            100.0,
            monthly_reduction_cents
            / average_monthly_income_cents
            * 100,
        )
        margin_score = round(100 - margin_percent, 1)
    else:
        margin_score = 100.0 if monthly_reduction_cents == 0 else 0.0

    if not affected_goals:
        goal_score = 100.0
    else:
        goal_score = 0.0

    if average_monthly_income_cents > 0:
        pressure_percent = min(
            100.0,
            recurring_obligations_cents
            / average_monthly_income_cents
            * 100,
        )
        pressure_score = round(100 - pressure_percent, 1)
    else:
        pressure_score = 50.0

    scores = {
        "liquidity_remaining": liquidity_score,
        "monthly_cash_flow_margin": margin_score,
        "safe_to_spend_reduction": safe_to_spend_score,
        "goal_disruption": goal_score,
        "recurring_obligation_pressure": pressure_score,
    }

    return [
        StressResilienceFactorOut(
            key=key,
            label=_RESILIENCE_LABELS[key],
            weight=weight,
            score=max(0.0, min(100.0, scores[key])),
        )
        for key, weight in _RESILIENCE_WEIGHTS.items()
    ]


def _determine_severity(resilience_score: float) -> str:
    for threshold, label in _SEVERITY_THRESHOLDS:
        if resilience_score >= threshold:
            return label

    return "critical"


def _format_currency(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def _build_explanation(
    *,
    scenario_type: str,
    scenario_name: str,
    total_impact_cents: int,
    safe_before_cents: int,
    safe_after_cents: int,
    shortfall_cents: int,
    risk_level: str,
) -> str:
    impact = _format_currency(total_impact_cents)
    safe_before = _format_currency(safe_before_cents)
    safe_after = _format_currency(safe_after_cents)
    shortfall = _format_currency(shortfall_cents)

    if risk_level == "critical":
        explanation = (
            f"{scenario_name} would cost {impact}, which exceeds "
            f"your current safe-to-spend amount of {safe_before} "
            f"and leaves a shortfall of {shortfall}. Your finances "
            "would be critically strained by this event."
        )
    elif risk_level == "strained":
        explanation = (
            f"{scenario_name} would cost {impact}, using more than "
            f"half of your {safe_before} safe-to-spend and leaving "
            f"only {safe_after} available. Your finances would be "
            "strained but would not go negative."
        )
    else:
        explanation = (
            f"{scenario_name} would cost {impact}. Your finances are "
            f"resilient to this event, leaving {safe_after} of your "
            f"{safe_before} safe-to-spend available afterward."
        )

    if scenario_type == "recurring_bill_increase":
        explanation += (
            f" This {impact} figure is the total impact you "
            "entered for the increase; it is not automatically "
            "multiplied by month."
        )

    return explanation


def _build_recommendations(
    *,
    scenario_type: str,
    risk_level: str,
    safety_reserve_cents: int,
    shortfall_cents: int,
) -> list[str]:
    recommendations = [
        _SCENARIO_RECOMMENDATIONS[scenario_type],
    ]

    if risk_level == "critical":
        recommendations.append(
            "Reduce non-essential spending immediately to cover "
            f"the {_format_currency(shortfall_cents)} shortfall."
        )
        recommendations.append(
            "Consider a short-term transfer from savings or a "
            "low-interest line of credit to bridge the gap."
        )
    elif risk_level == "strained":
        recommendations.append(
            "Pause discretionary purchases until your "
            "safe-to-spend balance recovers."
        )

        if safety_reserve_cents == 0:
            recommendations.append(
                "Build a safety reserve so future stress events "
                "are easier to absorb."
            )
    else:
        recommendations.append(
            "Maintain your current safety reserve; it is "
            "sufficient to absorb this scenario."
        )

    return recommendations
