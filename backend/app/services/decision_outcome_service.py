"""Decision Outcome Tracking.

An outcome re-runs an acted-on decision's ORIGINAL saved input against
CURRENT deterministic data and stores a bounded, structured comparison
against the original result -- never a client-supplied "current"
result, and never a rewrite of the original saved result_snapshot.
Reuses the same deterministic dispatch (`_run`) and input
reconstruction (`_parse_input`) as decision_history_service so an
outcome's "current" figure is always a genuine recalculation.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DecisionOutcome
from app.schemas import (
    DecisionOutcomeComparisonMetric,
    DecisionOutcomeComparisonOut,
    DecisionOutcomeComparisonSummary,
)
from app.services.decision_history_service import _parse_input, _run, get_decision

_MAX_LISTED_OUTCOMES = 50
_MAX_COMPARISON_METRICS = 50
# Strings longer than this are treated as narrative/prose (an
# explanation, a reason, a caveat) and excluded from comparison --
# never fabricated into a fake "changed" metric.
_MAX_COMPARABLE_TEXT_LENGTH = 80


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    """Flattens persisted JSON into {leaf-path: scalar-value}.

    Only bool/int/float/str leaves are kept -- None and any other
    type are dropped, since they can't be safely/deterministically
    compared.
    """
    leaves: dict[str, Any] = {}

    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            leaves.update(_flatten(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            leaves.update(_flatten(item, f"{prefix}[{index}]"))
    elif isinstance(value, (bool, int, float, str)):
        leaves[prefix] = value

    return leaves


def _is_iso_date_or_datetime(value: str) -> bool:
    try:
        if len(value) == 10:
            date.fromisoformat(value)
        else:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _compare_leaf(
    path: str, before: Any, current: Any
) -> DecisionOutcomeComparisonMetric | None:
    # bool must be checked ahead of int (bool is an int subclass).
    if isinstance(before, bool) or isinstance(current, bool):
        if isinstance(before, bool) and isinstance(current, bool):
            return DecisionOutcomeComparisonMetric(
                path=path,
                before=before,
                current=current,
                delta=None,
                change_type="boolean",
            )
        return None

    if isinstance(before, (int, float)) and isinstance(current, (int, float)):
        return DecisionOutcomeComparisonMetric(
            path=path,
            before=before,
            current=current,
            delta=current - before,
            change_type="numeric",
        )

    if isinstance(before, str) and isinstance(current, str):
        if (
            len(before) > _MAX_COMPARABLE_TEXT_LENGTH
            or len(current) > _MAX_COMPARABLE_TEXT_LENGTH
        ):
            return None

        if _is_iso_date_or_datetime(before) and _is_iso_date_or_datetime(
            current
        ):
            return DecisionOutcomeComparisonMetric(
                path=path,
                before=before,
                current=current,
                delta=None,
                change_type="date",
            )

        return DecisionOutcomeComparisonMetric(
            path=path,
            before=before,
            current=current,
            delta=None,
            change_type="text",
        )

    # Mismatched/unsupported types -- never guess.
    return None


def build_comparison_snapshot(
    before_result: dict, current_result: dict
) -> dict:
    """Builds the bounded, deterministic comparison_snapshot dict.

    Only paths present in BOTH snapshots with a directly comparable
    scalar type are included. Ordering is alphabetical by path for
    determinism, and the metric count is capped so persisted payloads
    stay bounded regardless of how large a decision type's result
    schema is.
    """
    before_leaves = _flatten(before_result)
    current_leaves = _flatten(current_result)

    common_paths = sorted(set(before_leaves) & set(current_leaves))

    metrics: list[DecisionOutcomeComparisonMetric] = []
    for path in common_paths:
        metric = _compare_leaf(path, before_leaves[path], current_leaves[path])
        if metric is not None:
            metrics.append(metric)

    metrics = metrics[:_MAX_COMPARISON_METRICS]

    changed_count = sum(
        1 for metric in metrics if metric.before != metric.current
    )

    comparison = DecisionOutcomeComparisonOut(
        changed=changed_count > 0,
        metrics=metrics,
        summary=DecisionOutcomeComparisonSummary(
            metrics_compared=len(metrics),
            metrics_changed=changed_count,
        ),
    )

    return comparison.model_dump(mode="json")


def evaluate_decision_outcome(
    db: Session,
    user_id: int,
    decision_id: int,
    *,
    as_of: date | None = None,
) -> DecisionOutcome | None:
    """Re-runs an acted-on decision's original input against current
    data and persists the result as a new DecisionOutcome.

    Returns None if the decision doesn't exist (or isn't owned by
    user_id) -- the router turns that into a 404. Raises ValueError
    (a stable, non-sensitive domain message) if the decision hasn't
    been acted on yet.
    """
    decision = get_decision(db, user_id, decision_id)

    if decision is None:
        return None

    if decision.status != "acted_on":
        raise ValueError(
            "an outcome can only be evaluated for a decision that has "
            "been acted on"
        )

    calculation_date = as_of or date.today()
    payload = _parse_input(decision.decision_type, decision.input_snapshot)
    result = _run(
        db, user_id, decision.decision_type, payload, calculation_date
    )

    current_result_snapshot = result.model_dump(mode="json")
    comparison_snapshot = build_comparison_snapshot(
        decision.result_snapshot, current_result_snapshot
    )

    outcome = DecisionOutcome(
        decision_id=decision.id,
        user_id=user_id,
        evaluated_at=datetime.now(timezone.utc),
        current_result_snapshot=current_result_snapshot,
        comparison_snapshot=comparison_snapshot,
    )
    db.add(outcome)
    db.commit()
    db.refresh(outcome)

    return outcome


def list_decision_outcomes(
    db: Session,
    user_id: int,
    decision_id: int,
    *,
    limit: int = _MAX_LISTED_OUTCOMES,
) -> list[DecisionOutcome] | None:
    """Newest-first outcome history for a decision. Returns None if
    the decision doesn't exist (or isn't owned by user_id)."""
    decision = get_decision(db, user_id, decision_id)

    if decision is None:
        return None

    return list(
        db.scalars(
            select(DecisionOutcome)
            .where(
                DecisionOutcome.decision_id == decision_id,
                DecisionOutcome.user_id == user_id,
            )
            .order_by(
                DecisionOutcome.evaluated_at.desc(),
                DecisionOutcome.id.desc(),
            )
            .limit(limit)
        ).all()
    )
