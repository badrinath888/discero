from datetime import date
from math import ceil

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SavingsGoal
from app.schemas import (
    GoalConflictDetectionOut,
    GoalConflictDetectionRequest,
    GoalConflictGoalOut,
    GoalConflictRecommendationOut,
    SafeToSpendRequest,
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
        no_goals_capacity = payload.monthly_savings_capacity_cents or 0
        return GoalConflictDetectionOut(
            as_of=calculation_date,
            conflict_status="no_conflict",
            monthly_savings_capacity_cents=no_goals_capacity,
            total_required_monthly_cents=0,
            monthly_shortfall_cents=0,
            monthly_headroom_cents=no_goals_capacity,
            key_driver="no_goals",
            confidence_score=100.0,
            goals=[],
            explanation="No savings goals were found.",
            recommendations=[
                "Create at least one savings goal to evaluate funding conflicts."
            ],
            recommendation=GoalConflictRecommendationOut(
                type="no_change_needed",
                message=(
                    "Create at least one savings goal to evaluate "
                    "funding conflicts."
                ),
                resulting_monthly_gap_cents=0,
            ),
            recommendation_alternatives=[],
            warnings=[],
        )

    monthly_capacity = payload.monthly_savings_capacity_cents

    if monthly_capacity is None:
        monthly_capacity = _derive_realistic_monthly_capacity_cents(
            db,
            user_id,
            calculation_date,
        )
        warnings.append(
            "Monthly savings capacity was estimated from your recent "
            "income and upcoming obligations."
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

    key_driver = _key_driver(
        conflict_status,
        monthly_capacity,
        goal_results,
    )

    recommendation, recommendation_alternatives = _build_recommendation(
        conflict_status,
        monthly_capacity,
        monthly_shortfall,
        goal_results,
    )

    return GoalConflictDetectionOut(
        as_of=calculation_date,
        conflict_status=conflict_status,
        monthly_savings_capacity_cents=monthly_capacity,
        total_required_monthly_cents=total_required,
        monthly_shortfall_cents=monthly_shortfall,
        monthly_headroom_cents=max(monthly_capacity - total_required, 0),
        key_driver=key_driver,
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
        recommendation=recommendation,
        recommendation_alternatives=recommendation_alternatives,
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


def _derive_realistic_monthly_capacity_cents(
    db: Session,
    user_id: int,
    as_of: date,
) -> int:
    """Realistic monthly savings capacity when the caller didn't supply
    one: recent income minus upcoming obligations over the same
    30-day window, reusing the Safe-to-Spend engine so this can never
    diverge from how capacity is measured elsewhere in the app.

    `include_goal_reserve=False` is deliberate -- goal funding is
    exactly what THIS calculation is being used to determine, so it
    must not already be subtracted from the capacity being measured
    against it.

    Imported lazily to avoid a circular import: `safe_to_spend_service`
    already imports `_months_remaining`/`_required_monthly_amount` from
    this module at load time.
    """
    from app.services.safe_to_spend_service import (
        _DAYS_PER_MONTH,
        calculate_safe_to_spend,
    )

    baseline = calculate_safe_to_spend(
        db,
        user_id,
        SafeToSpendRequest(
            horizon_days=_DAYS_PER_MONTH,
            include_projected_income=True,
            include_goal_reserve=False,
        ),
        as_of=as_of,
    )

    return max(
        baseline.breakdown.projected_income_cents
        - baseline.breakdown.upcoming_obligations_cents,
        0,
    )


def _largest_pressure_goal(
    goal_results: list[GoalConflictGoalOut],
) -> GoalConflictGoalOut | None:
    shortfalled = [
        goal for goal in goal_results if goal.monthly_shortfall_cents > 0
    ]

    if not shortfalled:
        return None

    return max(
        shortfalled,
        key=lambda goal: (
            goal.monthly_shortfall_cents,
            goal.required_monthly_cents,
        ),
    )


def _key_driver(
    conflict_status: str,
    monthly_capacity: int,
    goal_results: list[GoalConflictGoalOut],
) -> str:
    if not goal_results:
        return "no_goals"

    if conflict_status != "conflict":
        return "no_conflict"

    if monthly_capacity <= 0:
        return "insufficient_capacity"

    return "largest_required_goal"


def _lowest_priority_funded_goal(
    goal_results: list[GoalConflictGoalOut],
    *,
    exclude_goal_id: int | None,
) -> GoalConflictGoalOut | None:
    """The most defensible discretionary "donor" for a reprioritize
    suggestion: a goal that is already fully funded (no shortfall)
    with a real allocation and the latest deadline -- i.e. the least
    time-urgent goal under the same earliest-deadline-first priority
    this module already allocates capacity by.
    """
    candidates = [
        goal
        for goal in goal_results
        if goal.allocated_monthly_cents > 0
        and goal.monthly_shortfall_cents == 0
        and goal.target_date is not None
        and goal.goal_id != exclude_goal_id
    ]

    if not candidates:
        return None

    return max(candidates, key=lambda goal: (goal.target_date, goal.goal_id))


def _build_recommendation(
    conflict_status: str,
    monthly_capacity: int,
    monthly_shortfall: int,
    goal_results: list[GoalConflictGoalOut],
) -> tuple[GoalConflictRecommendationOut, list[GoalConflictRecommendationOut]]:
    if conflict_status != "conflict":
        return (
            GoalConflictRecommendationOut(
                type="no_change_needed",
                message=(
                    "Your current goals are jointly fundable within "
                    "your available monthly capacity."
                ),
                resulting_monthly_gap_cents=0,
            ),
            [],
        )

    primary = GoalConflictRecommendationOut(
        type="increase_monthly_capacity",
        message=(
            "Increase available monthly savings by "
            f"{_format_currency(monthly_shortfall)} to fund all "
            "current goals on time."
        ),
        amount_cents=monthly_shortfall,
        resulting_monthly_gap_cents=0,
    )

    alternatives: list[GoalConflictRecommendationOut] = []

    pressure_goal = _largest_pressure_goal(goal_results)

    if (
        pressure_goal is not None
        and pressure_goal.allocated_monthly_cents > 0
        and pressure_goal.months_remaining is not None
    ):
        # Reuses the exact months-to-complete formula
        # `goal_impact_service`/`goal_intelligence_service` already use
        # for projected completion, imported lazily to avoid the
        # circular import (`goal_impact_service` imports this module
        # at load time).
        from app.services.goal_impact_service import _months_to_complete

        months_needed = _months_to_complete(
            pressure_goal.remaining_cents,
            pressure_goal.allocated_monthly_cents,
        )
        extension_months = (
            max(months_needed - pressure_goal.months_remaining, 0)
            if months_needed is not None
            else 0
        )

        if extension_months > 0:
            alternatives.append(
                GoalConflictRecommendationOut(
                    type="extend_target_date",
                    message=(
                        f"Extend {pressure_goal.name}'s target date by "
                        f"{extension_months} month"
                        f"{'s' if extension_months != 1 else ''} to fit "
                        f"your current {_format_currency(monthly_capacity)}"
                        "/month capacity."
                    ),
                    goal_id=pressure_goal.goal_id,
                    extension_months=extension_months,
                    resulting_monthly_gap_cents=max(
                        monthly_shortfall
                        - pressure_goal.monthly_shortfall_cents,
                        0,
                    ),
                )
            )

    donor = _lowest_priority_funded_goal(
        goal_results,
        exclude_goal_id=(
            pressure_goal.goal_id if pressure_goal is not None else None
        ),
    )

    if donor is not None:
        shift_amount = min(donor.allocated_monthly_cents, monthly_shortfall)

        if shift_amount > 0:
            alternatives.append(
                GoalConflictRecommendationOut(
                    type="reprioritize_goal",
                    message=(
                        f"Reallocate {_format_currency(shift_amount)}"
                        f"/month from {donor.name} to your underfunded "
                        "goals."
                    ),
                    goal_id=donor.goal_id,
                    amount_cents=shift_amount,
                    resulting_monthly_gap_cents=max(
                        monthly_shortfall - shift_amount,
                        0,
                    ),
                )
            )

    return primary, alternatives[:2]
