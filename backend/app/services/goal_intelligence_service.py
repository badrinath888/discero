"""Goal Intelligence: per-goal urgency, feasibility, and conflict detail.

Deliberately does not reinvent allocation math. The underlying capacity
allocation (nearest-deadline-first, matching `detect_goal_conflicts`'s
existing, already-tested strategy) and required-monthly-amount formula
both come from `goal_conflict_detection_service`. This module only adds
derived, explainable fields on top: urgency ranking, projected
completion, and a feasible target date at the currently allocated pace.

Nothing here writes to a goal record -- these are recommendations only.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.schemas import (
    GoalConflictDetectionRequest,
    GoalConflictGoalOut,
    GoalIntelligenceGoalOut,
    GoalIntelligenceOut,
)
from app.services.goal_conflict_detection_service import (
    detect_goal_conflicts,
)
from app.services.goal_impact_service import _add_months, _months_to_complete


def _currency(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    return f"{sign}${abs(cents) / 100:,.2f}"


def calculate_feasible_target_date(
    remaining_cents: int,
    monthly_contribution_cents: int,
    as_of: date,
) -> date | None:
    """"If I can only contribute $X/month, when would this realistically
    finish?" Returns None when it's already complete or truly can never
    finish at that pace (zero/negative contribution with money still
    owed).
    """
    if remaining_cents <= 0:
        return as_of

    if monthly_contribution_cents <= 0:
        return None

    months = _months_to_complete(remaining_cents, monthly_contribution_cents)

    if months is None:
        return None

    return _add_months(as_of, months)


def _intelligence_status(
    goal_result: GoalConflictGoalOut, shortfalled_goal_count: int
) -> str:
    if goal_result.status == "completed":
        return "completed"

    if goal_result.status == "no_deadline":
        return "no_deadline"

    if goal_result.status == "on_track":
        return "on_track"

    # "at_risk" or "unfunded" at the per-goal level: escalate to
    # "conflict" only when MULTIPLE goals are actually competing for
    # the same capacity, so a single goal's own tight timeline (no
    # other goal involved) isn't confused with competing-goal
    # pressure.
    if goal_result.monthly_shortfall_cents > 0 and shortfalled_goal_count > 1:
        return "conflict"

    return "at_risk"


def _urgency_sort_key(goal_result: GoalConflictGoalOut) -> tuple:
    has_shortfall = goal_result.monthly_shortfall_cents > 0
    # Goals without a deadline are the least time-urgent; push them last.
    months = (
        goal_result.months_remaining
        if goal_result.months_remaining is not None
        else 10_000
    )
    return (
        0 if has_shortfall else 1,
        months,
        -goal_result.required_monthly_cents,
        goal_result.goal_id,
    )


def _goal_explanation(
    goal_result: GoalConflictGoalOut,
    status: str,
    projected_completion_date: date | None,
) -> str:
    name = goal_result.name

    if status == "completed":
        return f"{name} has already reached its target."

    if status == "no_deadline":
        return f"{name} has no target date, so timing pressure can't be measured."

    if status == "on_track":
        return (
            f"{name} is funded at {_currency(goal_result.allocated_monthly_cents)}"
            "/month, enough to reach its target on time."
        )

    shortfall = _currency(goal_result.monthly_shortfall_cents)
    required = _currency(goal_result.required_monthly_cents)

    if status == "conflict":
        base = (
            f"{name} needs {required}/month, but competing goals leave "
            f"only {_currency(goal_result.allocated_monthly_cents)}/month "
            f"available -- a {shortfall}/month gap."
        )
    else:
        base = f"{name} needs {required}/month, a {shortfall}/month gap at your current capacity."

    if projected_completion_date and goal_result.target_date:
        base += (
            f" At this pace, it would realistically finish around "
            f"{projected_completion_date.isoformat()} instead of "
            f"{goal_result.target_date.isoformat()}."
        )

    return base


def evaluate_goal_intelligence(
    db: Session,
    user_id: int,
    *,
    monthly_capacity_cents: int | None = None,
    as_of: date | None = None,
) -> GoalIntelligenceOut:
    calculation_date = as_of or date.today()

    conflict = detect_goal_conflicts(
        db,
        user_id,
        GoalConflictDetectionRequest(
            monthly_savings_capacity_cents=monthly_capacity_cents
        ),
        as_of=calculation_date,
    )

    shortfalled_goal_count = sum(
        1 for g in conflict.goals if g.monthly_shortfall_cents > 0
    )

    # Keep each derived output paired with its raw conflict-detection
    # result so ranking/lookups never risk misaligning two lists.
    pairs: list[tuple[GoalIntelligenceGoalOut, GoalConflictGoalOut]] = []

    for goal_result in conflict.goals:
        status = _intelligence_status(goal_result, shortfalled_goal_count)

        projected_completion_date = calculate_feasible_target_date(
            goal_result.remaining_cents,
            goal_result.allocated_monthly_cents,
            calculation_date,
        )

        suggested_feasible_target_date = (
            projected_completion_date
            if status in ("at_risk", "conflict")
            else None
        )

        pairs.append(
            (
                GoalIntelligenceGoalOut(
                    goal_id=goal_result.goal_id,
                    name=goal_result.name,
                    target_amount_cents=goal_result.target_cents,
                    saved_amount_cents=goal_result.saved_cents,
                    remaining_amount_cents=goal_result.remaining_cents,
                    target_date=goal_result.target_date,
                    months_remaining=goal_result.months_remaining,
                    required_monthly_cents=goal_result.required_monthly_cents,
                    allocated_monthly_cents=goal_result.allocated_monthly_cents,
                    monthly_gap_cents=goal_result.monthly_shortfall_cents,
                    status=status,
                    projected_completion_date=projected_completion_date,
                    suggested_feasible_target_date=suggested_feasible_target_date,
                    urgency_rank=None,
                    confidence_score=conflict.confidence_score,
                    explanation=_goal_explanation(
                        goal_result, status, projected_completion_date
                    ),
                ),
                goal_result,
            )
        )

    enriched = [goal_out for goal_out, _raw in pairs]

    # Rank urgency deterministically: goals with a live funding gap
    # first (nearest deadline, then larger required payment as
    # tiebreakers); completed goals are never ranked.
    rankable = sorted(
        (pair for pair in pairs if pair[1].status != "completed"),
        key=lambda pair: _urgency_sort_key(pair[1]),
    )
    for rank, (goal_out, _raw) in enumerate(rankable, start=1):
        goal_out.urgency_rank = rank

    largest_pressure_goal_id = None
    shortfalled = [g for g in conflict.goals if g.monthly_shortfall_cents > 0]
    if shortfalled:
        worst = max(
            shortfalled,
            key=lambda g: (g.monthly_shortfall_cents, g.required_monthly_cents),
        )
        largest_pressure_goal_id = worst.goal_id

    suggestions = _build_suggestions(
        conflict.conflict_status,
        conflict.monthly_savings_capacity_cents,
        conflict.monthly_shortfall_cents,
        enriched,
        largest_pressure_goal_id,
    )

    return GoalIntelligenceOut(
        as_of=calculation_date,
        conflict_status=conflict.conflict_status,
        total_capacity_cents=conflict.monthly_savings_capacity_cents,
        total_required_cents=conflict.total_required_monthly_cents,
        total_shortfall_cents=conflict.monthly_shortfall_cents,
        largest_pressure_goal_id=largest_pressure_goal_id,
        confidence_score=conflict.confidence_score,
        explanation=conflict.explanation,
        suggestions=suggestions,
        goals=sorted(
            enriched,
            key=lambda g: (g.urgency_rank is None, g.urgency_rank or 0),
        ),
    )


def _build_suggestions(
    conflict_status: str,
    capacity_cents: int,
    shortfall_cents: int,
    goals: list[GoalIntelligenceGoalOut],
    largest_pressure_goal_id: int | None,
) -> list[str]:
    if conflict_status == "no_conflict":
        return []

    suggestions: list[str] = []

    if shortfall_cents > 0:
        suggestions.append(
            f"Increase monthly savings by {_currency(shortfall_cents)} "
            "to fund all current goals on time."
        )

    pressure_goal = next(
        (g for g in goals if g.goal_id == largest_pressure_goal_id),
        None,
    )

    if pressure_goal and pressure_goal.suggested_feasible_target_date:
        suggestions.append(
            f"Or move {pressure_goal.name}'s target date to "
            f"{pressure_goal.suggested_feasible_target_date.isoformat()} "
            f"to fit your current {_currency(capacity_cents)}/month capacity."
        )

    nearest_deadline_goal = next(
        (g for g in goals if g.urgency_rank == 1),
        None,
    )
    if nearest_deadline_goal and (
        pressure_goal is None
        or nearest_deadline_goal.goal_id != pressure_goal.goal_id
    ):
        suggestions.append(
            f"If you can't fund every goal, prioritize {nearest_deadline_goal.name} "
            "since its deadline is nearest."
        )

    return suggestions
