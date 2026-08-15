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
from math import ceil

from sqlalchemy.orm import Session

from app.schemas import (
    GoalConflictDetectionRequest,
    GoalConflictGoalOut,
    GoalConflictRecommendationOut,
    GoalIntelligenceGoalOut,
    GoalIntelligenceOut,
)
from app.services.goal_conflict_detection_service import (
    _lowest_priority_funded_goal,
    _months_remaining,
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


def _is_ahead_of_schedule(goal_result: GoalConflictGoalOut) -> bool:
    """Ahead when banked progress already beats what an even, linear
    pace from the goal's creation date to its target date would have
    saved by now -- by at least one full month of that original pace,
    so rounding noise never flips a goal to "ahead".

    Deliberately independent of the capacity-based allocation
    waterfall: `allocated_monthly_cents` is capped at
    `required_monthly_cents` by design (see module docstring), so a
    goal can never be projected to finish *before* its target through
    that path alone. This is the only signal that can show a user is
    genuinely ahead of their own original plan.
    """
    target_date = goal_result.target_date
    if target_date is None or goal_result.remaining_cents <= 0:
        return False

    total_months = _months_remaining(goal_result.created_at, target_date)
    if total_months is None or total_months <= 0:
        return False

    elapsed_months = total_months - (goal_result.months_remaining or 0)
    if elapsed_months <= 0:
        return False

    original_monthly_cents = ceil(goal_result.target_cents / total_months)
    if original_monthly_cents <= 0:
        return False

    expected_saved_cents = min(
        original_monthly_cents * elapsed_months, goal_result.target_cents
    )

    return (
        goal_result.saved_cents - expected_saved_cents
    ) >= original_monthly_cents


def _intelligence_status(
    goal_result: GoalConflictGoalOut,
    shortfalled_goal_count: int,
    is_ahead: bool,
) -> str:
    if goal_result.status == "completed":
        return "completed"

    if goal_result.status == "no_deadline":
        return "no_deadline"

    if goal_result.status == "unfunded":
        # Target date has already passed with money still owed -- no
        # future contribution schedule can retroactively fix this, so
        # it's distinct from a goal that's merely underfunded with
        # time still on the clock.
        return "not_feasible"

    if goal_result.status == "on_track":
        return "ahead" if is_ahead else "on_track"

    # "at_risk" at the per-goal level: escalate to "conflict" only
    # when MULTIPLE goals are actually competing for the same
    # capacity, so a single goal's own tight timeline (no other goal
    # involved) isn't confused with competing-goal pressure.
    if goal_result.monthly_shortfall_cents > 0 and shortfalled_goal_count > 1:
        return "conflict"

    return "at_risk"


_KEY_DRIVER_BY_STATUS = {
    "completed": "goal_already_completed",
    "no_deadline": "no_target_date_set",
    "ahead": "ahead_of_schedule",
    "on_track": "on_track",
    "not_feasible": "target_date_passed",
    "conflict": "competing_goal_priority",
    "at_risk": "insufficient_monthly_capacity",
}


def _goal_key_driver(status: str) -> str:
    return _KEY_DRIVER_BY_STATUS[status]


def _no_change_action(message: str) -> GoalConflictRecommendationOut:
    return GoalConflictRecommendationOut(
        type="no_change_needed",
        message=message,
        resulting_monthly_gap_cents=0,
    )


def _goal_recommended_actions(
    goal_result: GoalConflictGoalOut,
    status: str,
    projected_completion_date: date | None,
    all_goal_results: list[GoalConflictGoalOut],
) -> tuple[GoalConflictRecommendationOut, list[GoalConflictRecommendationOut]]:
    """The smallest deterministic action that restores the goal to
    on-track, plus at most two bounded alternatives (Discero product
    rule: never flood the UI with options).
    """
    name = goal_result.name
    gap = goal_result.monthly_shortfall_cents

    if status == "completed":
        return _no_change_action(f"{name} has already reached its target."), []

    if status == "no_deadline":
        return (
            _no_change_action(
                f"Add a target date to {name} to measure its funding needs."
            ),
            [],
        )

    if status == "ahead":
        return (
            _no_change_action(
                f"{name} is ahead of its original pace and remains on track."
            ),
            [],
        )

    if status == "on_track":
        return (
            _no_change_action(f"{name} is funded to reach its target on time."),
            [],
        )

    if status == "not_feasible":
        if projected_completion_date is not None:
            primary = GoalConflictRecommendationOut(
                type="extend_target_date",
                message=(
                    f"{name}'s target date has already passed -- move it to "
                    f"{projected_completion_date.isoformat()} to match its "
                    "current funding pace."
                ),
                goal_id=goal_result.goal_id,
                resulting_monthly_gap_cents=0,
            )
        else:
            primary = GoalConflictRecommendationOut(
                type="increase_goal_allocation",
                message=(
                    f"{name}'s target date has passed with "
                    f"{_currency(goal_result.remaining_cents)} still needed "
                    "-- increase its monthly allocation to begin funding it."
                ),
                goal_id=goal_result.goal_id,
                amount_cents=gap,
                resulting_monthly_gap_cents=gap,
            )
        return primary, []

    # at_risk / conflict: the smallest fix is closing the exact
    # monthly gap on this goal.
    primary = GoalConflictRecommendationOut(
        type="increase_goal_allocation",
        message=(
            f"Increase {name}'s monthly allocation by {_currency(gap)} to "
            "stay on track for its target date."
        ),
        goal_id=goal_result.goal_id,
        amount_cents=gap,
        resulting_monthly_gap_cents=0,
    )

    alternatives: list[GoalConflictRecommendationOut] = []

    if projected_completion_date is not None:
        alternatives.append(
            GoalConflictRecommendationOut(
                type="extend_target_date",
                message=(
                    f"Or move {name}'s target date to "
                    f"{projected_completion_date.isoformat()} to fit the "
                    "current funding pace."
                ),
                goal_id=goal_result.goal_id,
                resulting_monthly_gap_cents=0,
            )
        )

    if status == "conflict":
        donor = _lowest_priority_funded_goal(
            all_goal_results, exclude_goal_id=goal_result.goal_id
        )
        if donor is not None:
            shift = min(donor.allocated_monthly_cents, gap)
            if shift > 0:
                alternatives.append(
                    GoalConflictRecommendationOut(
                        type="reprioritize_goal",
                        message=(
                            f"Or reprioritize {name} above {donor.name} to "
                            f"free up {_currency(shift)}/month."
                        ),
                        goal_id=donor.goal_id,
                        amount_cents=shift,
                        resulting_monthly_gap_cents=max(gap - shift, 0),
                    )
                )

    return primary, alternatives[:2]


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

    if status == "ahead":
        return (
            f"{name} has already saved more than its original even pace "
            "would require, and is ahead of its target date."
        )

    shortfall = _currency(goal_result.monthly_shortfall_cents)
    required = _currency(goal_result.required_monthly_cents)

    if status == "not_feasible":
        base = (
            f"{name}'s target date has already passed with "
            f"{_currency(goal_result.remaining_cents)} still needed."
        )
    elif status == "conflict":
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
        is_ahead = _is_ahead_of_schedule(goal_result)
        status = _intelligence_status(
            goal_result, shortfalled_goal_count, is_ahead
        )

        projected_completion_date = calculate_feasible_target_date(
            goal_result.remaining_cents,
            goal_result.allocated_monthly_cents,
            calculation_date,
        )

        suggested_feasible_target_date = (
            projected_completion_date
            if status in ("at_risk", "conflict", "not_feasible")
            else None
        )

        # How many months late the goal is projected to finish,
        # reusing `_months_remaining` (already the single source of
        # truth for month-counting elsewhere in the app) to measure
        # the gap between the goal's own target date and its
        # currently-funded projected completion date. Left `None`
        # when there's no funded projection to compare against (goal
        # has no deadline, or is completely unfunded) so a delay is
        # never fabricated -- see `calculate_feasible_target_date`.
        projected_delay_months = (
            _months_remaining(
                goal_result.target_date, projected_completion_date
            )
            if goal_result.target_date is not None
            and projected_completion_date is not None
            else None
        )

        recommended_action, alternative_actions = _goal_recommended_actions(
            goal_result, status, projected_completion_date, conflict.goals
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
                    projected_delay_months=projected_delay_months,
                    urgency_rank=None,
                    confidence_score=conflict.confidence_score,
                    explanation=_goal_explanation(
                        goal_result, status, projected_completion_date
                    ),
                    key_driver=_goal_key_driver(status),
                    recommended_action=recommended_action,
                    alternative_actions=alternative_actions,
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
        monthly_headroom_cents=conflict.monthly_headroom_cents,
        key_driver=conflict.key_driver,
        largest_pressure_goal_id=largest_pressure_goal_id,
        confidence_score=conflict.confidence_score,
        explanation=conflict.explanation,
        suggestions=suggestions,
        recommendation=conflict.recommendation,
        recommendation_alternatives=conflict.recommendation_alternatives,
        warnings=conflict.warnings,
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
