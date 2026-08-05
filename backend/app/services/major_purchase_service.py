from datetime import date

from sqlalchemy.orm import Session

from app.schemas import (
    MajorPurchaseAlternativeOut,
    MajorPurchaseSimulationOut,
    MajorPurchaseSimulationRequest,
    SafeToSpendRequest,
)
from app.services.safe_to_spend_service import (
    calculate_safe_to_spend,
)


def simulate_major_purchase(
    db: Session,
    user_id: int,
    payload: MajorPurchaseSimulationRequest,
    *,
    as_of: date | None = None,
) -> MajorPurchaseSimulationOut:
    calculation_date = as_of or date.today()

    if payload.purchase_date < calculation_date:
        raise ValueError(
            "purchase date cannot be before the calculation date"
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

    if payload.purchase_date > safe_to_spend.through_date:
        raise ValueError(
            "purchase date must fall within the selected horizon"
        )

    safe_before = safe_to_spend.safe_to_spend_cents
    raw_safe_after = (
        safe_before - payload.purchase_amount_cents
    )
    safe_after = max(raw_safe_after, 0)
    shortfall_after = max(-raw_safe_after, 0)

    recommended_max = _recommended_max_purchase(
        safe_before
    )
    impact_percent = _purchase_impact_percent(
        payload.purchase_amount_cents,
        safe_before,
    )
    affordability_status = _affordability_status(
        payload.purchase_amount_cents,
        safe_before,
        recommended_max,
    )

    return MajorPurchaseSimulationOut(
        purchase_name=payload.purchase_name.strip(),
        purchase_amount_cents=payload.purchase_amount_cents,
        purchase_date=payload.purchase_date,
        as_of=safe_to_spend.as_of,
        through_date=safe_to_spend.through_date,
        affordability_status=affordability_status,
        safe_to_spend_before_purchase_cents=safe_before,
        safe_to_spend_after_purchase_cents=safe_after,
        shortfall_after_purchase_cents=shortfall_after,
        recommended_max_purchase_cents=recommended_max,
        purchase_impact_percent=impact_percent,
        confidence_score=safe_to_spend.confidence_score,
        explanation=_build_explanation(
            purchase_name=payload.purchase_name.strip(),
            purchase_amount_cents=(
                payload.purchase_amount_cents
            ),
            safe_before_cents=safe_before,
            safe_after_cents=safe_after,
            shortfall_cents=shortfall_after,
            recommended_max_cents=recommended_max,
            status=affordability_status,
        ),
        alternatives=_build_alternatives(
            requested_amount_cents=(
                payload.purchase_amount_cents
            ),
            safe_before_cents=safe_before,
            recommended_max_cents=recommended_max,
        ),
        safe_to_spend=safe_to_spend,
    )


def _recommended_max_purchase(
    safe_to_spend_cents: int,
) -> int:
    if safe_to_spend_cents <= 0:
        return 0

    return round(safe_to_spend_cents * 0.75)


def _purchase_impact_percent(
    purchase_amount_cents: int,
    safe_to_spend_cents: int,
) -> float:
    if safe_to_spend_cents <= 0:
        return 100.0

    return round(
        (purchase_amount_cents / safe_to_spend_cents) * 100,
        1,
    )


def _affordability_status(
    purchase_amount_cents: int,
    safe_to_spend_cents: int,
    recommended_max_cents: int,
) -> str:
    if (
        safe_to_spend_cents <= 0
        or purchase_amount_cents > safe_to_spend_cents
    ):
        return "not_affordable"

    if purchase_amount_cents > recommended_max_cents:
        return "caution"

    return "affordable"


def _build_explanation(
    *,
    purchase_name: str,
    purchase_amount_cents: int,
    safe_before_cents: int,
    safe_after_cents: int,
    shortfall_cents: int,
    recommended_max_cents: int,
    status: str,
) -> str:
    if status == "not_affordable":
        return (
            f"{purchase_name} exceeds the current safe-to-spend "
            f"amount by {shortfall_cents} cents. Reduce the purchase "
            "amount, increase available funds, or postpone the purchase."
        )

    if status == "caution":
        return (
            f"{purchase_name} is technically affordable, but it is "
            f"above the recommended ceiling of "
            f"{recommended_max_cents} cents and would leave "
            f"{safe_after_cents} cents available."
        )

    return (
        f"{purchase_name} is within the recommended purchase range. "
        f"It uses {purchase_amount_cents} cents from "
        f"{safe_before_cents} cents currently safe to spend and "
        f"leaves {safe_after_cents} cents available."
    )


def _build_alternatives(
    *,
    requested_amount_cents: int,
    safe_before_cents: int,
    recommended_max_cents: int,
) -> list[MajorPurchaseAlternativeOut]:
    if safe_before_cents <= 0:
        return []

    conservative_amount = round(
        safe_before_cents * 0.5
    )
    candidates = [
        (
            "Conservative option",
            conservative_amount,
            "Uses no more than half of the current safe-to-spend "
            "amount.",
        ),
        (
            "Recommended ceiling",
            recommended_max_cents,
            "Keeps 25% of the current safe-to-spend amount "
            "available after the purchase.",
        ),
    ]

    alternatives: list[MajorPurchaseAlternativeOut] = []
    seen_amounts: set[int] = set()

    for label, amount_cents, description in candidates:
        if (
            amount_cents <= 0
            or amount_cents >= requested_amount_cents
            or amount_cents in seen_amounts
        ):
            continue

        seen_amounts.add(amount_cents)
        alternatives.append(
            MajorPurchaseAlternativeOut(
                label=label,
                purchase_amount_cents=amount_cents,
                remaining_safe_to_spend_cents=max(
                    safe_before_cents - amount_cents,
                    0,
                ),
                description=description,
            )
        )

    return alternatives