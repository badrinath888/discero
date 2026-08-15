"""Scenario Comparison for the What-If Simulator.

A thin orchestration layer: every scenario is run through the exact
same `simulate_what_if` engine used by the single-scenario What-If
flow, against ONE shared baseline (computed once via
`calculate_safe_to_spend` and reused across scenarios -- see
`simulate_what_if`'s `precomputed_baseline` parameter). No new
finance math is introduced here; this module only ranks and explains
results `simulate_what_if` already produced.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.schemas import (
    SafeToSpendRequest,
    WhatIfComparisonOut,
    WhatIfComparisonRequest,
    WhatIfComparisonScenarioOut,
    WhatIfComparisonScenarioRequest,
    WhatIfOutcomeOut,
    WhatIfSimulationRequest,
)
from app.services.safe_to_spend_service import calculate_safe_to_spend
from app.services.what_if_service import simulate_what_if


def _currency(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    return f"{sign}${abs(cents) / 100:,.2f}"


def _total_delay_months(scenario: WhatIfComparisonScenarioOut) -> int:
    return sum(
        impact.delay_months for impact in scenario.goal_impacts
    )


def _ranking_key(
    scenario: WhatIfComparisonScenarioOut,
) -> tuple[int, int, int, int]:
    """Lower is better. Priority order matches Discero's established
    convention (see `scenario_comparison_service._comparison_key` and
    `buy_now_vs_wait_service`): no shortfall beats shortfall, smaller
    shortfall beats larger, higher safe-to-spend beats lower, smaller
    aggregate goal delay beats larger. Confidence is deliberately
    excluded -- it is reported as context, not used to rank.
    """
    return (
        0 if scenario.shortfall_cents == 0 else 1,
        scenario.shortfall_cents,
        -scenario.safe_to_spend_cents,
        _total_delay_months(scenario),
    )


def _build_scenario_out(
    request: WhatIfComparisonScenarioRequest,
    horizon_days: int,
    safety_reserve_cents: int,
    essential_spending_cents: int,
    *,
    db: Session,
    user_id: int,
    calculation_date: date,
    baseline,
) -> WhatIfComparisonScenarioOut:
    simulation = simulate_what_if(
        db,
        user_id,
        WhatIfSimulationRequest(
            scenario_type=request.scenario_type,
            scenario_name=request.label,
            amount_cents=request.amount_cents,
            effective_date=request.effective_date,
            monthly_amount_change_cents=(
                request.monthly_amount_change_cents
            ),
            monthly_income_loss_cents=(
                request.monthly_income_loss_cents
            ),
            duration_months=request.duration_months,
            safety_reserve_cents=safety_reserve_cents,
            essential_spending_cents=essential_spending_cents,
            horizon_days=horizon_days,
        ),
        as_of=calculation_date,
        precomputed_baseline=baseline,
    )

    return WhatIfComparisonScenarioOut(
        label=request.label.strip(),
        scenario_type=request.scenario_type,
        safe_to_spend_cents=simulation.scenario.safe_to_spend_cents,
        shortfall_cents=simulation.scenario.shortfall_cents,
        safe_to_spend_delta_cents=(
            simulation.impact.safe_to_spend_delta_cents
        ),
        shortfall_delta_cents=simulation.impact.shortfall_delta_cents,
        confidence_score=simulation.scenario.confidence_score,
        confidence_level=simulation.scenario.confidence_level,
        impact_level=simulation.impact.level,
        goal_impacts=simulation.goal_impacts,
        explanation=simulation.explanation,
    )


def _build_recommendation(
    scenarios: list[WhatIfComparisonScenarioOut],
) -> tuple[str | None, str, str, str | None, list[str], bool]:
    """Returns (recommended_label, recommendation_reason, key_driver,
    key_tradeoff, ranking, is_tie).
    """
    ranked = sorted(scenarios, key=_ranking_key)
    best_key = _ranking_key(ranked[0])
    tied_for_best = [
        scenario
        for scenario in ranked
        if _ranking_key(scenario) == best_key
    ]

    ranking = [scenario.label for scenario in ranked]

    if len(tied_for_best) > 1:
        if len(tied_for_best) == len(ranked):
            return (
                None,
                "These scenarios have the same projected financial "
                "outcome within the selected horizon.",
                "tie",
                None,
                ranking,
                True,
            )

        tied_labels = ", ".join(
            scenario.label for scenario in tied_for_best
        )
        return (
            None,
            f"{tied_labels} are equally strong; the remaining "
            "scenario(s) are financially weaker.",
            "tie",
            None,
            ranking,
            True,
        )

    winner = ranked[0]
    runner_up = ranked[1]

    if winner.shortfall_cents == 0 and runner_up.shortfall_cents > 0:
        key_driver = "shortfall"
        reason = (
            f"{winner.label} is recommended because it avoids a "
            "projected shortfall, while "
            f"{runner_up.label} creates a shortfall of "
            f"{_currency(runner_up.shortfall_cents)}."
        )
    elif winner.shortfall_cents != runner_up.shortfall_cents:
        key_driver = "shortfall"
        reason = (
            f"{winner.label} is recommended because it has a smaller "
            f"shortfall of {_currency(winner.shortfall_cents)} versus "
            f"{_currency(runner_up.shortfall_cents)} for "
            f"{runner_up.label}."
        )
    elif winner.safe_to_spend_cents != runner_up.safe_to_spend_cents:
        key_driver = "safe_to_spend"
        diff = winner.safe_to_spend_cents - runner_up.safe_to_spend_cents
        reason = (
            f"{winner.label} is recommended because it preserves "
            f"{_currency(diff)} more safe-to-spend than "
            f"{runner_up.label}."
        )
    else:
        key_driver = "goal_impact"
        months_saved = _total_delay_months(runner_up) - _total_delay_months(
            winner
        )
        reason = (
            f"{winner.label} is recommended because it delays your "
            f"active goals by {months_saved} fewer month(s) than "
            f"{runner_up.label}."
        )

    key_tradeoff = None

    if (
        key_driver != "safe_to_spend"
        and winner.safe_to_spend_cents != runner_up.safe_to_spend_cents
    ):
        buffer_diff = (
            winner.safe_to_spend_cents - runner_up.safe_to_spend_cents
        )
        if buffer_diff < 0:
            key_tradeoff = (
                f"{runner_up.label} preserves "
                f"{_currency(-buffer_diff)} more safe-to-spend, but "
                f"{winner.label} avoids or reduces the shortfall."
            )
        else:
            key_tradeoff = (
                f"{winner.label} preserves {_currency(buffer_diff)} "
                f"more safe-to-spend than {runner_up.label}."
            )
    elif (
        key_driver != "goal_impact"
        and _total_delay_months(winner) != _total_delay_months(runner_up)
    ):
        key_tradeoff = (
            f"{runner_up.label} delays your active goals by "
            f"{_total_delay_months(runner_up) - _total_delay_months(winner)} "
            f"more month(s) than {winner.label}."
        )

    return (
        winner.label,
        reason,
        key_driver,
        key_tradeoff,
        ranking,
        False,
    )


def compare_what_if_scenarios(
    db: Session,
    user_id: int,
    payload: WhatIfComparisonRequest,
    *,
    as_of: date | None = None,
) -> WhatIfComparisonOut:
    calculation_date = as_of or date.today()

    baseline = calculate_safe_to_spend(
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

    scenarios = [
        _build_scenario_out(
            scenario_request,
            payload.horizon_days,
            payload.safety_reserve_cents,
            payload.essential_spending_cents,
            db=db,
            user_id=user_id,
            calculation_date=calculation_date,
            baseline=baseline,
        )
        for scenario_request in payload.scenarios
    ]

    (
        recommended_label,
        recommendation_reason,
        key_driver,
        key_tradeoff,
        ranking,
        is_tie,
    ) = _build_recommendation(scenarios)

    return WhatIfComparisonOut(
        as_of=baseline.as_of,
        through_date=baseline.through_date,
        horizon_days=payload.horizon_days,
        baseline=WhatIfOutcomeOut(
            safe_to_spend_cents=baseline.safe_to_spend_cents,
            shortfall_cents=baseline.shortfall_cents,
            confidence_score=baseline.confidence_score,
            confidence_level=baseline.confidence_level,
        ),
        scenarios=scenarios,
        recommended_label=recommended_label,
        recommendation_reason=recommendation_reason,
        key_driver=key_driver,
        key_tradeoff=key_tradeoff,
        ranking=ranking,
        is_tie=is_tie,
    )
