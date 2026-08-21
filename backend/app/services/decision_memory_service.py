"""Financial Decision Memory 2.0.

A deterministic, user-scoped READ MODEL over already-persisted
SavedDecision/DecisionOutcome state -- never LLM memory, never a new
calculation engine. Directional/favorable-unfavorable semantics are
reused verbatim from decision_calibration_service (never a second
directionality engine); the review-queue count reuses
decision_review_service. Every count/rate below is either a bounded
aggregate SQL query or a pure recomputation over those two services'
own already-bounded results -- never one query per decision.

Deliberately excluded, per product scope: fuzzy/semantic title
deduplication ("New Laptop" vs "MacBook" are always distinct decisions),
embeddings, and any invented behavioral label ("impulsive",
"disciplined", etc.) not backed by a persisted, countable fact.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import SavedDecision
from app.schemas import (
    DecisionMemoryFollowThroughOut,
    DecisionMemoryOut,
    DecisionMemoryOutcomeSummaryOut,
    DecisionMemoryPatternOut,
    DecisionMemorySummaryOut,
    DecisionMemoryTypeBreakdownOut,
)
from app.services import decision_calibration_service, decision_review_service

_MOST_USED_TYPES_LIMIT = 3
_MOST_FREQUENT_METRICS_LIMIT = 5
_REPEATED_TYPE_PATTERN_MIN_COUNT = 3
_UNRESOLVED_PATTERN_MIN_COUNT = 3
# No existing "recent decision usage" window convention exists elsewhere
# in the codebase to reuse (decision_dashboard_intelligence_service's
# "recent_decision" means only "the single latest one"); the other
# "recent" windows in the codebase (forecast_confidence_service,
# spending_anomaly_service) are about transaction recency, a different
# concept. 90 days is a simple, explicit, product-appropriate window
# for "recent decision activity" -- never a time-decay/fuzzy system.
_RECENT_PATTERN_WINDOW_DAYS = 90

_DECISION_TYPE_LABELS: dict[str, str] = {
    "major_purchase": "major purchase",
    "scenario_comparison": "purchase scenario comparison",
    "stress_test": "stress test",
    "buy_now_vs_wait": "buy now vs. wait",
    "what_if": "what-if",
    "what_if_comparison": "what-if comparison",
    "multi_step_plan": "multi-step plan",
}


def _type_label(decision_type: str) -> str:
    return _DECISION_TYPE_LABELS.get(decision_type, decision_type)


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator > 0 else None


def get_decision_memory(
    db: Session, user_id: int, *, now: datetime | None = None
) -> DecisionMemoryOut:
    reference_time = now or datetime.now(timezone.utc)
    recent_cutoff = reference_time - timedelta(
        days=_RECENT_PATTERN_WINDOW_DAYS
    )

    status_counts = dict(
        db.execute(
            select(SavedDecision.status, func.count(SavedDecision.id))
            .where(SavedDecision.user_id == user_id)
            .group_by(SavedDecision.status)
        ).all()
    )

    type_status_rows = db.execute(
        select(
            SavedDecision.decision_type,
            SavedDecision.status,
            func.count(SavedDecision.id),
        )
        .where(SavedDecision.user_id == user_id)
        .group_by(SavedDecision.decision_type, SavedDecision.status)
    ).all()

    saved_count_by_type: dict[str, int] = {}
    acted_on_count_by_type: dict[str, int] = {}
    for decision_type, status, count in type_status_rows:
        saved_count_by_type[decision_type] = (
            saved_count_by_type.get(decision_type, 0) + count
        )
        if status == "acted_on":
            acted_on_count_by_type[decision_type] = count

    earliest_at, latest_at = db.execute(
        select(
            func.min(SavedDecision.created_at),
            func.max(SavedDecision.created_at),
        ).where(SavedDecision.user_id == user_id)
    ).one()

    total_saved_decisions = sum(status_counts.values())
    acted_on_count = status_counts.get("acted_on", 0)
    dismissed_count = status_counts.get("dismissed", 0)
    unresolved_count = status_counts.get("saved", 0)

    if total_saved_decisions == 0:
        return DecisionMemoryOut(
            status="no_history",
            summary=DecisionMemorySummaryOut(
                total_saved_decisions=0,
                acted_on_count=0,
                dismissed_count=0,
                unresolved_count=0,
                earliest_decision_at=None,
                latest_decision_at=None,
                most_used_decision_types=[],
            ),
            follow_through=DecisionMemoryFollowThroughOut(
                eligible_decisions=0,
                acted_on_count=0,
                follow_through_rate=None,
                outcome_eligible_decisions=0,
                outcome_tracked_decisions=0,
                outcome_tracking_rate=None,
            ),
            outcomes=DecisionMemoryOutcomeSummaryOut(
                total_outcome_checks=0,
                directional_observations=0,
                favorable_count=0,
                unfavorable_count=0,
                unchanged_count=0,
                most_frequent_metric_paths=[],
            ),
            decision_types=[],
            recent_patterns=[],
            needs_follow_up_count=0,
        )

    calibration = decision_calibration_service.get_decision_calibration(
        db, user_id
    )
    calibration_by_type = {
        entry.decision_type: entry for entry in calibration.decision_types
    }
    review_queue = decision_review_service.build_review_queue(db, user_id)

    most_used_decision_types = [
        decision_type
        for decision_type, _count in sorted(
            saved_count_by_type.items(),
            key=lambda item: (-item[1], item[0]),
        )[:_MOST_USED_TYPES_LIMIT]
    ]

    eligible_decisions = acted_on_count + dismissed_count

    decision_types_out = [
        DecisionMemoryTypeBreakdownOut(
            decision_type=decision_type,
            saved_count=saved_count_by_type[decision_type],
            acted_on_count=acted_on_count_by_type.get(decision_type, 0),
            outcome_check_count=(
                calibration_by_type[decision_type].outcome_checks
                if decision_type in calibration_by_type
                else 0
            ),
            directional_observation_count=(
                calibration_by_type[decision_type].directional_observations
                if decision_type in calibration_by_type
                else 0
            ),
            calibration_label=(
                calibration_by_type[decision_type].calibration_label
                if decision_type in calibration_by_type
                else "insufficient_data"
            ),
        )
        for decision_type in sorted(saved_count_by_type)
    ]

    # Scoped to the last _RECENT_PATTERN_WINDOW_DAYS only -- a single
    # extra bounded aggregate query, mirroring the existing type+status
    # group-by above but with a `created_at` cutoff, so "recent
    # patterns" is never derived from all-time counts.
    recent_type_status_rows = db.execute(
        select(
            SavedDecision.decision_type,
            SavedDecision.status,
            func.count(SavedDecision.id),
        )
        .where(
            SavedDecision.user_id == user_id,
            SavedDecision.created_at >= recent_cutoff,
        )
        .group_by(SavedDecision.decision_type, SavedDecision.status)
    ).all()

    recent_saved_count_by_type: dict[str, int] = {}
    recent_unresolved_count = 0
    for decision_type, status, count in recent_type_status_rows:
        recent_saved_count_by_type[decision_type] = (
            recent_saved_count_by_type.get(decision_type, 0) + count
        )
        if status == "saved":
            recent_unresolved_count += count

    recent_patterns: list[DecisionMemoryPatternOut] = []
    for decision_type in sorted(
        recent_saved_count_by_type,
        key=lambda dt: -recent_saved_count_by_type[dt],
    ):
        count = recent_saved_count_by_type[decision_type]
        if count >= _REPEATED_TYPE_PATTERN_MIN_COUNT:
            recent_patterns.append(
                DecisionMemoryPatternOut(
                    text=(
                        f"Repeated {_type_label(decision_type)} analysis "
                        f"in the last {_RECENT_PATTERN_WINDOW_DAYS} days "
                        f"-- {count} saved decisions."
                    ),
                    decision_type=decision_type,
                    count=count,
                )
            )

    if recent_unresolved_count >= _UNRESOLVED_PATTERN_MIN_COUNT:
        recent_patterns.append(
            DecisionMemoryPatternOut(
                text=(
                    f"{recent_unresolved_count} decisions saved in the "
                    f"last {_RECENT_PATTERN_WINDOW_DAYS} days are still "
                    "unresolved -- tell Discero whether you acted on "
                    "them."
                ),
                count=recent_unresolved_count,
            )
        )

    return DecisionMemoryOut(
        status="available",
        summary=DecisionMemorySummaryOut(
            total_saved_decisions=total_saved_decisions,
            acted_on_count=acted_on_count,
            dismissed_count=dismissed_count,
            unresolved_count=unresolved_count,
            earliest_decision_at=earliest_at,
            latest_decision_at=latest_at,
            most_used_decision_types=most_used_decision_types,
        ),
        follow_through=DecisionMemoryFollowThroughOut(
            eligible_decisions=eligible_decisions,
            acted_on_count=acted_on_count,
            follow_through_rate=_rate(acted_on_count, eligible_decisions),
            outcome_eligible_decisions=acted_on_count,
            outcome_tracked_decisions=calibration.tracked_decisions,
            outcome_tracking_rate=_rate(
                calibration.tracked_decisions, acted_on_count
            ),
        ),
        outcomes=DecisionMemoryOutcomeSummaryOut(
            total_outcome_checks=calibration.outcome_checks,
            directional_observations=calibration.directional_metrics_compared,
            favorable_count=calibration.favorable_count,
            unfavorable_count=calibration.unfavorable_count,
            unchanged_count=calibration.unchanged_count,
            most_frequent_metric_paths=[
                group.path
                for group in calibration.metric_groups[
                    :_MOST_FREQUENT_METRICS_LIMIT
                ]
            ],
        ),
        decision_types=decision_types_out,
        recent_patterns=recent_patterns,
        needs_follow_up_count=len(review_queue),
    )
