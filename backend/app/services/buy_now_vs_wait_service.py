"""Buy Now vs Wait 2.0: deterministic purchase-timing comparison.

Both the NOW and WAIT scenarios are evaluated with the exact same
`simulate_major_purchase` service used by the single-purchase flow --
no separate formulas are invented here.

NOW is evaluated exactly as before: `as_of=calculation_date`, so
`calculate_safe_to_spend`'s own obligations/income window already
covers today through the full horizon -- nothing about that path
changes.

WAIT is where Time-Aware Engine 2.0 actually matters. WAIT 1.0 shifted
`as_of` straight to the wait date, which re-ran safe-to-spend AT that
future date using TODAY's actual balance -- silently skipping every
known obligation or income event that lands BETWEEN now and the wait
date. A bill due next week was invisible to a "wait a month" estimate.
WAIT 2.0 closes that gap: it first calls
`time_aware_financial_simulation_service.advance_known_state_to_date`
to net known recurring obligations/income between `calculation_date`
and `wait_until_date` against today's actual balance, then evaluates
`simulate_major_purchase` AT the wait date starting from that advanced
balance (via `starting_liquid_balance_override_cents`) instead of the
unmodified current balance.

Known, permanent limitation, surfaced via `assumption` on EVERY result
rather than hidden or only shown conditionally: the advance uses only
KNOWN recurring obligations and a trailing-average income projection --
it never predicts discretionary spending or any other event that isn't
already a known recurring item. `caveat` is reserved for a stronger,
conditional warning when forecast confidence materially drops at the
wait horizon.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.schemas import (
    BuyNowVsWaitOptionOut,
    BuyNowVsWaitOut,
    BuyNowVsWaitRequest,
    MajorPurchaseSimulationOut,
    MajorPurchaseSimulationRequest,
)
from app.services.major_purchase_service import simulate_major_purchase
from app.services.time_aware_financial_simulation_service import (
    advance_known_state_to_date,
)

# Below this, a difference in preserved buffer is not worth recommending
# on -- it's noise relative to the kinds of purchase amounts this
# feature is meant for.
_MATERIALITY_THRESHOLD_CENTS = 5_000

# A confidence-score drop (0-100 scale) at least this large is called
# out explicitly rather than silently baked into the recommendation.
_CONFIDENCE_DROP_THRESHOLD = 10.0

# Beyond this many days out, the WAIT scenario's "project today's
# snapshot forward" limitation is worth calling out more strongly,
# even when the confidence score itself didn't move.
_LONG_HORIZON_CAVEAT_DAYS = 45

# Always shown, for every result -- the WAIT estimate advances today's
# known balances and obligations to the wait date, never a claim about
# unknown future income or spending.
_BASE_ASSUMPTION = (
    "The wait estimate advances your current balance using known "
    "recurring obligations and projected income between today and the "
    "wait date, then evaluates known obligations from that date "
    "forward; it does not predict the income or spending that isn't "
    "already a known recurring item."
)
_LONG_HORIZON_ASSUMPTION_SUFFIX = (
    " Because this date is further out, the estimate is directional "
    "rather than a precise forecast."
)


def _currency(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    return f"{sign}${abs(cents) / 100:,.2f}"


def _total_delay_months(simulation: MajorPurchaseSimulationOut) -> int:
    return sum(impact.delay_months for impact in simulation.goal_impacts)


def _goal_impact_note(
    now_simulation: MajorPurchaseSimulationOut,
    wait_simulation: MajorPurchaseSimulationOut,
) -> str | None:
    if not now_simulation.goal_impacts and not wait_simulation.goal_impacts:
        return None

    now_delay = _total_delay_months(now_simulation)
    wait_delay = _total_delay_months(wait_simulation)

    if now_delay == wait_delay:
        if now_delay == 0:
            return "Your goal timeline is unaffected either way."
        return "Both timings delay your goals by about the same amount."

    if wait_delay > now_delay:
        months = wait_delay - now_delay
        return (
            f"Waiting delays your goals by {months} more "
            f"month{'s' if months != 1 else ''} than buying now."
        )

    months = now_delay - wait_delay
    return (
        f"Buying now delays your goals by {months} more "
        f"month{'s' if months != 1 else ''} than waiting."
    )


def _build_reason(
    *,
    recommended_timing: str,
    key_driver: str,
    wait_until_date: date,
    buffer_difference_cents: int,
    goal_impact_note: str | None,
) -> str:
    if recommended_timing == "neither":
        return (
            "This purchase isn't affordable now or by "
            f"{wait_until_date.isoformat()} without cutting into your "
            "safety reserve or essential spending."
        )

    if key_driver == "affordability":
        if recommended_timing == "wait":
            return (
                "Not affordable right now, but it is affordable by "
                f"{wait_until_date.isoformat()}."
            )
        return (
            "Affordable now, but it would not be affordable by "
            f"{wait_until_date.isoformat()} at current projections."
        )

    if key_driver == "buffer":
        if recommended_timing == "wait":
            note = (
                " while keeping your goal timeline unchanged."
                if goal_impact_note
                and "unaffected" in goal_impact_note
                else ""
            )
            return (
                f"Waiting until {wait_until_date.isoformat()} gives you "
                f"{_currency(buffer_difference_cents)} more room"
                f"{note}"
            )
        return (
            f"Buying now preserves {_currency(-buffer_difference_cents)} "
            "more of your available buffer than waiting."
        )

    if key_driver == "goal_impact":
        return goal_impact_note or (
            "Goal timeline impact differs between the two timings."
        )

    if key_driver == "confidence":
        return (
            "Buying now avoids relying on a less certain forecast at "
            f"the {wait_until_date.isoformat()} horizon."
        )

    return "Either timing works; the difference is not financially meaningful."


def evaluate_buy_now_vs_wait(
    db: Session,
    user_id: int,
    request: BuyNowVsWaitRequest,
    *,
    as_of: date | None = None,
) -> BuyNowVsWaitOut:
    calculation_date = as_of or date.today()

    if request.buy_now_date < calculation_date:
        raise ValueError("buy_now_date cannot be before the calculation date")

    now_result = simulate_major_purchase(
        db,
        user_id,
        MajorPurchaseSimulationRequest(
            purchase_name=request.purchase_name,
            purchase_amount_cents=request.purchase_amount_cents,
            purchase_date=request.buy_now_date,
            safety_reserve_cents=request.safety_reserve_cents,
            essential_spending_cents=request.essential_spending_cents,
            horizon_days=request.horizon_days,
        ),
        as_of=calculation_date,
    )

    # The step WAIT 1.0 skipped: advance TODAY's actual liquid balance
    # to the wait date using only known recurring obligations/income,
    # so a bill due before the wait date is never invisible to it.
    advanced_liquid_balance_cents, advance_notices = (
        advance_known_state_to_date(
            db,
            user_id,
            current_liquid_balance_cents=(
                now_result.safe_to_spend.breakdown.liquid_balance_cents
            ),
            start_date=calculation_date,
            target_date=request.wait_until_date,
        )
    )

    wait_result = simulate_major_purchase(
        db,
        user_id,
        MajorPurchaseSimulationRequest(
            purchase_name=request.purchase_name,
            purchase_amount_cents=request.purchase_amount_cents,
            purchase_date=request.wait_until_date,
            safety_reserve_cents=request.safety_reserve_cents,
            essential_spending_cents=request.essential_spending_cents,
            horizon_days=request.horizon_days,
        ),
        as_of=request.wait_until_date,
        starting_liquid_balance_override_cents=advanced_liquid_balance_cents,
    )

    now_affordable = now_result.affordability_status != "not_affordable"
    wait_affordable = wait_result.affordability_status != "not_affordable"

    buffer_difference_cents = (
        wait_result.safe_to_spend_after_purchase_cents
        - now_result.safe_to_spend_after_purchase_cents
    )
    confidence_difference = round(
        wait_result.confidence_score - now_result.confidence_score, 1
    )
    goal_impact_note = _goal_impact_note(now_result, wait_result)
    delay_difference = _total_delay_months(wait_result) - _total_delay_months(
        now_result
    )

    buffer_material = abs(buffer_difference_cents) >= _MATERIALITY_THRESHOLD_CENTS
    delay_material = delay_difference != 0

    if not now_affordable and not wait_affordable:
        recommended_timing, key_driver = "neither", "affordability"
    elif not now_affordable:
        recommended_timing, key_driver = "wait", "affordability"
    elif not wait_affordable:
        recommended_timing, key_driver = "buy_now", "affordability"
    elif buffer_material:
        recommended_timing = "wait" if buffer_difference_cents > 0 else "buy_now"
        key_driver = "buffer"
    elif delay_material:
        recommended_timing = "buy_now" if delay_difference > 0 else "wait"
        key_driver = "goal_impact"
    elif confidence_difference <= -_CONFIDENCE_DROP_THRESHOLD:
        recommended_timing, key_driver = "buy_now", "confidence"
    else:
        recommended_timing, key_driver = "either", "equivalent"

    reason = _build_reason(
        recommended_timing=recommended_timing,
        key_driver=key_driver,
        wait_until_date=request.wait_until_date,
        buffer_difference_cents=buffer_difference_cents,
        goal_impact_note=goal_impact_note,
    )

    # Always disclosed, regardless of horizon or confidence -- the WAIT
    # figures are never a real future forecast, and that must not be
    # easy to miss just because this particular result looks clean.
    wait_horizon_days = (request.wait_until_date - calculation_date).days
    assumption = _BASE_ASSUMPTION
    if advance_notices:
        assumption += " " + advance_notices[0]
    if wait_horizon_days > _LONG_HORIZON_CAVEAT_DAYS:
        assumption += _LONG_HORIZON_ASSUMPTION_SUFFIX

    caveat = None
    if confidence_difference <= -_CONFIDENCE_DROP_THRESHOLD:
        caveat = (
            "Confidence is lower for the "
            f"{request.wait_until_date.isoformat()} estimate "
            f"({wait_result.confidence_score:.0f} vs "
            f"{now_result.confidence_score:.0f}) -- treat it as "
            "directional, not exact."
        )

    return BuyNowVsWaitOut(
        purchase_name=request.purchase_name.strip(),
        purchase_amount_cents=request.purchase_amount_cents,
        buy_now_date=request.buy_now_date,
        wait_until_date=request.wait_until_date,
        now=BuyNowVsWaitOptionOut(
            label="now",
            evaluated_date=request.buy_now_date,
            simulation=now_result,
        ),
        wait=BuyNowVsWaitOptionOut(
            label="wait",
            evaluated_date=request.wait_until_date,
            simulation=wait_result,
        ),
        recommended_timing=recommended_timing,
        reason=reason,
        key_driver=key_driver,
        buffer_difference_cents=buffer_difference_cents,
        goal_impact_note=goal_impact_note,
        confidence_difference=confidence_difference,
        assumption=assumption,
        caveat=caveat,
    )
