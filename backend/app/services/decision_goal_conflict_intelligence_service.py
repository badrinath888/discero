"""Goal Conflict Intelligence 2.0 + Goal Conflict Attribution 2.1.

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

Attribution 2.1 classifies each goal's conflict wording by comparing
BASELINE against ADJUSTED state, using only fields already present on
GoalImpactOut -- never a second goal-impact/funding-allocation engine,
and never a new financial number. It fixes the wording bug where a
goal already at $0/mo baseline allocation (already impossible before
any scenario) was reported only as "N in conflict", implying the
scenario itself broke it.
"""

from __future__ import annotations

from app.schemas import (
    GoalConflictAttribution,
    GoalConflictIntelligenceItemOut,
    GoalConflictIntelligenceOut,
    GoalConflictSeverity,
    GoalImpactOut,
    GoalImpactStatus,
)
from app.services.goal_impact_service import _format_currency

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


def _baseline_conflict(impact: GoalImpactOut) -> bool:
    """Whether the goal was ALREADY off track before this scenario,
    reapplying goal_impact_service's own impossible/at-risk thresholds
    to the baseline allocation/completion instead of the adjusted
    ones -- never a new funding calculation."""
    if impact.baseline_monthly_allocation_cents <= 0:
        return True

    return (
        impact.target_date is not None
        and impact.baseline_estimated_completion_date is not None
        and impact.baseline_estimated_completion_date > impact.target_date
    )


def _classify_attribution(
    impact: GoalImpactOut, *, adjusted_conflict: bool, baseline_conflict: bool
) -> GoalConflictAttribution:
    if not baseline_conflict and adjusted_conflict:
        return "scenario_created_conflict"

    if baseline_conflict and adjusted_conflict:
        newly_defunded = (
            impact.baseline_monthly_allocation_cents > 0
            and impact.adjusted_monthly_allocation_cents <= 0
        )
        allocation_worsened = (
            impact.adjusted_monthly_allocation_cents
            < impact.baseline_monthly_allocation_cents
        )
        completion_worsened = (
            impact.baseline_estimated_completion_date is not None
            and impact.adjusted_estimated_completion_date is not None
            and impact.adjusted_estimated_completion_date
            > impact.baseline_estimated_completion_date
        )
        if newly_defunded or allocation_worsened or completion_worsened:
            return "scenario_worsened_conflict"
        return "pre_existing_conflict"

    if baseline_conflict and not adjusted_conflict:
        return "scenario_improved"

    return "unaffected"


def _attribution_text(
    goal_name: str,
    attribution: GoalConflictAttribution,
    impact: GoalImpactOut,
) -> str:
    if attribution == "scenario_created_conflict":
        return f"This scenario causes {goal_name} to fall off track."

    if attribution == "scenario_worsened_conflict":
        if (
            impact.baseline_monthly_allocation_cents > 0
            and impact.adjusted_monthly_allocation_cents <= 0
        ):
            return (
                f"{goal_name} was already off track, and this scenario "
                "removes its funding entirely."
            )
        if (
            impact.adjusted_monthly_allocation_cents
            < impact.baseline_monthly_allocation_cents
        ):
            worsened_cents = (
                impact.baseline_monthly_allocation_cents
                - impact.adjusted_monthly_allocation_cents
            )
            return (
                f"{goal_name} was already off track, and this scenario "
                f"reduces its funding by {_format_currency(worsened_cents)}"
                "/mo."
            )
        return (
            f"{goal_name} was already off track, and this scenario "
            "pushes its projected completion later."
        )

    if attribution == "pre_existing_conflict":
        return (
            f"{goal_name} is already off track before this scenario. "
            "This scenario does not materially worsen the goal."
        )

    if attribution == "scenario_improved":
        return f"This scenario improves {goal_name}'s projected position."

    return f"{goal_name} is not meaningfully affected by this scenario."


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

    items = []
    for rank, impact in enumerate(ordered, start=1):
        adjusted_conflict = impact.status in _CONFLICT_STATUSES
        baseline_conflict = _baseline_conflict(impact)
        attribution = _classify_attribution(
            impact,
            adjusted_conflict=adjusted_conflict,
            baseline_conflict=baseline_conflict,
        )

        items.append(
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
                conflict=adjusted_conflict,
                severity=_SEVERITY_BY_STATUS[impact.status],
                rank=rank,
                attribution=attribution,
                attribution_text=_attribution_text(
                    impact.goal_name, attribution, impact
                ),
            )
        )

    most_affected = next(
        (item.goal_id for item in items if item.severity != "none"), None
    )

    return GoalConflictIntelligenceOut(
        supported=True,
        goals=items,
        most_affected_goal_id=most_affected,
        conflict_count=sum(1 for item in items if item.conflict),
        scenario_created_conflict_count=sum(
            1
            for item in items
            if item.attribution == "scenario_created_conflict"
        ),
        scenario_worsened_conflict_count=sum(
            1
            for item in items
            if item.attribution == "scenario_worsened_conflict"
        ),
        pre_existing_conflict_count=sum(
            1 for item in items if item.attribution == "pre_existing_conflict"
        ),
        scenario_improved_count=sum(
            1 for item in items if item.attribution == "scenario_improved"
        ),
    )
