from calendar import monthrange
from datetime import date
from math import ceil

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SavingsGoal
from app.schemas import GoalImpactOut
from app.services.goal_conflict_detection_service import (
    _months_remaining,
    _required_monthly_amount,
)

# A single, shared per-goal impact calculation used by both the
# financial stress test and the major-purchase / scenario-comparison
# flows, so the two features can never diverge in how they model
# individual goal funding.


def calculate_goal_impacts(
    db: Session,
    user_id: int,
    *,
    baseline_monthly_capacity_cents: int,
    adjusted_monthly_capacity_cents: int,
    as_of: date | None = None,
) -> list[GoalImpactOut]:
    calculation_date = as_of or date.today()

    goals = list(
        db.scalars(
            select(SavingsGoal).where(
                SavingsGoal.user_id == user_id,
                SavingsGoal.saved_cents < SavingsGoal.target_cents,
            )
        ).all()
    )

    if not goals:
        return []

    # Priority order: nearest target date first; goals without a
    # target date sort last. Goal ID is the deterministic tie-breaker
    # for goals that share a date (or share "no date").
    goals.sort(
        key=lambda goal: (
            0 if goal.target_date is not None else 1,
            goal.target_date or date.max,
            goal.id,
        )
    )

    prepared: list[tuple[SavingsGoal, int, int | None, int]] = []

    for goal in goals:
        remaining_cents = max(goal.target_cents - goal.saved_cents, 0)

        if remaining_cents <= 0:
            continue

        months_remaining = _months_remaining(
            calculation_date, goal.target_date
        )
        required_monthly_cents = _required_monthly_amount(
            remaining_cents, months_remaining, goal.target_date
        )

        prepared.append(
            (
                goal,
                remaining_cents,
                months_remaining,
                required_monthly_cents,
            )
        )

    baseline_allocations = _allocate(
        prepared, baseline_monthly_capacity_cents
    )
    adjusted_allocations = _allocate(
        prepared, adjusted_monthly_capacity_cents
    )

    return [
        _build_goal_impact(
            goal=goal,
            remaining_cents=remaining_cents,
            months_remaining=months_remaining,
            required_monthly_cents=required_monthly_cents,
            baseline_allocation_cents=baseline_allocations[goal.id],
            adjusted_allocation_cents=adjusted_allocations[goal.id],
            as_of=calculation_date,
        )
        for goal, remaining_cents, months_remaining, required_monthly_cents
        in prepared
    ]


def _allocate(
    prepared: list[tuple[SavingsGoal, int, int | None, int]],
    capacity_cents: int,
) -> dict[int, int]:
    # Zero/negative capacity can never fund a goal. Capacity is
    # distributed in priority order, and a goal is never allocated
    # more than the remaining amount it still needs (its "surplus"
    # capacity flows to the next goal in priority order instead).
    remaining_capacity = max(capacity_cents, 0)
    allocations: dict[int, int] = {}

    for goal, remaining_cents, _months_remaining, _required in prepared:
        allocated = min(remaining_cents, remaining_capacity)
        allocations[goal.id] = allocated
        remaining_capacity -= allocated

    return allocations


def _months_to_complete(
    remaining_cents: int, allocation_cents: int
) -> int | None:
    if allocation_cents <= 0:
        return None

    return ceil(remaining_cents / allocation_cents)


def _add_months(base: date, months: int) -> date:
    month_index = base.month - 1 + months
    year = base.year + month_index // 12
    month = month_index % 12 + 1
    day = min(base.day, monthrange(year, month)[1])
    return date(year, month, day)


def _format_currency(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def _build_goal_impact(
    *,
    goal: SavingsGoal,
    remaining_cents: int,
    months_remaining: int | None,
    required_monthly_cents: int,
    baseline_allocation_cents: int,
    adjusted_allocation_cents: int,
    as_of: date,
) -> GoalImpactOut:
    allocation_change_cents = (
        adjusted_allocation_cents - baseline_allocation_cents
    )

    baseline_months = _months_to_complete(
        remaining_cents, baseline_allocation_cents
    )
    adjusted_months = _months_to_complete(
        remaining_cents, adjusted_allocation_cents
    )

    baseline_completion = (
        _add_months(as_of, baseline_months)
        if baseline_months is not None
        else None
    )
    adjusted_completion = (
        _add_months(as_of, adjusted_months)
        if adjusted_months is not None
        else None
    )

    if adjusted_allocation_cents <= 0:
        # No positive allocation is available under the scenario, so
        # the target amount cannot be reached on the current plan.
        status = "impossible"
        funding_shortfall_cents = remaining_cents
        delay_months = 0
    elif (
        goal.target_date is not None
        and adjusted_completion is not None
        and adjusted_completion > goal.target_date
    ):
        # A shortfall is expected by the target date. This also
        # covers already-overdue goals, since months_remaining is
        # clamped to 0 and any positive completion estimate lands
        # after a target date that has already passed. Goals without
        # a target date have nothing to be "at risk" against.
        fundable_by_target_cents = adjusted_allocation_cents * max(
            months_remaining or 0, 0
        )
        funding_shortfall_cents = max(
            remaining_cents - fundable_by_target_cents, 0
        )
        status = "at_risk"
        delay_months = 0
    else:
        funding_shortfall_cents = 0

        if baseline_allocation_cents <= 0 or baseline_months is None:
            # Baseline had no positive allocation to compare against
            # (e.g. capacity increased under the scenario), so there
            # is nothing to measure a delay against.
            delay_months = 0
        else:
            delay_months = max(
                (adjusted_months or 0) - baseline_months, 0
            )

        if delay_months > 0:
            status = "delayed"
        elif adjusted_allocation_cents < baseline_allocation_cents:
            status = "reduced"
        else:
            status = "unaffected"

    explanation = _build_goal_explanation(
        goal_name=goal.name,
        status=status,
        has_target_date=goal.target_date is not None,
        baseline_allocation_cents=baseline_allocation_cents,
        adjusted_allocation_cents=adjusted_allocation_cents,
        delay_months=delay_months,
        funding_shortfall_cents=funding_shortfall_cents,
    )

    return GoalImpactOut(
        goal_id=goal.id,
        goal_name=goal.name,
        target_date=goal.target_date,
        target_amount_cents=goal.target_cents,
        saved_amount_cents=goal.saved_cents,
        remaining_amount_cents=remaining_cents,
        current_required_monthly_contribution_cents=(
            required_monthly_cents
        ),
        baseline_monthly_allocation_cents=baseline_allocation_cents,
        adjusted_monthly_allocation_cents=adjusted_allocation_cents,
        monthly_allocation_change_cents=allocation_change_cents,
        baseline_estimated_completion_date=baseline_completion,
        adjusted_estimated_completion_date=adjusted_completion,
        delay_months=delay_months,
        funding_shortfall_cents=funding_shortfall_cents,
        status=status,
        explanation=explanation,
    )


def _build_goal_explanation(
    *,
    goal_name: str,
    status: str,
    has_target_date: bool,
    baseline_allocation_cents: int,
    adjusted_allocation_cents: int,
    delay_months: int,
    funding_shortfall_cents: int,
) -> str:
    if status == "unaffected" and not has_target_date:
        return (
            f"{goal_name} has no target date, so it is not "
            "affected by monthly funding-pace changes."
        )

    if status == "impossible":
        return (
            f"{goal_name} would receive no funding under this "
            "scenario, so its target cannot be reached on the "
            "current plan."
        )

    if status == "at_risk":
        return (
            f"{goal_name} is expected to fall short of its target "
            f"by {_format_currency(funding_shortfall_cents)} at the "
            "target date under this scenario."
        )

    if status == "delayed":
        return (
            f"{goal_name}'s estimated completion moves back by "
            f"{delay_months} month(s) under this scenario, but it "
            "is still expected to be reached on time."
        )

    if status == "reduced":
        return (
            f"{goal_name}'s monthly allocation drops from "
            f"{_format_currency(baseline_allocation_cents)} to "
            f"{_format_currency(adjusted_allocation_cents)}, but it "
            "remains on track to complete on time."
        )

    return f"{goal_name} is not affected by this scenario."
