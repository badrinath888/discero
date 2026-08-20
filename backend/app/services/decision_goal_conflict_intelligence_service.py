"""Goal Conflict Intelligence 2.0.

A pure normalizer/ranker over ALREADY-COMPUTED GoalImpactOut entries
(see app/services/goal_impact_service.py) -- it never recomputes goal
allocation, funding, or completion dates itself, so a goal's numbers
can never diverge between the underlying scenario result and this
view.

Severity is derived only from goal_impact_service's own deterministic
`status` classification, which is itself already a measurable-effect
judgment (no positive allocation available, projected to miss its
target date, a funding-pace delay, or a plain allocation reduction) --
never a new, independently-invented risk score.
"""

from __future__ import annotations

from app.schemas import (
    GoalConflictIntelligenceItemOut,
    GoalConflictIntelligenceOut,
    GoalConflictSeverity,
    GoalImpactOut,
    GoalImpactStatus,
)

# A goal that is merely "reduced" is still on track to complete on
# time (see goal_impact_service._build_goal_impact) -- real pressure
# starts at "delayed". "at_risk"/"impossible" both represent a
# projected shortfall against the target and are equally severe;
# there is no existing measurable signal that ranks one above the
# other, so treating them as distinct severities would be invented,
# not derived.
_SEVERITY_BY_STATUS: dict[GoalImpactStatus, GoalConflictSeverity] = {
    "unaffected": "none",
    "reduced": "low",
    "delayed": "medium",
    "at_risk": "high",
    "impossible": "high",
}

_CONFLICT_STATUSES: frozenset[GoalImpactStatus] = frozenset(
    {"delayed", "at_risk", "impossible"}
)

_SEVERITY_RANK: dict[GoalConflictSeverity, int] = {
    "high": 0,
    "medium": 1,
    "low": 2,
    "none": 3,
}


def build_goal_conflict_intelligence(
    goal_impacts: list[GoalImpactOut],
) -> GoalConflictIntelligenceOut:
    if not goal_impacts:
        return GoalConflictIntelligenceOut(supported=True, goals=[])

    # Most affected first: severity, then the larger of the two
    # measurable pressure signals (a shortfall dollar amount or a
    # delay in months), then goal_id as the final deterministic
    # tie-break.
    ordered = sorted(
        goal_impacts,
        key=lambda impact: (
            _SEVERITY_RANK[_SEVERITY_BY_STATUS[impact.status]],
            -impact.funding_shortfall_cents,
            -impact.delay_months,
            impact.goal_id,
        ),
    )

    items = [
        GoalConflictIntelligenceItemOut(
            goal_id=impact.goal_id,
            goal_name=impact.goal_name,
            baseline_allocation_cents=impact.baseline_monthly_allocation_cents,
            adjusted_allocation_cents=impact.adjusted_monthly_allocation_cents,
            allocation_change_cents=impact.monthly_allocation_change_cents,
            baseline_completion_date=impact.baseline_estimated_completion_date,
            adjusted_completion_date=impact.adjusted_estimated_completion_date,
            delay_months=impact.delay_months,
            funding_shortfall_cents=impact.funding_shortfall_cents,
            status=impact.status,
            conflict=impact.status in _CONFLICT_STATUSES,
            severity=_SEVERITY_BY_STATUS[impact.status],
            rank=rank,
        )
        for rank, impact in enumerate(ordered, start=1)
    ]

    most_affected = next(
        (item.goal_id for item in items if item.severity != "none"), None
    )

    return GoalConflictIntelligenceOut(
        supported=True,
        goals=items,
        most_affected_goal_id=most_affected,
        conflict_count=sum(1 for item in items if item.conflict),
    )
