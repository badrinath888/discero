"""Decision Calibration 1.0.

A deterministic read-model over ALREADY-PERSISTED DecisionOutcome rows
(see app/services/decision_outcome_service.py). It never re-runs a
financial simulation, never mutates outcome history, and never accepts
client-supplied numbers -- every count and delta here is recomputed
from `comparison_snapshot["metrics"]`, which was itself built
server-side when the outcome was evaluated.

Bound: only the `_MAX_CALIBRATION_OUTCOMES` most recently evaluated
outcome rows for a user are considered (newest first). This keeps the
aggregation to a single bounded query + one Python pass regardless of
how long a user has been tracking decisions, matching the per-decision
`_MAX_LISTED_OUTCOMES` bound already used by decision_outcome_service.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DecisionOutcome, SavedDecision
from app.schemas import (
    CalibrationLabel,
    DecisionCalibrationMetricGroupOut,
    DecisionCalibrationOut,
    DecisionCalibrationTypeBreakdownOut,
)

_MAX_CALIBRATION_OUTCOMES = 500
_MAX_METRIC_GROUPS = 20

_MIN_DIRECTIONAL_OBSERVATIONS = 3
_MIN_TRACKED_DECISIONS = 2
_RATE_THRESHOLD = 0.65

# Direction is classified from the metric PATH alone -- never from its
# value -- so the same path always means the same thing regardless of
# which decision produced it. Deliberately narrow: an unmatched path
# is left "unknown" rather than guessed, per the "if uncertain, mark
# direction unknown" rule.
_HIGHER_IS_BETTER_SUBSTRINGS = (
    "safe_to_spend",
    "buffer",
    "resilience",
    "confidence",
    "remaining_headroom",
    "liquid_balance",
)

_LOWER_IS_BETTER_SUBSTRINGS = (
    "shortfall",
    "deficit",
    # Covers delay_days, delay_months, estimated_delay_months,
    # projected_delay_months, etc. -- a delay of any unit is always
    # worse, never better.
    "delay",
)

_LOWER_IS_BETTER_EXACT_LEAVES = {
    "risk_score",
}

_INDEX_SUFFIX = re.compile(r"\[\d+\]$")


def _leaf_name(path: str) -> str:
    """The final path segment, with any trailing "[N]" list index
    stripped, e.g. "goal_impacts[0].delay_months" -> "delay_months"."""
    segment = path.rsplit(".", 1)[-1]
    return _INDEX_SUFFIX.sub("", segment)


def _classify_unit(path: str) -> str:
    leaf = _leaf_name(path)

    if leaf.endswith("_cents"):
        return "currency"
    if "confidence" in leaf:
        return "score"
    if "percent" in leaf:
        return "percentage"
    if "days" in leaf:
        return "days"
    return "numeric"


def _classify_direction(path: str) -> str:
    leaf = _leaf_name(path)

    if leaf in _LOWER_IS_BETTER_EXACT_LEAVES:
        return "lower_is_better"

    # A required/remaining funding gap: smaller is always better.
    # Restricted to the "gap" family explicitly called out in the
    # spec, not a bare "gap" substring, to avoid misclassifying an
    # unrelated field that happens to contain "gap".
    if leaf.endswith("gap_cents") or "monthly_gap" in leaf:
        return "lower_is_better"

    for token in _LOWER_IS_BETTER_SUBSTRINGS:
        if token in leaf:
            return "lower_is_better"

    for token in _HIGHER_IS_BETTER_SUBSTRINGS:
        if token in leaf:
            return "higher_is_better"

    return "unknown"


def _directional_outcome(direction: str, delta: float) -> str | None:
    if direction == "higher_is_better":
        if delta > 0:
            return "favorable"
        if delta < 0:
            return "unfavorable"
        return "unchanged"

    if direction == "lower_is_better":
        if delta < 0:
            return "favorable"
        if delta > 0:
            return "unfavorable"
        return "unchanged"

    return None


class _MetricAccumulator:
    __slots__ = (
        "observations",
        "sum_signed_delta",
        "sum_absolute_delta",
        "latest_delta",
        "latest_delta_set",
        "favorable",
        "unfavorable",
        "unchanged",
    )

    def __init__(self) -> None:
        self.observations = 0
        self.sum_signed_delta = 0.0
        self.sum_absolute_delta = 0.0
        self.latest_delta: float | None = None
        self.latest_delta_set = False
        self.favorable = 0
        self.unfavorable = 0
        self.unchanged = 0


class _DirectionalTally:
    __slots__ = ("favorable", "unfavorable", "unchanged", "tracked_decisions")

    def __init__(self) -> None:
        self.favorable = 0
        self.unfavorable = 0
        self.unchanged = 0
        self.tracked_decisions: set[int] = set()

    @property
    def directional_total(self) -> int:
        return self.favorable + self.unfavorable + self.unchanged

    @property
    def favorable_rate(self) -> float | None:
        total = self.directional_total
        return self.favorable / total if total > 0 else None

    def label(self) -> CalibrationLabel:
        return _calibration_label(
            favorable=self.favorable,
            unfavorable=self.unfavorable,
            unchanged=self.unchanged,
            tracked_decisions=len(self.tracked_decisions),
        )


def _calibration_label(
    *,
    favorable: int,
    unfavorable: int,
    unchanged: int,
    tracked_decisions: int,
) -> CalibrationLabel:
    total = favorable + unfavorable + unchanged

    if total < _MIN_DIRECTIONAL_OBSERVATIONS or tracked_decisions < _MIN_TRACKED_DECISIONS:
        return "insufficient_data"

    favorable_rate = favorable / total
    unfavorable_rate = unfavorable / total

    if favorable_rate >= _RATE_THRESHOLD:
        return "mostly_conservative"
    if unfavorable_rate >= _RATE_THRESHOLD:
        return "mostly_optimistic"
    return "balanced"


def _iter_numeric_metrics(comparison_snapshot: Any) -> list[dict]:
    if not isinstance(comparison_snapshot, dict):
        return []

    metrics = comparison_snapshot.get("metrics")
    if not isinstance(metrics, list):
        return []

    return [
        metric
        for metric in metrics
        if isinstance(metric, dict)
        and metric.get("change_type") == "numeric"
        and metric.get("delta") is not None
    ]


def get_decision_calibration(
    db: Session,
    user_id: int,
) -> DecisionCalibrationOut:
    rows = db.execute(
        select(DecisionOutcome, SavedDecision.decision_type)
        .join(SavedDecision, DecisionOutcome.decision_id == SavedDecision.id)
        .where(
            DecisionOutcome.user_id == user_id,
            SavedDecision.user_id == user_id,
        )
        .order_by(
            DecisionOutcome.evaluated_at.desc(),
            DecisionOutcome.id.desc(),
        )
        .limit(_MAX_CALIBRATION_OUTCOMES)
    ).all()

    tracked_decision_ids: set[int] = set()
    outcome_checks = 0
    numeric_metrics_compared = 0
    changed_numeric_metrics = 0

    overall = _DirectionalTally()
    by_type: dict[str, _DirectionalTally] = {}
    outcome_checks_by_type: dict[str, int] = {}
    metric_groups: dict[str, _MetricAccumulator] = {}

    for outcome, decision_type in rows:
        outcome_checks += 1
        tracked_decision_ids.add(outcome.decision_id)

        type_tally = by_type.setdefault(decision_type, _DirectionalTally())
        type_tally.tracked_decisions.add(outcome.decision_id)
        outcome_checks_by_type[decision_type] = (
            outcome_checks_by_type.get(decision_type, 0) + 1
        )

        for metric in _iter_numeric_metrics(outcome.comparison_snapshot):
            path = metric.get("path")
            delta = metric.get("delta")
            before = metric.get("before")
            current = metric.get("current")

            if not isinstance(path, str) or not isinstance(delta, (int, float)):
                continue

            numeric_metrics_compared += 1
            if before != current:
                changed_numeric_metrics += 1

            agg = metric_groups.setdefault(path, _MetricAccumulator())
            agg.observations += 1
            agg.sum_signed_delta += delta
            agg.sum_absolute_delta += abs(delta)
            if not agg.latest_delta_set:
                agg.latest_delta = delta
                agg.latest_delta_set = True

            direction = _classify_direction(path)
            outcome_kind = _directional_outcome(direction, delta)

            if outcome_kind == "favorable":
                agg.favorable += 1
                overall.favorable += 1
                type_tally.favorable += 1
            elif outcome_kind == "unfavorable":
                agg.unfavorable += 1
                overall.unfavorable += 1
                type_tally.unfavorable += 1
            elif outcome_kind == "unchanged":
                agg.unchanged += 1
                overall.unchanged += 1
                type_tally.unchanged += 1

    overall.tracked_decisions = tracked_decision_ids

    sorted_paths = sorted(
        metric_groups.keys(),
        key=lambda path: (-metric_groups[path].observations, path),
    )[:_MAX_METRIC_GROUPS]

    metric_group_out = [
        DecisionCalibrationMetricGroupOut(
            path=path,
            unit=_classify_unit(path),
            direction=_classify_direction(path),
            observations=metric_groups[path].observations,
            mean_signed_delta=(
                metric_groups[path].sum_signed_delta
                / metric_groups[path].observations
            ),
            mean_absolute_delta=(
                metric_groups[path].sum_absolute_delta
                / metric_groups[path].observations
            ),
            latest_delta=metric_groups[path].latest_delta,
            favorable_count=metric_groups[path].favorable,
            unfavorable_count=metric_groups[path].unfavorable,
            unchanged_count=metric_groups[path].unchanged,
        )
        for path in sorted_paths
    ]

    decision_type_out = [
        DecisionCalibrationTypeBreakdownOut(
            decision_type=decision_type,
            tracked_decisions=len(by_type[decision_type].tracked_decisions),
            outcome_checks=outcome_checks_by_type.get(decision_type, 0),
            directional_observations=by_type[decision_type].directional_total,
            favorable_count=by_type[decision_type].favorable,
            unfavorable_count=by_type[decision_type].unfavorable,
            unchanged_count=by_type[decision_type].unchanged,
            favorable_rate=by_type[decision_type].favorable_rate,
            calibration_label=by_type[decision_type].label(),
        )
        for decision_type in sorted(by_type.keys())
    ]

    return DecisionCalibrationOut(
        tracked_decisions=len(tracked_decision_ids),
        outcome_checks=outcome_checks,
        numeric_metrics_compared=numeric_metrics_compared,
        changed_numeric_metrics=changed_numeric_metrics,
        directional_metrics_compared=overall.directional_total,
        favorable_count=overall.favorable,
        unfavorable_count=overall.unfavorable,
        unchanged_count=overall.unchanged,
        favorable_rate=overall.favorable_rate,
        unfavorable_rate=(
            overall.unfavorable / overall.directional_total
            if overall.directional_total > 0
            else None
        ),
        calibration_label=overall.label(),
        metric_groups=metric_group_out,
        decision_types=decision_type_out,
    )
