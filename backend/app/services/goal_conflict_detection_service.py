from datetime import date
from math import ceil

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SavingsGoal
from app.schemas import (
    GoalConflictDetectionOut,
    GoalConflictDetectionRequest,
    GoalConflictGoalOut,
)


def detect_goal_conflicts(
    db: Session,
    user_id: int,
    payload: GoalConflictDetectionRequest,
    *,
    as_of: date | None = None,
) -> GoalConflictDetectionOut:
    calculation_date = as_of or date.today()

    goals = list(
        db.scalars(
            select(SavingsGoal)
            .where(SavingsGoal.user_id == user_id)
            .order_by(
                SavingsGoal.target_date.asc(),
                SavingsGoal.created_at.asc(),
            )
        ).all()
    )

    warnings: list[str] = []

    if not goals:
        return GoalConflictDetectionOut(
            as_of=calculation_date,
            conflict_status="no_conflict",
            monthly_savings_capacity_cents=(
                payload.monthly_savings_capacity_cents or 0
            ),
            total_required_monthly_cents=0,
            monthly_shortfall_cents=0,
            confidence_score=100.0,
            goals=[],
            explanation="No savings goals were found.",
            recommendations=[
                "Create at least one savings goal to evaluate funding conflicts."
            ],
            warnings=[],
        )

    monthly_capacity = payload.monthly_savings_capacity_cents

    if monthly_capacity is None:
        monthly_capacity = 0
        warnings.append(
            "Monthly savings capacity was not provided, so zero was used."
        )

    prepared_goals: list[dict[str, object]] = []

    for goal in goals:
        remaining_cents = max(
            goal.target_cents - goal.saved_cents,
            0,
        )

        months_remaining = _months_remaining(
            calculation_date,
            goal.target_date,
        )

        required_monthly_cents = _required_monthly_amount(
            remaining_cents,
            months_remaining,
            goal.target_date,
        )

        prepared_goals.append(
            {
                "goal": goal,
                "remaining_cents": remaining_cents,
                "months_remaining": months_remaining,
                "required_monthly_cents": required_monthly_cents,
            }
        )

    total_required = sum(
        int(item["required_monthly_cents"])
        for item in prepared_goals
    )

    remaining_capacity = monthly_capacity
    goal_results: list[GoalConflictGoalOut] = []

    for item in prepared_goals:
        goal = item["goal"]
        remaining_cents = int(item["remaining_cents"])
        months_remaining = item["months_remaining"]
        required_monthly_cents = int(
            item["required_monthly_cents"]
        )

        allocated_monthly_cents = min(
            required_monthly_cents,
            remaining_capacity,
        )

        remaining_capacity -= allocated_monthly_cents

        monthly_shortfall_cents = max(
            required_monthly_cents - allocated_monthly_cents,
            0,
        )

        goal_results.append(
            GoalConflictGoalOut(
                goal_id=goal.id,
                name=goal.name,
                target_cents=goal.target_cents,
                saved_cents=goal.saved_cents,
                remaining_cents=remaining_cents,
                target_date=goal.target_date,
                months_remaining=months_remaining,
                required_monthly_cents=required_monthly_cents,
                allocated_monthly_cents=allocated_monthly_cents,
                monthly_shortfall_cents=monthly_shortfall_cents,
                status=_goal_status(
                    remaining_cents=remaining_cents,
                    target_date=goal.target_date,
                    months_remaining=months_remaining,
                    monthly_shortfall_cents=monthly_shortfall_cents,
                ),
            )
        )

    monthly_shortfall = max(
        total_required - monthly_capacity,
        0,
    )

    conflict_status = _conflict_status(
        monthly_capacity,
        total_required,
        monthly_shortfall,
    )

    return GoalConflictDetectionOut(
        as_of=calculation_date,
        conflict_status=conflict_status,
        monthly_savings_capacity_cents=monthly_capacity,
        total_required_monthly_cents=total_required,
        monthly_shortfall_cents=monthly_shortfall,
        confidence_score=_confidence_score(
            payload.monthly_savings_capacity_cents,
            goals,
        ),
        goals=goal_results,
        explanation=_build_explanation(
            conflict_status,
            monthly_capacity,
            total_required,
            monthly_shortfall,
        ),
        recommendations=_build_recommendations(
            conflict_status,
            goal_results,
        ),
        warnings=warnings,
    )


def _months_remaining(
    as_of: date,
    target_date: date | None,
) -> int | None:
    if target_date is None:
        return None

    month_difference = (
        (target_date.year - as_of.year) * 12
        + target_date.month
        - as_of.month
    )

    if target_date.day > as_of.day:
        month_difference += 1

    return max(month_difference, 0)


def _required_monthly_amount(
    remaining_cents: int,
    months_remaining: int | None,
    target_date: date | None,
) -> int:
    if remaining_cents <= 0:
        return 0

    if target_date is None:
        return 0

    if months_remaining is None or months_remaining <= 0:
        return remaining_cents

    return ceil(remaining_cents / months_remaining)


def _goal_status(
    *,
    remaining_cents: int,
    target_date: date | None,
    months_remaining: int | None,
    monthly_shortfall_cents: int,
) -> str:
    if remaining_cents <= 0:
        return "completed"

    if target_date is None:
        return "no_deadline"

    if months_remaining == 0:
        return "unfunded"

    if monthly_shortfall_cents > 0:
        return "at_risk"

    return "on_track"


def _conflict_status(
    monthly_capacity: int,
    total_required: int,
    monthly_shortfall: int,
) -> str:
    if monthly_shortfall > 0:
        return "conflict"

    if total_required > round(monthly_capacity * 0.8):
        return "strained"

    return "no_conflict"


def _confidence_score(
    provided_capacity: int | None,
    goals: list[SavingsGoal],
) -> float:
    score = 100.0

    if provided_capacity is None:
        score -= 30.0

    if any(goal.target_date is None for goal in goals):
        score -= 10.0

    return max(score, 0.0)


def _format_currency(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def _build_explanation(
    conflict_status: str,
    monthly_capacity: int,
    total_required: int,
    monthly_shortfall: int,
) -> str:
    if conflict_status == "conflict":
        return (
            "Your goals require "
            f"{_format_currency(total_required)} per month, but only "
            f"{_format_currency(monthly_capacity)} is available, "
            f"leaving a {_format_currency(monthly_shortfall)} "
            "monthly shortfall."
        )

    if conflict_status == "strained":
        return (
            "Your goals are currently fundable, but they use most "
            "of your available monthly savings capacity."
        )

    return (
        "Your available monthly savings capacity is sufficient "
        "to support the current goal deadlines."
    )


def _build_recommendations(
    conflict_status: str,
    goals: list[GoalConflictGoalOut],
) -> list[str]:
    recommendations: list[str] = []

    if conflict_status == "conflict":
        recommendations.append(
            "Extend one or more goal deadlines to reduce the "
            "required monthly funding."
        )
        recommendations.append(
            "Prioritize the most important goal and temporarily "
            "reduce funding for lower-priority goals."
        )
        recommendations.append(
            "Increase monthly savings capacity before committing "
            "to all current deadlines."
        )
    elif conflict_status == "strained":
        recommendations.append(
            "Keep a small buffer instead of allocating the full "
            "monthly savings capacity."
        )
    else:
        recommendations.append(
            "Review goal progress monthly and adjust contributions "
            "when income or expenses change."
        )

    if any(goal.status == "no_deadline" for goal in goals):
        recommendations.append(
            "Add target dates to goals without deadlines so their "
            "monthly funding needs can be measured."
        )

    return recommendations
