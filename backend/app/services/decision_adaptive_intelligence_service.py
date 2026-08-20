"""Adaptive Decision Intelligence 1.0.

A pure adapter over the already-computed Decision Calibration output
(see app/services/decision_calibration_service.py) -- it never queries
DecisionOutcome/SavedDecision itself and never recomputes calibration's
aggregation, so a calibration figure can never diverge between the two
features. V1 is CONTEXTUAL intelligence only: narrative text describing
how tracked outcomes have compared with original estimates, never a
change to any deterministic financial calculation, and never an LLM
call.
"""

from __future__ import annotations

from app.schemas import (
    AdaptiveIntelligenceMetricPatternOut,
    CalibrationLabel,
    DecisionAdaptiveIntelligenceOut,
    DecisionCalibrationOut,
)

# A metric group with a single observation can't support a "pattern"
# claim -- mirrors the calibration label's own minimum-evidence gating
# (see _MIN_DIRECTIONAL_OBSERVATIONS in decision_calibration_service).
_MIN_METRIC_OBSERVATIONS = 2
_MAX_METRIC_PATTERNS = 5

_NARRATIVE: dict[CalibrationLabel, str] = {
    "mostly_conservative": (
        "Your tracked outcomes have generally been more favorable than "
        "the original estimates."
    ),
    "mostly_optimistic": (
        "Your tracked outcomes have generally been less favorable than "
        "the original estimates."
    ),
    "balanced": (
        "Your tracked outcomes have been mixed relative to the original "
        "estimates."
    ),
    "insufficient_data": (
        "More tracked outcomes are needed before Discero can identify a "
        "reliable historical pattern."
    ),
}


def build_adaptive_intelligence(
    calibration: DecisionCalibrationOut,
) -> DecisionAdaptiveIntelligenceOut:
    status = (
        "insufficient_data"
        if calibration.calibration_label == "insufficient_data"
        else "available"
    )

    metric_patterns = [
        AdaptiveIntelligenceMetricPatternOut(
            path=group.path,
            unit=group.unit,
            direction=group.direction,
            observations=group.observations,
            mean_signed_delta=group.mean_signed_delta,
        )
        for group in calibration.metric_groups
        if group.observations >= _MIN_METRIC_OBSERVATIONS
    ][:_MAX_METRIC_PATTERNS]

    return DecisionAdaptiveIntelligenceOut(
        status=status,
        calibration_label=calibration.calibration_label,
        tracked_decisions=calibration.tracked_decisions,
        outcome_checks=calibration.outcome_checks,
        directional_observations=calibration.directional_metrics_compared,
        favorable_rate=calibration.favorable_rate,
        unfavorable_rate=calibration.unfavorable_rate,
        narrative=_NARRATIVE[calibration.calibration_label],
        metric_patterns=metric_patterns,
    )
