"""Dashboard Decision Intelligence 1.0.

A small aggregate read-model composed entirely from already-existing
services -- Decision Review Queue, Decision Calibration, and the same
SavedDecision listing pattern decision_history_service uses. It never
runs a simulation, rerun, or portfolio analysis, and never duplicates
any of those services' own calculations.

Fixed query cost regardless of decision count: build_review_queue's own
two bounded queries, one bounded calibration aggregate query, and one
bounded "most recent decision" query -- four queries total, never N+1.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SavedDecision
from app.schemas import (
    DashboardCalibrationSummaryOut,
    DashboardDecisionIntelligenceOut,
    DashboardRecentDecisionOut,
    DashboardReviewQueueSummaryOut,
)
from app.services import decision_calibration_service, decision_review_service


def build_dashboard_intelligence(
    db: Session, user_id: int
) -> DashboardDecisionIntelligenceOut:
    review_queue = decision_review_service.build_review_queue(db, user_id)
    calibration = decision_calibration_service.get_decision_calibration(
        db, user_id
    )
    recent_decision = db.scalar(
        select(SavedDecision)
        .where(SavedDecision.user_id == user_id)
        .order_by(SavedDecision.created_at.desc())
        .limit(1)
    )

    return DashboardDecisionIntelligenceOut(
        review_queue=DashboardReviewQueueSummaryOut(
            count=len(review_queue),
            highest_priority=review_queue[0] if review_queue else None,
        ),
        calibration=DashboardCalibrationSummaryOut(
            label=calibration.calibration_label,
            tracked_decisions=calibration.tracked_decisions,
            outcome_checks=calibration.outcome_checks,
        ),
        recent_decision=(
            DashboardRecentDecisionOut(
                decision_id=recent_decision.id,
                decision_type=recent_decision.decision_type,
                title=recent_decision.title,
                status=recent_decision.status,
                created_at=recent_decision.created_at,
            )
            if recent_decision is not None
            else None
        ),
    )
