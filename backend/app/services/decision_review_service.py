"""Decision Review Queue 1.0.

A deterministic read-model over already-persisted SavedDecision and
DecisionOutcome state -- never an LLM call, background job, or
notification. Every item is recomputed from `status`, `created_at`,
`acted_on_at`, and the same grouped outcome aggregate
(`_attach_outcome_metadata`) decision_history_service already uses for
`outcome_count`/`latest_outcome_at`, so listing the queue never issues
one query per decision.

Dismissed decisions are never eligible -- checked implicitly by
scoping the base query to `status != "dismissed"`.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SavedDecision
from app.schemas import DecisionReviewAction, DecisionReviewQueueItemOut, DecisionReviewReason
from app.services.decision_history_service import _attach_outcome_metadata

_SAVED_UNRESOLVED_MIN_AGE_DAYS = 7
_ACTED_ON_NEVER_CHECKED_MIN_AGE_DAYS = 7
_ACTED_ON_RECHECK_DUE_MIN_AGE_DAYS = 30

_REASON_PRIORITY: dict[DecisionReviewReason, int] = {
    "acted_on_never_checked": 0,
    "acted_on_recheck_due": 1,
    "saved_unresolved": 2,
}

_RECOMMENDED_ACTION: dict[DecisionReviewReason, DecisionReviewAction] = {
    "saved_unresolved": "mark_acted_or_dismiss",
    "acted_on_never_checked": "check_outcome",
    "acted_on_recheck_due": "recheck_outcome",
}


def _as_aware_utc(value: datetime) -> datetime:
    """SQLite (used in tests) drops tzinfo on readback even though the
    column is declared `DateTime(timezone=True)` and every write goes
    through `_utcnow()` -- the wall-clock value is always already UTC,
    so a naive value is annotated rather than converted."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _age_days(reference: datetime, now: datetime) -> int:
    return (now - _as_aware_utc(reference)).days


def _reason_text(reason: DecisionReviewReason, age_days: int) -> str:
    if reason == "saved_unresolved":
        return (
            f"Saved {age_days} days ago. Tell Discero whether you acted "
            "on this decision."
        )
    if reason == "acted_on_never_checked":
        return (
            f"Acted on {age_days} days ago. Check how this decision "
            "compares with your finances today."
        )
    return (
        f"Last checked {age_days} days ago. Review this decision again "
        "with current data."
    )


def _build_item(
    decision: SavedDecision,
    *,
    reason: DecisionReviewReason,
    age_days: int,
) -> DecisionReviewQueueItemOut:
    return DecisionReviewQueueItemOut(
        decision_id=decision.id,
        decision_type=decision.decision_type,
        title=decision.title,
        status=decision.status,
        created_at=decision.created_at,
        acted_on_at=decision.acted_on_at,
        outcome_count=decision.outcome_count,
        latest_outcome_at=decision.latest_outcome_at,
        review_reason=reason,
        review_reason_text=_reason_text(reason, age_days),
        age_days=age_days,
        recommended_action=_RECOMMENDED_ACTION[reason],
    )


def _review_item(
    decision: SavedDecision, now: datetime
) -> tuple[DecisionReviewQueueItemOut, datetime] | None:
    """Returns (item, relevant_event_timestamp) if the decision belongs
    in the queue, otherwise None. relevant_event_timestamp drives the
    "oldest relevant event first" tie-break within a reason."""
    if decision.status == "saved":
        age_days = _age_days(decision.created_at, now)
        if age_days >= _SAVED_UNRESOLVED_MIN_AGE_DAYS:
            item = _build_item(
                decision, reason="saved_unresolved", age_days=age_days
            )
            return item, decision.created_at
        return None

    if decision.status == "acted_on":
        if decision.acted_on_at is None:
            return None

        if decision.outcome_count == 0:
            age_days = _age_days(decision.acted_on_at, now)
            if age_days >= _ACTED_ON_NEVER_CHECKED_MIN_AGE_DAYS:
                item = _build_item(
                    decision,
                    reason="acted_on_never_checked",
                    age_days=age_days,
                )
                return item, decision.acted_on_at
            return None

        if decision.latest_outcome_at is None:
            return None

        age_days = _age_days(decision.latest_outcome_at, now)
        if age_days >= _ACTED_ON_RECHECK_DUE_MIN_AGE_DAYS:
            item = _build_item(
                decision, reason="acted_on_recheck_due", age_days=age_days
            )
            return item, decision.latest_outcome_at
        return None

    return None


def build_review_queue(
    db: Session,
    user_id: int,
    *,
    now: datetime | None = None,
) -> list[DecisionReviewQueueItemOut]:
    """Returns the deterministic review queue for a user, sorted by
    urgency: acted_on_never_checked, then acted_on_recheck_due, then
    saved_unresolved -- oldest relevant event first within a reason,
    decision ID as the final stable tie-break.

    `now` is injectable so review-age logic is directly testable
    without depending on wall-clock time.
    """
    reference_time = now or datetime.now(timezone.utc)

    decisions = list(
        db.scalars(
            select(SavedDecision).where(
                SavedDecision.user_id == user_id,
                SavedDecision.status != "dismissed",
            )
        ).all()
    )
    decisions = _attach_outcome_metadata(db, user_id, decisions)

    entries: list[tuple[DecisionReviewQueueItemOut, datetime]] = []
    for decision in decisions:
        entry = _review_item(decision, reference_time)
        if entry is not None:
            entries.append(entry)

    entries.sort(
        key=lambda entry: (
            _REASON_PRIORITY[entry[0].review_reason],
            entry[1],
            entry[0].decision_id,
        )
    )

    return [item for item, _relevant_event in entries]
