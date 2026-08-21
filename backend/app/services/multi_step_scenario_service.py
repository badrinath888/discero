"""Multi-Step Scenario Planning 2.0.

Evaluates 2-5 dated financial events in chronological order against ONE
shared baseline, reusing `calculate_safe_to_spend`'s raw (pre-clamp)
total and the shared `time_aware_financial_simulation_service` engine's
`walk_step_timeline` for the chronological walk -- the exact same
ordering, proration, and worst/final-state logic Buy Now vs Wait's
known-cashflow advance is built from, so there is only ONE deterministic
temporal walker in the codebase, not a duplicate per feature.

The engine has no notion of a projected future account balance: calling
`calculate_safe_to_spend` with a future `as_of` still reads TODAY's
actual linked-account balance, not a balance decremented by intervening
scenario steps. So a plan is evaluated the same way `what_if_service`
evaluates a single scenario -- one real baseline, walked forward
in-memory step by step -- rather than by re-querying account state at
each step's date, which would silently drop every prior step's effect.

Each step's cost delta is computed against the days remaining from ITS
OWN effective date to the plan horizon's end (not the full horizon),
using the same `_prorate_monthly_to_horizon` day-based convention
`safe_to_spend_service` already uses for goal reserve and projected
income -- a monthly change that starts partway through the horizon
only accumulates for its own remaining window. The running raw total
is never clamped mid-sequence: only the per-checkpoint DISPLAY values
are floored at zero, so a temporary shortfall can still be seen to
recover in a later checkpoint instead of being silently pinned at $0.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.schemas import (
    MultiStepScenarioCheckpointOut,
    MultiStepScenarioCheckpointStatus,
    MultiStepScenarioPlanOut,
    MultiStepScenarioPlanRequest,
    MultiStepScenarioStepRequest,
    SafeToSpendRequest,
)
from app.services.decision_goal_conflict_intelligence_service import (
    build_goal_conflict_intelligence,
)
from app.services.goal_impact_service import calculate_goal_impacts
from app.services.safe_to_spend_service import (
    _DAYS_PER_MONTH,
    _determine_status,
    _get_projected_income_cents,
    calculate_safe_to_spend,
)
from app.services.time_aware_financial_simulation_service import (
    StepTimelineEffect,
    chronological_order,
    walk_step_timeline,
)
from app.services.what_if_service import _validate_effective_date

# A step landing this close to the horizon's end has too little
# remaining window for its prorated effect to be meaningfully
# reflected -- flagged rather than silently shown as near-zero impact.
_NEAR_HORIZON_END_DAYS = 7

_STATUS_MAP: dict[str, MultiStepScenarioCheckpointStatus] = {
    "safe": "comfortable",
    "limited": "tight",
    "negative": "shortfall",
}


class MultiStepScenarioValidationError(Exception):
    """Raised for a stable, structured 422: a step date outside the
    plan's own horizon, or any other cross-field rule Pydantic alone
    can't express.
    """

    def __init__(self, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.details = details or {}


def evaluate_multi_step_scenario_plan(
    db: Session,
    user_id: int,
    payload: MultiStepScenarioPlanRequest,
    *,
    as_of: date | None = None,
) -> MultiStepScenarioPlanOut:
    calculation_date = as_of or date.today()
    horizon_end = calculation_date + timedelta(days=payload.horizon_days)

    ordered_steps = chronological_order(payload.steps)
    _validate_step_dates(ordered_steps, calculation_date, horizon_end)

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

    baseline_raw_cents = (
        baseline.safe_to_spend_cents - baseline.shortfall_cents
    )

    timeline = walk_step_timeline(
        ordered_steps,
        baseline_raw_cents=baseline_raw_cents,
        horizon_end=horizon_end,
    )

    liquid_balance_cents = baseline.breakdown.liquid_balance_cents
    checkpoints = [
        MultiStepScenarioCheckpointOut(
            sequence=checkpoint.sequence,
            step_type=checkpoint.step.step_type,
            label=checkpoint.step.label,
            effective_date=checkpoint.step.effective_date,
            is_recurring=checkpoint.effect.is_recurring,
            is_temporary=checkpoint.effect.is_temporary,
            expires_on=checkpoint.effect.expires_on,
            safe_to_spend_before_cents=max(checkpoint.before_raw_cents, 0),
            safe_to_spend_after_cents=max(checkpoint.after_raw_cents, 0),
            impact_cents=checkpoint.effect.cost_delta_cents,
            cumulative_impact_cents=checkpoint.cumulative_impact_cents,
            status=_STATUS_MAP[
                _determine_status(
                    checkpoint.after_raw_cents, liquid_balance_cents
                )
            ],
        )
        for checkpoint in timeline.checkpoints
    ]

    final_safe_cents = max(timeline.final_raw_cents, 0)
    final_shortfall_cents = max(-timeline.final_raw_cents, 0)

    average_monthly_income_cents = _get_projected_income_cents(
        db, user_id, calculation_date, _DAYS_PER_MONTH
    )
    baseline_monthly_capacity_cents = max(
        average_monthly_income_cents
        - baseline.breakdown.upcoming_obligations_cents,
        0,
    )
    # A one-time shortfall left after liquid funds are exhausted
    # competes with monthly goal funding the same way
    # `decision_portfolio_service` folds its own combined shortfall in.
    adjusted_monthly_capacity_cents = max(
        baseline_monthly_capacity_cents
        - timeline.total_monthly_capacity_delta_cents
        - final_shortfall_cents,
        0,
    )

    goal_impacts = calculate_goal_impacts(
        db,
        user_id,
        baseline_monthly_capacity_cents=baseline_monthly_capacity_cents,
        adjusted_monthly_capacity_cents=adjusted_monthly_capacity_cents,
        as_of=calculation_date,
    )

    warnings = [
        *baseline.warnings,
        *_build_warnings(
            ordered_steps,
            [checkpoint.effect for checkpoint in timeline.checkpoints],
            horizon_end=horizon_end,
            compounding_labels=timeline.compounding_labels,
        ),
    ]

    return MultiStepScenarioPlanOut(
        name=payload.name,
        as_of=calculation_date,
        horizon_days=payload.horizon_days,
        through_date=horizon_end,
        starting_safe_to_spend_cents=baseline.safe_to_spend_cents,
        final_safe_to_spend_cents=final_safe_cents,
        final_shortfall_cents=final_shortfall_cents,
        total_impact_cents=final_safe_cents - baseline.safe_to_spend_cents,
        minimum_safe_to_spend_cents=timeline.minimum_safe_cents,
        worst_checkpoint_sequence=timeline.worst_sequence,
        worst_checkpoint_label=timeline.worst_label,
        worst_checkpoint_date=timeline.worst_date,
        overall_status=_STATUS_MAP[
            _determine_status(timeline.final_raw_cents, liquid_balance_cents)
        ],
        checkpoints=checkpoints,
        goal_impacts=goal_impacts,
        goal_conflict_intelligence=build_goal_conflict_intelligence(
            goal_impacts
        ),
        # Only deterministic hypothetical step inputs changed -- the
        # underlying obligation/balance data driving confidence did
        # not, so confidence is reported unchanged rather than
        # fabricating a delta (same convention `what_if_service`/
        # `decision_portfolio_service` use).
        confidence_score=baseline.confidence_score,
        confidence_level=baseline.confidence_level,
        warnings=warnings,
    )


def _validate_step_dates(
    ordered_steps: list[MultiStepScenarioStepRequest],
    calculation_date: date,
    horizon_end: date,
) -> None:
    for step in ordered_steps:
        try:
            _validate_effective_date(
                step.effective_date, calculation_date, horizon_end
            )
        except ValueError as exc:
            raise MultiStepScenarioValidationError(
                str(exc),
                details={
                    "reason": "step_date_outside_horizon",
                    "label": step.label,
                },
            ) from exc


def _build_warnings(
    ordered_steps: list[MultiStepScenarioStepRequest],
    effects: list[StepTimelineEffect],
    *,
    horizon_end: date,
    compounding_labels: list[str],
) -> list[str]:
    warnings: list[str] = []

    for step, effect in zip(ordered_steps, effects):
        remaining_days = (horizon_end - step.effective_date).days
        if remaining_days <= _NEAR_HORIZON_END_DAYS:
            warnings.append(
                f"'{step.label}' occurs within the final "
                f"{_NEAR_HORIZON_END_DAYS} days of the selected "
                "horizon, so its projected effect is only partially "
                "reflected."
            )

        if effect.is_temporary and effect.expires_on is not None:
            if effect.expires_on < horizon_end:
                warnings.append(
                    f"'{step.label}' ends on {effect.expires_on.isoformat()}, "
                    "before the selected horizon ends."
                )

    for temp_step, temp_effect in zip(ordered_steps, effects):
        if not temp_effect.is_temporary or temp_effect.expires_on is None:
            continue

        for other_step, other_effect in zip(ordered_steps, effects):
            if other_step is temp_step or not other_effect.is_recurring:
                continue

            if other_step.effective_date < temp_effect.expires_on:
                warnings.append(
                    f"'{temp_step.label}' overlaps the ongoing effect of "
                    f"'{other_step.label}', which starts "
                    f"{other_step.effective_date.isoformat()} and "
                    "continues through the horizon."
                )

    for label in compounding_labels:
        warnings.append(
            f"'{label}' adds further pressure while the plan is already "
            "in a shortfall from an earlier step."
        )

    return warnings
