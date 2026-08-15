"""What-If Simulator.

Compares a real baseline (today's actual Safe-to-Spend 2.0 result)
against a hypothetical adjustment applied only in memory -- no
Transaction, RecurringItem, or SavingsGoal row is ever written.

The baseline reuses `calculate_safe_to_spend` with the same enriched
opt-ins (`include_projected_income`, `include_goal_reserve`) the
SafeToSpendCard UI already uses, so a simulated result is measured
against the most truthful current picture Discero can produce. This
does not change `calculate_safe_to_spend` itself or any of its other
callers -- What-If is a new, additive consumer.

Each scenario type resolves to a single deterministic
`cost_delta_cents` (positive reduces safe-to-spend, negative
increases it), prorated against the horizon using the same
day-based convention `safe_to_spend_service` already uses for goal
reserve and projected income. The scenario result is derived from
the baseline's UNCLAMPED total (`safe_to_spend_cents -
shortfall_cents`, which recovers the true signed figure even when
the baseline itself is already in shortfall) so an existing shortfall
correctly compounds instead of being silently understated.
"""

from datetime import date

from sqlalchemy.orm import Session

from app.schemas import (
    GoalImpactOut,
    SafeToSpendExplanationOut,
    SafeToSpendOut,
    SafeToSpendRequest,
    WhatIfImpactOut,
    WhatIfOutcomeOut,
    WhatIfSimulationOut,
    WhatIfSimulationRequest,
)
from app.services.goal_impact_service import calculate_goal_impacts
from app.services.safe_to_spend_service import (
    _DAYS_PER_MONTH,
    _get_projected_income_cents,
    _prorate_monthly_to_horizon,
    calculate_safe_to_spend,
)

# Scenario types whose ongoing monthly effect feeds goal-funding
# capacity (baseline vs. adjusted monthly capacity, same convention
# `major_purchase_service`/`financial_stress_test_service` already
# use). `one_time_expense` is a one-off draw against liquid funds,
# already fully reflected in the safe-to-spend delta, and
# `monthly_savings_change` is itself a goal-directed commitment, so
# folding it into capacity too would double-count the same dollars.
_CAPACITY_AFFECTING_SCENARIOS = {
    "monthly_expense_change",
    "monthly_income_change",
    "temporary_income_loss",
}


def simulate_what_if(
    db: Session,
    user_id: int,
    payload: WhatIfSimulationRequest,
    *,
    as_of: date | None = None,
    precomputed_baseline: SafeToSpendOut | None = None,
) -> WhatIfSimulationOut:
    """`precomputed_baseline` lets a caller comparing several scenarios
    against the same user/horizon (e.g. `what_if_comparison_service`)
    compute the baseline once and reuse it here instead of re-running
    `calculate_safe_to_spend` per scenario. It is only safe to pass
    when `safety_reserve_cents`, `essential_spending_cents`, and
    `horizon_days` match the request that produced it -- callers own
    that guarantee.
    """
    calculation_date = as_of or date.today()

    baseline = precomputed_baseline or calculate_safe_to_spend(
        db,
        user_id,
        SafeToSpendRequest(
            safety_reserve_cents=payload.safety_reserve_cents,
            essential_spending_cents=payload.essential_spending_cents,
            horizon_days=payload.horizon_days,
            include_projected_income=True,
            include_goal_reserve=True,
        ),
        as_of=calculation_date,
    )

    if payload.scenario_type == "one_time_expense":
        _validate_effective_date(
            payload.effective_date,
            calculation_date,
            baseline.through_date,
        )

    cost_delta_cents, monthly_capacity_delta_cents = _resolve_deltas(
        payload
    )

    baseline_raw_cents = (
        baseline.safe_to_spend_cents - baseline.shortfall_cents
    )
    scenario_raw_cents = baseline_raw_cents - cost_delta_cents
    scenario_safe_cents = max(scenario_raw_cents, 0)
    scenario_shortfall_cents = max(-scenario_raw_cents, 0)

    baseline_outcome = WhatIfOutcomeOut(
        safe_to_spend_cents=baseline.safe_to_spend_cents,
        shortfall_cents=baseline.shortfall_cents,
        confidence_score=baseline.confidence_score,
        confidence_level=baseline.confidence_level,
    )
    scenario_outcome = WhatIfOutcomeOut(
        safe_to_spend_cents=scenario_safe_cents,
        shortfall_cents=scenario_shortfall_cents,
        # Only deterministic hypothetical inputs changed -- the
        # underlying obligation/balance data driving confidence did
        # not, so confidence is reported unchanged rather than
        # fabricating a delta.
        confidence_score=baseline.confidence_score,
        confidence_level=baseline.confidence_level,
    )

    impact_level = _classify_impact(
        baseline_safe_cents=baseline.safe_to_spend_cents,
        scenario_safe_cents=scenario_safe_cents,
        baseline_shortfall_cents=baseline.shortfall_cents,
        scenario_shortfall_cents=scenario_shortfall_cents,
    )

    goal_impacts: list[GoalImpactOut] = []

    if (
        payload.scenario_type in _CAPACITY_AFFECTING_SCENARIOS
        and monthly_capacity_delta_cents != 0
    ):
        goal_impacts = _compute_goal_impacts(
            db,
            user_id,
            calculation_date,
            baseline,
            monthly_capacity_delta_cents,
        )

    return WhatIfSimulationOut(
        scenario_type=payload.scenario_type,
        scenario_name=payload.scenario_name,
        as_of=baseline.as_of,
        through_date=baseline.through_date,
        horizon_days=payload.horizon_days,
        baseline=baseline_outcome,
        scenario=scenario_outcome,
        impact=WhatIfImpactOut(
            safe_to_spend_delta_cents=(
                scenario_safe_cents - baseline.safe_to_spend_cents
            ),
            shortfall_delta_cents=(
                scenario_shortfall_cents - baseline.shortfall_cents
            ),
            confidence_delta=0.0,
            level=impact_level,
        ),
        explanation=_build_explanation(
            payload=payload,
            cost_delta_cents=cost_delta_cents,
            baseline_safe_cents=baseline.safe_to_spend_cents,
            scenario_safe_cents=scenario_safe_cents,
            scenario_shortfall_cents=scenario_shortfall_cents,
            confidence_level=baseline.confidence_level,
        ),
        goal_impacts=goal_impacts,
        safe_to_spend=baseline,
    )


def _validate_effective_date(
    effective_date: date | None,
    calculation_date: date,
    through_date: date,
) -> None:
    assert effective_date is not None

    if effective_date < calculation_date:
        raise ValueError(
            "effective_date cannot be before the calculation date"
        )

    if effective_date > through_date:
        raise ValueError(
            "effective_date must fall within the selected horizon"
        )


def _resolve_deltas(
    payload: WhatIfSimulationRequest,
) -> tuple[int, int]:
    """Returns (cost_delta_cents, monthly_capacity_delta_cents).

    `cost_delta_cents` is horizon-prorated and drives the safe-to-
    spend comparison; `monthly_capacity_delta_cents` is an
    unprorated monthly figure used only for goal-funding capacity.
    """
    scenario_type = payload.scenario_type

    if scenario_type == "one_time_expense":
        assert payload.amount_cents is not None
        return payload.amount_cents, 0

    if scenario_type == "monthly_expense_change":
        assert payload.monthly_amount_change_cents is not None
        change = payload.monthly_amount_change_cents
        return (
            _prorate_monthly_to_horizon(change, payload.horizon_days),
            max(change, 0),
        )

    if scenario_type == "monthly_income_change":
        assert payload.monthly_amount_change_cents is not None
        change = payload.monthly_amount_change_cents
        return (
            -_prorate_monthly_to_horizon(change, payload.horizon_days),
            max(-change, 0),
        )

    if scenario_type == "monthly_savings_change":
        assert payload.monthly_amount_change_cents is not None
        change = payload.monthly_amount_change_cents
        return (
            _prorate_monthly_to_horizon(change, payload.horizon_days),
            0,
        )

    assert scenario_type == "temporary_income_loss"
    assert payload.monthly_income_loss_cents is not None
    assert payload.duration_months is not None

    months_in_horizon = payload.horizon_days / _DAYS_PER_MONTH
    effective_months = min(payload.duration_months, months_in_horizon)
    cost_delta_cents = round(
        payload.monthly_income_loss_cents * effective_months
    )

    return cost_delta_cents, payload.monthly_income_loss_cents


def _classify_impact(
    *,
    baseline_safe_cents: int,
    scenario_safe_cents: int,
    baseline_shortfall_cents: int,
    scenario_shortfall_cents: int,
) -> str:
    if scenario_shortfall_cents > baseline_shortfall_cents:
        return "negative"

    if scenario_shortfall_cents < baseline_shortfall_cents:
        return "positive"

    safe_delta = scenario_safe_cents - baseline_safe_cents

    if safe_delta > 0:
        return "positive"

    if safe_delta < 0:
        if scenario_safe_cents == 0 and baseline_safe_cents > 0:
            return "negative"

        return "caution"

    return "neutral"


def _compute_goal_impacts(
    db: Session,
    user_id: int,
    calculation_date: date,
    baseline: SafeToSpendOut,
    monthly_capacity_delta_cents: int,
) -> list[GoalImpactOut]:
    average_monthly_income_cents = _get_projected_income_cents(
        db,
        user_id,
        calculation_date,
        _DAYS_PER_MONTH,
    )
    baseline_monthly_capacity_cents = max(
        average_monthly_income_cents
        - baseline.breakdown.upcoming_obligations_cents,
        0,
    )
    adjusted_monthly_capacity_cents = max(
        baseline_monthly_capacity_cents - monthly_capacity_delta_cents,
        0,
    )

    return calculate_goal_impacts(
        db,
        user_id,
        baseline_monthly_capacity_cents=baseline_monthly_capacity_cents,
        adjusted_monthly_capacity_cents=adjusted_monthly_capacity_cents,
        as_of=calculation_date,
    )


def _currency(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    return f"{sign}${abs(cents) / 100:,.2f}"


def _build_explanation(
    *,
    payload: WhatIfSimulationRequest,
    cost_delta_cents: int,
    baseline_safe_cents: int,
    scenario_safe_cents: int,
    scenario_shortfall_cents: int,
    confidence_level: str,
) -> list[SafeToSpendExplanationOut]:
    explanation: list[SafeToSpendExplanationOut] = []

    explanation.append(
        SafeToSpendExplanationOut(
            code="SCENARIO_COST",
            amount_cents=cost_delta_cents,
            message=_scenario_cost_message(payload, cost_delta_cents),
        )
    )

    if payload.safety_reserve_cents > 0:
        explanation.append(
            SafeToSpendExplanationOut(
                code="SAFETY_RESERVE_PROTECTED",
                amount_cents=payload.safety_reserve_cents,
                message=(
                    f"Your safety reserve of "
                    f"{_currency(payload.safety_reserve_cents)} "
                    "remains protected."
                ),
            )
        )

    if scenario_shortfall_cents > 0:
        explanation.append(
            SafeToSpendExplanationOut(
                code="SHORTFALL",
                amount_cents=scenario_shortfall_cents,
                message=(
                    "This scenario creates a projected shortfall of "
                    f"{_currency(scenario_shortfall_cents)}."
                ),
            )
        )
    else:
        explanation.append(
            SafeToSpendExplanationOut(
                code="RESULT",
                amount_cents=scenario_safe_cents,
                message=(
                    "Safe-to-spend remains above zero after this "
                    f"change, at {_currency(scenario_safe_cents)}."
                    if scenario_safe_cents > 0
                    else "Safe-to-spend is $0 after this change."
                ),
            )
        )

    explanation.append(
        SafeToSpendExplanationOut(
            code="CONFIDENCE",
            amount_cents=None,
            message=(
                f"Confidence is {confidence_level} and unchanged by "
                "this hypothetical scenario."
            ),
        )
    )

    return explanation


def _scenario_cost_message(
    payload: WhatIfSimulationRequest,
    cost_delta_cents: int,
) -> str:
    direction = "reduces" if cost_delta_cents >= 0 else "increases"
    magnitude = _currency(abs(cost_delta_cents))

    if payload.scenario_type == "one_time_expense":
        return (
            f"A {_currency(cost_delta_cents)} one-time expense "
            f"{direction} safe-to-spend by {magnitude}."
        )

    if payload.scenario_type == "monthly_expense_change":
        assert payload.monthly_amount_change_cents is not None
        return (
            f"A {_currency(payload.monthly_amount_change_cents)}/month "
            f"expense change {direction} your "
            f"{payload.horizon_days}-day buffer by {magnitude}."
        )

    if payload.scenario_type == "monthly_income_change":
        assert payload.monthly_amount_change_cents is not None
        return (
            f"A {_currency(payload.monthly_amount_change_cents)}/month "
            f"income change {direction} your "
            f"{payload.horizon_days}-day buffer by {magnitude}."
        )

    if payload.scenario_type == "monthly_savings_change":
        assert payload.monthly_amount_change_cents is not None
        return (
            f"Setting aside {_currency(payload.monthly_amount_change_cents)}"
            f"/month more or less {direction} safe-to-spend by "
            f"{magnitude} over this period."
        )

    assert payload.monthly_income_loss_cents is not None
    assert payload.duration_months is not None
    return (
        f"{payload.duration_months} month(s) of "
        f"{_currency(payload.monthly_income_loss_cents)}/month income "
        f"loss {direction} expected income within this period by "
        f"{magnitude}."
    )
