"""Multi-Step Scenario Planning 1.0.

Evaluates 2-5 dated financial events in chronological order against ONE
shared baseline, reusing `calculate_safe_to_spend`'s raw (pre-clamp)
total and the same linear cost-delta representation
`what_if_service`/`decision_portfolio_service` already use for every
step type -- never a second time-series/forecast engine.

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

from dataclasses import dataclass
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
    _prorate_monthly_to_horizon,
    calculate_safe_to_spend,
)
from app.services.what_if_service import _validate_effective_date

# A step landing this close to the horizon's end has too little
# remaining window for its prorated effect to be meaningfully
# reflected -- flagged rather than silently shown as near-zero impact.
_NEAR_HORIZON_END_DAYS = 7

_RECURRING_INCREASE_TYPES: frozenset[str] = frozenset(
    {"monthly_expense_increase", "monthly_income_decrease"}
)
_RECURRING_DECREASE_TYPES: frozenset[str] = frozenset(
    {"monthly_expense_decrease", "monthly_income_increase"}
)

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


@dataclass(frozen=True)
class _StepEffect:
    cost_delta_cents: int
    monthly_capacity_delta_cents: int
    is_recurring: bool
    is_temporary: bool
    expires_on: date | None


def evaluate_multi_step_scenario_plan(
    db: Session,
    user_id: int,
    payload: MultiStepScenarioPlanRequest,
    *,
    as_of: date | None = None,
) -> MultiStepScenarioPlanOut:
    calculation_date = as_of or date.today()
    horizon_end = calculation_date + timedelta(days=payload.horizon_days)

    ordered_steps = _chronological_order(payload.steps)
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

    (
        checkpoints,
        effects,
        final_raw_cents,
        total_monthly_capacity_delta_cents,
        worst_sequence,
        worst_label,
        worst_date,
        minimum_safe_cents,
        compounding_labels,
    ) = _walk_steps(
        ordered_steps,
        baseline_raw_cents=baseline_raw_cents,
        liquid_balance_cents=baseline.breakdown.liquid_balance_cents,
        horizon_end=horizon_end,
    )

    final_safe_cents = max(final_raw_cents, 0)
    final_shortfall_cents = max(-final_raw_cents, 0)

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
        - total_monthly_capacity_delta_cents
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
            effects,
            horizon_end=horizon_end,
            compounding_labels=compounding_labels,
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
        minimum_safe_to_spend_cents=minimum_safe_cents,
        worst_checkpoint_sequence=worst_sequence,
        worst_checkpoint_label=worst_label,
        worst_checkpoint_date=worst_date,
        overall_status=_STATUS_MAP[
            _determine_status(
                final_raw_cents, baseline.breakdown.liquid_balance_cents
            )
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


def _chronological_order(
    steps: list[MultiStepScenarioStepRequest],
) -> list[MultiStepScenarioStepRequest]:
    # Same-date steps keep their original request order: `sorted` is
    # itself stable, and indexing on `pair[0]` as the tie-breaker makes
    # that explicit rather than incidental.
    return [
        step
        for _, step in sorted(
            enumerate(steps),
            key=lambda pair: (pair[1].effective_date, pair[0]),
        )
    ]


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


def _walk_steps(
    ordered_steps: list[MultiStepScenarioStepRequest],
    *,
    baseline_raw_cents: int,
    liquid_balance_cents: int,
    horizon_end: date,
) -> tuple[
    list[MultiStepScenarioCheckpointOut],
    list[_StepEffect],
    int,
    int,
    int | None,
    str | None,
    date | None,
    int,
    list[str],
]:
    checkpoints: list[MultiStepScenarioCheckpointOut] = []
    effects: list[_StepEffect] = []
    running_raw_cents = baseline_raw_cents
    cumulative_impact_cents = 0
    total_monthly_capacity_delta_cents = 0
    minimum_safe_cents = max(baseline_raw_cents, 0)
    worst_sequence: int | None = None
    worst_label: str | None = None
    worst_date: date | None = None
    compounding_labels: list[str] = []

    for sequence, step in enumerate(ordered_steps, start=1):
        effect = _resolve_step_effect(step, horizon_end)
        effects.append(effect)

        before_raw_cents = running_raw_cents
        running_raw_cents -= effect.cost_delta_cents
        after_raw_cents = running_raw_cents
        cumulative_impact_cents += effect.cost_delta_cents
        total_monthly_capacity_delta_cents += (
            effect.monthly_capacity_delta_cents
        )

        if effect.cost_delta_cents > 0 and before_raw_cents < 0:
            compounding_labels.append(step.label)

        after_safe_cents = max(after_raw_cents, 0)

        if after_safe_cents < minimum_safe_cents:
            minimum_safe_cents = after_safe_cents
            worst_sequence = sequence
            worst_label = step.label
            worst_date = step.effective_date

        checkpoints.append(
            MultiStepScenarioCheckpointOut(
                sequence=sequence,
                step_type=step.step_type,
                label=step.label,
                effective_date=step.effective_date,
                is_recurring=effect.is_recurring,
                is_temporary=effect.is_temporary,
                expires_on=effect.expires_on,
                safe_to_spend_before_cents=max(before_raw_cents, 0),
                safe_to_spend_after_cents=after_safe_cents,
                impact_cents=effect.cost_delta_cents,
                cumulative_impact_cents=cumulative_impact_cents,
                status=_STATUS_MAP[
                    _determine_status(after_raw_cents, liquid_balance_cents)
                ],
            )
        )

    return (
        checkpoints,
        effects,
        running_raw_cents,
        total_monthly_capacity_delta_cents,
        worst_sequence,
        worst_label,
        worst_date,
        minimum_safe_cents,
        compounding_labels,
    )


def _resolve_step_effect(
    step: MultiStepScenarioStepRequest, horizon_end: date
) -> _StepEffect:
    remaining_days = (horizon_end - step.effective_date).days

    if step.step_type in ("one_time_expense", "temporary_expense_shock"):
        assert step.amount_cents is not None
        return _StepEffect(step.amount_cents, 0, False, False, None)

    if step.step_type in _RECURRING_INCREASE_TYPES:
        assert step.amount_cents is not None
        return _StepEffect(
            _prorate_monthly_to_horizon(step.amount_cents, remaining_days),
            step.amount_cents,
            True,
            False,
            None,
        )

    if step.step_type in _RECURRING_DECREASE_TYPES:
        assert step.amount_cents is not None
        return _StepEffect(
            -_prorate_monthly_to_horizon(step.amount_cents, remaining_days),
            0,
            True,
            False,
            None,
        )

    assert step.step_type == "temporary_income_loss"
    assert step.monthly_income_loss_cents is not None
    assert step.duration_months is not None

    months_remaining = remaining_days / _DAYS_PER_MONTH
    effective_months = min(step.duration_months, months_remaining)
    cost_delta_cents = round(
        step.monthly_income_loss_cents * effective_months
    )
    expires_on = step.effective_date + timedelta(
        days=round(_DAYS_PER_MONTH * step.duration_months)
    )

    return _StepEffect(
        cost_delta_cents,
        step.monthly_income_loss_cents,
        False,
        True,
        expires_on,
    )


def _build_warnings(
    ordered_steps: list[MultiStepScenarioStepRequest],
    effects: list[_StepEffect],
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
