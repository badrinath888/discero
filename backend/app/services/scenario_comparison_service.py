from datetime import date

from sqlalchemy.orm import Session

from app.schemas import (
    MajorPurchaseSimulationOut,
    ScenarioComparisonOptionOut,
    ScenarioComparisonOut,
    ScenarioComparisonRequest,
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

    return ScenarioComparisonOut(
        recommended_option=recommended_option,
        recommendation=_build_recommendation(
            recommended_option,
            simulation_a,
            simulation_b,
        ),
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
) -> tuple[int, int, int, float, int]:
    return (
        _AFFORDABILITY_RANK[
            simulation.affordability_status
        ],
        -simulation.shortfall_after_purchase_cents,
        simulation.safe_to_spend_after_purchase_cents,
        -simulation.purchase_impact_percent,
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
