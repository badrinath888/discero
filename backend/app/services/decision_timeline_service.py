"""Decision Timeline 1.0.

Persisted-only chronological record for a single saved decision --
never a fabricated lifecycle timestamp. `decision_saved` comes from
SavedDecision.created_at, `decision_acted_on` from acted_on_at (only
when set), and one `outcome_checked` event per persisted DecisionOutcome
row via evaluated_at. There is no persisted `dismissed_at` column, so a
dismissed decision surfaces only via `current_status` -- never a
synthesized dismissal event.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DecisionOutcome
from app.schemas import DecisionTimelineEventOut, DecisionTimelineOut
from app.services.decision_history_service import get_decision

_MAX_TIMELINE_OUTCOMES = 200


def build_decision_timeline(
    db: Session, user_id: int, decision_id: int
) -> DecisionTimelineOut | None:
    decision = get_decision(db, user_id, decision_id)

    if decision is None:
        return None

    events: list[DecisionTimelineEventOut] = [
        DecisionTimelineEventOut(
            event_type="decision_saved",
            occurred_at=decision.created_at,
        )
    ]

    if decision.acted_on_at is not None:
        events.append(
            DecisionTimelineEventOut(
                event_type="decision_acted_on",
                occurred_at=decision.acted_on_at,
            )
        )

    outcome_rows = db.execute(
        select(
            DecisionOutcome.id,
            DecisionOutcome.evaluated_at,
            DecisionOutcome.comparison_snapshot,
        )
        .where(
            DecisionOutcome.decision_id == decision_id,
            DecisionOutcome.user_id == user_id,
        )
        .limit(_MAX_TIMELINE_OUTCOMES)
    ).all()

    for outcome_id, evaluated_at, comparison_snapshot in outcome_rows:
        changed = (
            comparison_snapshot.get("changed")
            if isinstance(comparison_snapshot, dict)
            else None
        )
        events.append(
            DecisionTimelineEventOut(
                event_type="outcome_checked",
                occurred_at=evaluated_at,
                outcome_id=outcome_id,
                changed=changed if isinstance(changed, bool) else None,
            )
        )

    events.sort(key=lambda event: event.occurred_at)

    return DecisionTimelineOut(
        decision_id=decision.id,
        decision_type=decision.decision_type,
        title=decision.title,
        current_status=decision.status,
        events=events,
    )
