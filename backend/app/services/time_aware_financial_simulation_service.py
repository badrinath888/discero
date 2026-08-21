"""Time-Aware Financial Simulation Engine 2.0.

The shared deterministic temporal foundation for every feature that
reasons about Discero's known financial state at a point in time other
than right now: Multi-Step Scenario Planning and Buy Now vs Wait.

Two things are always true for state this engine produces:

1. It is built ONLY from already-deterministic Discero data -- the
   current liquid balance, known recurring obligations
   (`RecurringItem`, via `app.recurring.project_occurrences`), and the
   same trailing-average projected-income convention
   `safe_to_spend_service` already uses -- plus whatever explicit
   scenario events a caller supplies. It never predicts discretionary
   spending, investment returns, salary growth, or any other
   unmodeled behavior.
2. Nothing here queries the database once per day or once per
   checkpoint. Recurring obligations/income are loaded with the same
   bounded, single-query helpers `safe_to_spend_service` already uses;
   everything after that is in-memory arithmetic.

Two primitives cover the two ways a caller needs to move through time:

- `walk_step_timeline` -- chronologically applies a small, explicitly
  dated list of scenario events (one-time / recurring / temporary)
  against a starting balance. Used by Multi-Step Scenario Planning.
  Ported unchanged from Multi-Step 1.0's own `_walk_steps` so its
  existing, tested numeric behavior is preserved -- only its location
  (a shared, reusable module instead of a private one) changes.
- `project_known_cashflow_delta_cents` / `advance_known_state_to_date`
  -- nets known recurring obligations against projected income across
  a date range with NO scenario events. Used by Buy Now vs Wait to
  advance today's actual balance to a future WAIT date before that
  date's own safe-to-spend is evaluated -- the step Buy Now vs Wait
  1.0 skipped entirely (WAIT re-ran safe-to-spend AT the future date
  without ever accounting for what happens between now and then, so a
  bill due before the wait date was invisible to it).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.schemas import MultiStepScenarioStepRequest
from app.services.safe_to_spend_service import (
    _DAYS_PER_MONTH,
    _get_projected_income_cents,
    _get_upcoming_obligations,
    _prorate_monthly_to_horizon,
)

# step_type groupings mirror MultiStepScenarioStepType exactly -- see
# app.schemas for the authoritative list.
_RECURRING_INCREASE_TYPES: frozenset[str] = frozenset(
    {"monthly_expense_increase", "monthly_income_decrease"}
)
_RECURRING_DECREASE_TYPES: frozenset[str] = frozenset(
    {"monthly_expense_decrease", "monthly_income_increase"}
)


def _currency(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    return f"{sign}${abs(cents) / 100:,.2f}"


# --- Scenario event timeline (Multi-Step Scenario Planning) ---------------


@dataclass(frozen=True)
class StepTimelineEffect:
    cost_delta_cents: int
    monthly_capacity_delta_cents: int
    is_recurring: bool
    is_temporary: bool
    expires_on: date | None


@dataclass(frozen=True)
class StepTimelineCheckpoint:
    sequence: int
    step: MultiStepScenarioStepRequest
    effect: StepTimelineEffect
    before_raw_cents: int
    after_raw_cents: int
    cumulative_impact_cents: int


@dataclass(frozen=True)
class StepTimelineResult:
    checkpoints: list[StepTimelineCheckpoint]
    final_raw_cents: int
    total_monthly_capacity_delta_cents: int
    worst_sequence: int | None
    worst_label: str | None
    worst_date: date | None
    minimum_safe_cents: int
    compounding_labels: list[str]


def chronological_order(
    steps: list[MultiStepScenarioStepRequest],
) -> list[MultiStepScenarioStepRequest]:
    """Sorts steps by effective_date. Same-date steps keep their
    original request order: `sorted` is itself stable, and indexing on
    `pair[0]` as the tie-breaker makes that explicit rather than
    incidental, so ordering is deterministic and reproducible across
    identical requests regardless of underlying list/DB ordering.
    """
    return [
        step
        for _, step in sorted(
            enumerate(steps),
            key=lambda pair: (pair[1].effective_date, pair[0]),
        )
    ]


def resolve_step_effect(
    step: MultiStepScenarioStepRequest, horizon_end: date
) -> StepTimelineEffect:
    """Resolves one scenario event into a horizon-prorated cost delta.

    A recurring change's effect is prorated against the days remaining
    from ITS OWN effective date to the horizon's end (not the full
    horizon) using the same day-based convention
    `safe_to_spend_service` already uses for goal reserve and projected
    income -- a monthly change that starts partway through the horizon
    only accumulates for its own remaining window, and never
    back-applies to dates before its effective_date.

    A temporary effect's duration is capped by the days remaining in
    the horizon (`effective_months = min(duration, months_remaining)`)
    so it can never bleed impact past the horizon's end, and its
    `expires_on` date is always returned so a caller can show recovery
    after the effect ends.
    """
    remaining_days = (horizon_end - step.effective_date).days

    if step.step_type in ("one_time_expense", "temporary_expense_shock"):
        assert step.amount_cents is not None
        return StepTimelineEffect(step.amount_cents, 0, False, False, None)

    if step.step_type in _RECURRING_INCREASE_TYPES:
        assert step.amount_cents is not None
        return StepTimelineEffect(
            _prorate_monthly_to_horizon(step.amount_cents, remaining_days),
            step.amount_cents,
            True,
            False,
            None,
        )

    if step.step_type in _RECURRING_DECREASE_TYPES:
        assert step.amount_cents is not None
        return StepTimelineEffect(
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

    return StepTimelineEffect(
        cost_delta_cents,
        step.monthly_income_loss_cents,
        False,
        True,
        expires_on,
    )


def walk_step_timeline(
    ordered_steps: list[MultiStepScenarioStepRequest],
    *,
    baseline_raw_cents: int,
    horizon_end: date,
) -> StepTimelineResult:
    """Walks a chronologically-ordered event list forward in memory,
    carrying the running RAW (unclamped) total between events so a
    temporary shortfall can still be seen to recover in a later
    checkpoint instead of being silently pinned at $0 by an
    intermediate clamp. Only `minimum_safe_cents` (the worst point) and
    each checkpoint's own before/after DISPLAY values are floored at
    zero -- the running total that feeds the NEXT event is always the
    raw figure.
    """
    checkpoints: list[StepTimelineCheckpoint] = []
    running_raw_cents = baseline_raw_cents
    cumulative_impact_cents = 0
    total_monthly_capacity_delta_cents = 0
    minimum_safe_cents = max(baseline_raw_cents, 0)
    worst_sequence: int | None = None
    worst_label: str | None = None
    worst_date: date | None = None
    compounding_labels: list[str] = []

    for sequence, step in enumerate(ordered_steps, start=1):
        effect = resolve_step_effect(step, horizon_end)

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
            StepTimelineCheckpoint(
                sequence=sequence,
                step=step,
                effect=effect,
                before_raw_cents=before_raw_cents,
                after_raw_cents=after_raw_cents,
                cumulative_impact_cents=cumulative_impact_cents,
            )
        )

    return StepTimelineResult(
        checkpoints=checkpoints,
        final_raw_cents=running_raw_cents,
        total_monthly_capacity_delta_cents=total_monthly_capacity_delta_cents,
        worst_sequence=worst_sequence,
        worst_label=worst_label,
        worst_date=worst_date,
        minimum_safe_cents=minimum_safe_cents,
        compounding_labels=compounding_labels,
    )


# --- Known-cashflow state advance (Buy Now vs Wait) ------------------------


@dataclass(frozen=True)
class KnownCashflowProjection:
    obligations_cents: int
    projected_income_cents: int
    net_delta_cents: int
    notices: list[str] = field(default_factory=list)


def project_known_cashflow_delta_cents(
    db: Session,
    user_id: int,
    start_date: date,
    end_date: date,
) -> KnownCashflowProjection:
    """Nets KNOWN recurring obligations against projected income across
    [start_date, end_date).

    `end_date` is EXCLUSIVE so a caller that separately evaluates
    end_date's own safe-to-spend window (which always starts AT
    end_date) never double counts an obligation landing exactly on
    end_date.

    Only RecurringItem-based obligations are counted -- the same
    `_get_upcoming_obligations` helper `safe_to_spend_service` already
    uses for its own obligations window. Budget-based "remaining
    envelope" obligations are tied to a specific calendar-month
    horizon window, not a literal dated cashflow, so they are
    deliberately excluded from a balance-advance projection rather
    than stretched to mean something they don't.
    """
    if end_date <= start_date:
        return KnownCashflowProjection(0, 0, 0, [])

    gap_days = (end_date - start_date).days
    through_date = end_date - timedelta(days=1)

    obligations = _get_upcoming_obligations(
        db, user_id, start_date, through_date
    )
    obligations_cents = sum(
        obligation.amount_cents for obligation in obligations
    )

    projected_income_cents = _get_projected_income_cents(
        db, user_id, start_date, gap_days
    )

    notices: list[str] = []
    if obligations_cents or projected_income_cents:
        notices.append(
            f"Between {start_date.isoformat()} and {end_date.isoformat()}, "
            f"known obligations of {_currency(obligations_cents)} and "
            f"projected income of {_currency(projected_income_cents)} were "
            "applied to advance your balance to that date."
        )

    return KnownCashflowProjection(
        obligations_cents=obligations_cents,
        projected_income_cents=projected_income_cents,
        net_delta_cents=obligations_cents - projected_income_cents,
        notices=notices,
    )


def advance_known_state_to_date(
    db: Session,
    user_id: int,
    *,
    current_liquid_balance_cents: int,
    start_date: date,
    target_date: date,
) -> tuple[int, list[str]]:
    """Advances a known liquid balance from `start_date` to
    `target_date` using only known recurring obligations/income --
    never a prediction of discretionary spending. Returns
    (advanced_liquid_balance_cents, notices). The result is not
    floored at zero: it is carried forward raw so a downstream
    safe-to-spend calculation sees the true (possibly negative)
    projected position rather than a silently masked shortfall.
    """
    projection = project_known_cashflow_delta_cents(
        db, user_id, start_date, target_date
    )
    advanced_cents = current_liquid_balance_cents - projection.net_delta_cents
    return advanced_cents, projection.notices
