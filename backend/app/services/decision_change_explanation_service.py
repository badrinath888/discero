"""Decision Change Explanation 1.0.

Answers "what changed since I originally analyzed this?" -- never "why
did this happen?" unless the cause is deterministically provable, which
this v1 never claims. Reuses decision_outcome_service's
build_comparison_snapshot (the exact same leaf-flattening and
type-safe comparison logic Decision Outcome Tracking already uses) so
a changed metric is never computed two different ways, and reuses
decision_calibration_service's unit/direction classification so a
metric's meaning never diverges between calibration and this feature.
Never performs arithmetic on booleans, dates, or arbitrary text, and
never labels an unknown-direction metric as good or bad.
"""

from __future__ import annotations

from app.schemas import (
    DecisionChangeExplanationMetricOut,
    DecisionChangeExplanationOut,
)
from app.services.decision_calibration_service import (
    classify_metric_direction,
    classify_metric_unit,
)
from app.services.decision_outcome_service import build_comparison_snapshot

_MAX_DISPLAYED_METRICS = 12

# Known headline financial metrics surface first, in this order, when
# present among the changed metrics -- everything else keeps the
# comparison's existing alphabetical-by-path order. Never reordered by
# magnitude, which would imply an importance judgment the underlying
# data doesn't support.
_PRIORITY_LEAVES = (
    "safe_to_spend_after_purchase_cents",
    "safe_to_spend_cents",
    "shortfall_cents",
    "shortfall_after_purchase_cents",
    "confidence_score",
    "resilience_score",
    "affordability_status",
    "recommended_timing",
    "recommended_option",
    "recommended_label",
    "risk_level",
)


def _leaf_name(path: str) -> str:
    return path.rsplit(".", 1)[-1].split("[")[0]


def _display_label(path: str) -> str:
    return _leaf_name(path).replace("_cents", "").replace("_", " ")


def _priority(path: str) -> int:
    try:
        return _PRIORITY_LEAVES.index(_leaf_name(path))
    except ValueError:
        return len(_PRIORITY_LEAVES)


def build_change_explanation(
    before_result: dict, current_result: dict
) -> DecisionChangeExplanationOut:
    comparison = build_comparison_snapshot(before_result, current_result)
    metrics = comparison["metrics"]

    changed = [
        metric for metric in metrics if metric["before"] != metric["current"]
    ]
    changed.sort(key=lambda metric: (_priority(metric["path"]), metric["path"]))
    displayed = changed[:_MAX_DISPLAYED_METRICS]

    changed_metrics_out = [
        DecisionChangeExplanationMetricOut(
            path=metric["path"],
            label=_display_label(metric["path"]),
            before=metric["before"],
            current=metric["current"],
            delta=metric["delta"],
            change_type=metric["change_type"],
            unit=(
                classify_metric_unit(metric["path"])
                if metric["change_type"] == "numeric"
                else None
            ),
            direction=(
                classify_metric_direction(metric["path"])
                if metric["change_type"] == "numeric"
                else None
            ),
        )
        for metric in displayed
    ]

    return DecisionChangeExplanationOut(
        changed_metrics=changed_metrics_out,
        total_changed_metric_count=len(changed),
        unchanged_metric_count=len(metrics) - len(changed),
    )
