from datetime import date

from sqlalchemy.orm import Session

from app.schemas import (
    FinancialStressTestOut,
    FinancialStressTestRequest,
    SafeToSpendRequest,
)
from app.services.safe_to_spend_service import (
    calculate_safe_to_spend,
)

_DURATION_REQUIRED_SCENARIOS = {
    "temporary_income_loss",
    "delayed_paycheck",
}

_SCENARIO_LABELS = {
    "emergency_expense": "emergency expense",
    "temporary_income_loss": "temporary income loss",
    "delayed_paycheck": "delayed paycheck",
    "recurring_bill_increase": "recurring bill increase",
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
}

_STRAINED_THRESHOLD_RATIO = 0.5
_CONFIDENCE_PENALTY_PER_DAY = 0.3
_MAX_CONFIDENCE_PENALTY = 30.0


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

    safe_before = safe_to_spend.safe_to_spend_cents
    total_impact = payload.stress_amount_cents
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

    scenario_name = payload.scenario_name

    return FinancialStressTestOut(
        scenario_type=payload.scenario_type,
        scenario_name=scenario_name,
        event_date=payload.event_date,
        duration_days=payload.duration_days,
        as_of=safe_to_spend.as_of,
        through_date=safe_to_spend.through_date,
        risk_level=risk_level,
        safe_to_spend_before_stress_cents=safe_before,
        safe_to_spend_after_stress_cents=safe_after,
        total_financial_impact_cents=total_impact,
        shortfall_cents=shortfall,
        confidence_score=confidence_score,
        estimated_recovery_days=recovery_days,
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
