from datetime import date

from sqlalchemy.orm import Session

from app.schemas import (
    MajorPurchaseSimulationOut,
    ScenarioComparisonOptionOut,
    ScenarioComparisonOut,
    ScenarioComparisonRequest,
    ScenarioComparisonScorecardOut,
    ScenarioComparisonScoreCriterionOut,
)
from app.services.major_purchase_service import simulate_major_purchase

_AFFORDABILITY_RANK = {
    "affordable": 3,
    "caution": 2,
    "not_affordable": 1,
}

_STATUS_LABELS = {
    "affordable": "affordable",
    "caution": "caution",
    "not_affordable": "not affordable",
}

# Each criterion's weight exceeds the sum of every lower-priority
# weight (64 > 32+16+8+4+2+1), so the scorecard's higher-scoring
# option always matches the lexicographic winner from
# `_comparison_key` below — the scorecard can never disagree with
# `recommended_option`. Order here is priority order, highest first.
_SCORECARD_WEIGHTS: dict[str, float] = {
    "affordability": 64.0,
    "shortfall": 32.0,
    "safe_to_spend_after": 16.0,
    "impact_percent": 8.0,
    "goal_impact": 4.0,
    "confidence": 2.0,
    "purchase_cost": 1.0,
}

_SCORECARD_LABELS: dict[str, str] = {
    "affordability": "Financial safety",
    "shortfall": "Shortfall risk",
    "safe_to_spend_after": "Remaining safe-to-spend",
    "impact_percent": "Safe-to-spend impact",
    "goal_impact": "Goal impact",
    "confidence": "Confidence",
    "purchase_cost": "Purchase cost",
}

_SCORECARD_MAX_SCORE = sum(_SCORECARD_WEIGHTS.values())


def compare_major_purchase_scenarios(
    db: Session,
    user_id: int,
    payload: ScenarioComparisonRequest,
    *,
    as_of: date | None = None,
) -> ScenarioComparisonOut:
    calculation_date = as_of or date.today()

    simulation_a = simulate_major_purchase(
        db,
        user_id,
        payload.option_a,
        as_of=calculation_date,
    )
    simulation_b = simulate_major_purchase(
        db,
        user_id,
        payload.option_b,
        as_of=calculation_date,
    )

    recommended_option = _determine_recommendation(
        simulation_a,
        simulation_b,
    )

    scorecard = _build_scorecard(simulation_a, simulation_b)

    return ScenarioComparisonOut(
        recommended_option=recommended_option,
        recommendation=_build_recommendation(
            recommended_option,
            simulation_a,
            simulation_b,
        ),
        reasons=_build_reasons(
            recommended_option,
            scorecard,
            simulation_a,
            simulation_b,
        ),
        scorecard=scorecard,
        safe_to_spend_difference_cents=(
            simulation_a.safe_to_spend_after_purchase_cents
            - simulation_b.safe_to_spend_after_purchase_cents
        ),
        purchase_cost_difference_cents=(
            simulation_a.purchase_amount_cents
            - simulation_b.purchase_amount_cents
        ),
        impact_difference_percent=round(
            simulation_a.purchase_impact_percent
            - simulation_b.purchase_impact_percent,
            1,
        ),
        option_a=_build_option_out(
            "option_a",
            simulation_a,
        ),
        option_b=_build_option_out(
            "option_b",
            simulation_b,
        ),
    )


def _build_option_out(
    option_key: str,
    simulation: MajorPurchaseSimulationOut,
) -> ScenarioComparisonOptionOut:
    return ScenarioComparisonOptionOut(
        option_key=option_key,
        simulation=simulation,
        affordability_rank=_AFFORDABILITY_RANK[
            simulation.affordability_status
        ],
    )


def _comparison_key(
    simulation: MajorPurchaseSimulationOut,
) -> tuple[int, int, int, float, float, float, int]:
    return (
        _AFFORDABILITY_RANK[
            simulation.affordability_status
        ],
        -simulation.shortfall_after_purchase_cents,
        simulation.safe_to_spend_after_purchase_cents,
        -simulation.purchase_impact_percent,
        -simulation.goal_impact_months,
        simulation.confidence_score,
        -simulation.purchase_amount_cents,
    )


def _determine_recommendation(
    simulation_a: MajorPurchaseSimulationOut,
    simulation_b: MajorPurchaseSimulationOut,
) -> str:
    key_a = _comparison_key(simulation_a)
    key_b = _comparison_key(simulation_b)

    if key_a > key_b:
        return "option_a"

    if key_b > key_a:
        return "option_b"

    return "tie"


def _format_currency(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def _build_recommendation(
    recommended_option: str,
    simulation_a: MajorPurchaseSimulationOut,
    simulation_b: MajorPurchaseSimulationOut,
) -> str:
    if recommended_option == "tie":
        return (
            f"{simulation_a.purchase_name} and "
            f"{simulation_b.purchase_name} are equally viable. "
            "Both options have the same affordability, remaining "
            "safe-to-spend, shortfall, impact, and purchase cost."
        )

    winner, loser = (
        (simulation_a, simulation_b)
        if recommended_option == "option_a"
        else (simulation_b, simulation_a)
    )
    winner_label = (
        "Option A"
        if recommended_option == "option_a"
        else "Option B"
    )

    reasons: list[str] = []

    winner_rank = _AFFORDABILITY_RANK[
        winner.affordability_status
    ]
    loser_rank = _AFFORDABILITY_RANK[
        loser.affordability_status
    ]

    if winner_rank != loser_rank:
        reasons.append(
            f"it is {_STATUS_LABELS[winner.affordability_status]} "
            f"while {loser.purchase_name} is "
            f"{_STATUS_LABELS[loser.affordability_status]}"
        )

    if (
        winner.shortfall_after_purchase_cents
        < loser.shortfall_after_purchase_cents
    ):
        reasons.append(
            "it has a lower shortfall of "
            f"{_format_currency(winner.shortfall_after_purchase_cents)} "
            f"versus "
            f"{_format_currency(loser.shortfall_after_purchase_cents)}"
        )

    if (
        winner.safe_to_spend_after_purchase_cents
        > loser.safe_to_spend_after_purchase_cents
    ):
        reasons.append(
            "it leaves more safe-to-spend after purchase "
            f"({_format_currency(winner.safe_to_spend_after_purchase_cents)} "
            f"vs {_format_currency(loser.safe_to_spend_after_purchase_cents)})"
        )

    if (
        winner.purchase_impact_percent
        < loser.purchase_impact_percent
    ):
        reasons.append(
            f"it has a lower impact on safe-to-spend "
            f"({winner.purchase_impact_percent}% vs "
            f"{loser.purchase_impact_percent}%)"
        )

    if winner.purchase_amount_cents < loser.purchase_amount_cents:
        reasons.append(
            f"it costs less ({_format_currency(winner.purchase_amount_cents)} "
            f"vs {_format_currency(loser.purchase_amount_cents)})"
        )

    reason_text = (
        reasons[0]
        if len(reasons) == 1
        else "; ".join(reasons[:2])
    )

    return (
        f"{winner_label} ({winner.purchase_name}) is recommended because "
        f"{reason_text}."
    )


def _criterion_winner(
    value_a: float,
    value_b: float,
    *,
    lower_is_better: bool,
) -> str:
    if value_a == value_b:
        return "tie"

    a_wins = (
        value_a < value_b if lower_is_better else value_a > value_b
    )

    return "option_a" if a_wins else "option_b"


def _build_scorecard(
    simulation_a: MajorPurchaseSimulationOut,
    simulation_b: MajorPurchaseSimulationOut,
) -> ScenarioComparisonScorecardOut:
    winners = {
        "affordability": _criterion_winner(
            _AFFORDABILITY_RANK[simulation_a.affordability_status],
            _AFFORDABILITY_RANK[simulation_b.affordability_status],
            lower_is_better=False,
        ),
        "shortfall": _criterion_winner(
            simulation_a.shortfall_after_purchase_cents,
            simulation_b.shortfall_after_purchase_cents,
            lower_is_better=True,
        ),
        "safe_to_spend_after": _criterion_winner(
            simulation_a.safe_to_spend_after_purchase_cents,
            simulation_b.safe_to_spend_after_purchase_cents,
            lower_is_better=False,
        ),
        "impact_percent": _criterion_winner(
            simulation_a.purchase_impact_percent,
            simulation_b.purchase_impact_percent,
            lower_is_better=True,
        ),
        "goal_impact": _criterion_winner(
            simulation_a.goal_impact_months,
            simulation_b.goal_impact_months,
            lower_is_better=True,
        ),
        "confidence": _criterion_winner(
            simulation_a.confidence_score,
            simulation_b.confidence_score,
            lower_is_better=False,
        ),
        "purchase_cost": _criterion_winner(
            simulation_a.purchase_amount_cents,
            simulation_b.purchase_amount_cents,
            lower_is_better=True,
        ),
    }

    option_a_score = 0.0
    option_b_score = 0.0
    criteria: list[ScenarioComparisonScoreCriterionOut] = []

    for key, winner in winners.items():
        weight = _SCORECARD_WEIGHTS[key]

        if winner == "option_a":
            option_a_score += weight
        elif winner == "option_b":
            option_b_score += weight
        else:
            option_a_score += weight / 2
            option_b_score += weight / 2

        criteria.append(
            ScenarioComparisonScoreCriterionOut(
                key=key,
                label=_SCORECARD_LABELS[key],
                weight=weight,
                winner=winner,
            )
        )

    return ScenarioComparisonScorecardOut(
        option_a_score=round(option_a_score, 1),
        option_b_score=round(option_b_score, 1),
        max_score=_SCORECARD_MAX_SCORE,
        criteria=criteria,
    )


def _criterion_reason_sentence(
    key: str,
    winner: MajorPurchaseSimulationOut,
    loser: MajorPurchaseSimulationOut,
) -> str:
    if key == "affordability":
        return (
            f"It is {_STATUS_LABELS[winner.affordability_status]} "
            f"while {loser.purchase_name} is "
            f"{_STATUS_LABELS[loser.affordability_status]}."
        )

    if key == "shortfall":
        return (
            "It has a lower shortfall of "
            f"{_format_currency(winner.shortfall_after_purchase_cents)} "
            f"versus "
            f"{_format_currency(loser.shortfall_after_purchase_cents)}."
        )

    if key == "safe_to_spend_after":
        return (
            "It leaves more safe-to-spend after purchase "
            f"({_format_currency(winner.safe_to_spend_after_purchase_cents)} "
            f"vs {_format_currency(loser.safe_to_spend_after_purchase_cents)})."
        )

    if key == "impact_percent":
        return (
            "It has a lower impact on safe-to-spend "
            f"({winner.purchase_impact_percent}% vs "
            f"{loser.purchase_impact_percent}%)."
        )

    if key == "goal_impact":
        return (
            "It uses less of your monthly savings-goal capacity "
            f"({winner.goal_impact_months} months vs "
            f"{loser.goal_impact_months} months of required goal "
            "savings)."
        )

    if key == "confidence":
        return (
            "It has higher confidence in the underlying data "
            f"({round(winner.confidence_score)}% vs "
            f"{round(loser.confidence_score)}%)."
        )

    return (
        f"It costs less ({_format_currency(winner.purchase_amount_cents)} "
        f"vs {_format_currency(loser.purchase_amount_cents)})."
    )


def _build_reasons(
    recommended_option: str,
    scorecard: ScenarioComparisonScorecardOut,
    simulation_a: MajorPurchaseSimulationOut,
    simulation_b: MajorPurchaseSimulationOut,
) -> list[str]:
    if recommended_option == "tie":
        tied_labels = [
            criterion.label.lower()
            for criterion in scorecard.criteria
            if criterion.winner == "tie"
        ]

        return [
            "Both options are equally viable: they are evenly "
            f"matched on {', '.join(tied_labels)}."
        ]

    winner, loser = (
        (simulation_a, simulation_b)
        if recommended_option == "option_a"
        else (simulation_b, simulation_a)
    )

    reasons: list[str] = []

    for criterion in scorecard.criteria:
        if criterion.winner != recommended_option:
            continue

        reasons.append(
            _criterion_reason_sentence(criterion.key, winner, loser)
        )

        if len(reasons) == 4:
            break

    if len(reasons) == 1:
        reasons.append(
            "The remaining comparison factors are tied or favor "
            "the other option, so this is a close call decided "
            "by that single factor."
        )

    return reasons
