"""Decision Portfolio Intelligence.

Evaluates several compatible saved decisions together as ONE combined
deterministic scenario against a single financial baseline -- never by
arithmetically summing each decision's independently-calculated
result_snapshot (each was computed against its own baseline, so
summing final numbers would double count or silently understate a
compounding shortfall).

Each supported decision type already reduces to a linear cost delta
against `calculate_safe_to_spend`'s raw (pre-clamp) total -- the same
representation `what_if_service`/`major_purchase_service` use. This
reuses that representation and sums every selected decision's delta
against ONE shared baseline's raw total BEFORE the single floor-at-
zero clamp that produces the final safe-to-spend figure, so an
existing shortfall from one decision correctly compounds with the
next rather than being silently understated by clamping each decision
independently first.

Saved decisions are always loaded server-side by id and ownership;
client-supplied input/result snapshots are never trusted. Each
input_snapshot is revalidated through the same schema used when the
decision was originally saved, via `decision_history_service._parse_
input`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SavedDecision
from app.schemas import (
    DecisionPortfolioBaselineOut,
    DecisionPortfolioCombinedOut,
    DecisionPortfolioImpactOut,
    DecisionPortfolioOut,
    DecisionPortfolioSelectionOut,
    DecisionType,
    GoalConflictDetectionRequest,
    MajorPurchaseSimulationRequest,
    SafeToSpendOut,
    SafeToSpendRequest,
    WhatIfSimulationRequest,
)
from app.services.decision_history_service import _parse_input
from app.services.goal_conflict_detection_service import detect_goal_conflicts
from app.services.goal_impact_service import calculate_goal_impacts
from app.services.safe_to_spend_service import (
    _DAYS_PER_MONTH,
    _determine_status,
    _get_projected_income_cents,
    calculate_safe_to_spend,
)
from app.services.what_if_service import _resolve_deltas, _validate_effective_date

_MIN_DECISIONS = 2
_MAX_DECISIONS = 5

# v1 supports only decision types whose saved input reduces to a
# single linear cash/capacity delta against the safe-to-spend
# baseline. Comparison/stress-test/buy-now-vs-wait types model two
# branches or a single shock rather than one adjustment, so folding
# them into one combined scenario would need a different combination
# rule -- deferred rather than silently reinterpreted.
SUPPORTED_DECISION_TYPES: frozenset[str] = frozenset(
    {"major_purchase", "what_if"}
)

_STATUS_MAP: dict[str, str] = {
    "safe": "comfortable",
    "limited": "tight",
    "negative": "high_risk",
}

# Contribution-level thresholds are a share of the portfolio's total
# negative (pressure-creating) impact, not an absolute cents amount,
# so the rule scales with the user's own finances instead of an
# arbitrary dollar figure. Boundaries are inclusive on the upper tier.
_HIGH_CONTRIBUTION_SHARE = 0.5
_MEDIUM_CONTRIBUTION_SHARE = 0.2


class DecisionPortfolioNotFoundError(Exception):
    """Raised when one or more selected decisions don't exist for this
    user. Deliberately indistinguishable from "belongs to another
    user" -- a saved decision is always loaded by id AND ownership
    together, never disclosing which case applies.
    """

    def __init__(self, message: str, *, missing_decision_ids: list[int]):
        super().__init__(message)
        self.missing_decision_ids = missing_decision_ids


class DecisionPortfolioValidationError(Exception):
    """Raised for a stable, structured 422: bad selection shape,
    incompatible decision lifecycle/type, or a legacy persisted input
    that no longer matches its decision type's schema.
    """

    def __init__(self, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.details = details or {}


@dataclass(frozen=True)
class _PortfolioAdjustment:
    source_decision_id: int
    decision_type: DecisionType
    title: str
    # Positive reduces the combined raw safe-to-spend total; horizon-
    # prorated the same way what_if_service prorates a monthly change.
    cost_delta_cents: int
    # Unprorated monthly figure feeding combined goal-funding capacity,
    # same convention major_purchase_service/what_if_service use.
    monthly_capacity_delta_cents: int


def evaluate_decision_portfolio(
    db: Session,
    user_id: int,
    decision_ids: list[int],
    *,
    as_of: date | None = None,
) -> DecisionPortfolioOut:
    calculation_date = as_of or date.today()

    _validate_selection(decision_ids)
    decisions = _load_decisions(db, user_id, decision_ids)
    _check_compatibility(decisions)
    payloads = _parse_all_inputs(decisions)

    horizon_days = max(payload.horizon_days for payload in payloads)
    safety_reserve_cents = max(
        payload.safety_reserve_cents for payload in payloads
    )
    essential_spending_cents = max(
        payload.essential_spending_cents for payload in payloads
    )

    baseline = calculate_safe_to_spend(
        db,
        user_id,
        SafeToSpendRequest(
            safety_reserve_cents=safety_reserve_cents,
            essential_spending_cents=essential_spending_cents,
            horizon_days=horizon_days,
            include_projected_income=True,
            include_goal_reserve=True,
        ),
        as_of=calculation_date,
    )

    adjustments = _build_adjustments(
        decisions, payloads, horizon_days=horizon_days, baseline=baseline
    )

    baseline_raw_cents = (
        baseline.safe_to_spend_cents - baseline.shortfall_cents
    )
    total_cost_delta_cents = sum(
        adjustment.cost_delta_cents for adjustment in adjustments
    )
    combined_raw_cents = baseline_raw_cents - total_cost_delta_cents
    combined_safe_cents = max(combined_raw_cents, 0)
    combined_shortfall_cents = max(-combined_raw_cents, 0)

    average_monthly_income_cents = _get_projected_income_cents(
        db, user_id, calculation_date, _DAYS_PER_MONTH
    )
    baseline_monthly_capacity_cents = max(
        average_monthly_income_cents
        - baseline.breakdown.upcoming_obligations_cents,
        0,
    )
    # A one-time shortfall left after liquid funds are exhausted
    # competes with monthly goal funding the same way
    # major_purchase_service's adjusted_monthly_capacity_cents does,
    # generalized to the portfolio's combined shortfall.
    total_monthly_capacity_delta_cents = (
        sum(
            adjustment.monthly_capacity_delta_cents
            for adjustment in adjustments
        )
        + combined_shortfall_cents
    )
    adjusted_monthly_capacity_cents = max(
        baseline_monthly_capacity_cents
        - total_monthly_capacity_delta_cents,
        0,
    )

    goal_impacts = calculate_goal_impacts(
        db,
        user_id,
        baseline_monthly_capacity_cents=baseline_monthly_capacity_cents,
        adjusted_monthly_capacity_cents=adjusted_monthly_capacity_cents,
        as_of=calculation_date,
    )

    conflicts = detect_goal_conflicts(
        db,
        user_id,
        GoalConflictDetectionRequest(
            monthly_savings_capacity_cents=adjusted_monthly_capacity_cents
        ),
        as_of=calculation_date,
    )

    portfolio_status = _STATUS_MAP[
        _determine_status(
            combined_raw_cents, baseline.breakdown.liquid_balance_cents
        )
    ]

    decision_impacts = _rank_decision_impacts(
        adjustments, combined_raw_cents=combined_raw_cents
    )

    return DecisionPortfolioOut(
        as_of=calculation_date,
        selected_decisions=[
            DecisionPortfolioSelectionOut(
                decision_id=decision.id,
                decision_type=decision.decision_type,
                title=decision.title,
            )
            for decision in decisions
        ],
        baseline=DecisionPortfolioBaselineOut(
            safe_to_spend_cents=baseline.safe_to_spend_cents,
            confidence_score=baseline.confidence_score,
        ),
        combined=DecisionPortfolioCombinedOut(
            safe_to_spend_cents=combined_safe_cents,
            safe_to_spend_delta_cents=(
                combined_safe_cents - baseline.safe_to_spend_cents
            ),
            # Only deterministic hypothetical/committed inputs changed
            # -- the underlying obligation/balance data driving
            # confidence did not, so confidence is reported unchanged
            # rather than fabricating a delta (same convention
            # what_if_service uses).
            confidence_score=baseline.confidence_score,
            confidence_delta=0.0,
        ),
        portfolio_status=portfolio_status,
        decision_impacts=decision_impacts,
        goal_impacts=goal_impacts,
        conflicts=conflicts,
        warnings=list(baseline.warnings),
        assumptions=_build_assumptions(
            horizon_days=horizon_days,
            safety_reserve_cents=safety_reserve_cents,
            essential_spending_cents=essential_spending_cents,
        ),
    )


def _validate_selection(decision_ids: list[int]) -> None:
    if (
        len(decision_ids) < _MIN_DECISIONS
        or len(decision_ids) > _MAX_DECISIONS
    ):
        raise DecisionPortfolioValidationError(
            f"portfolio analysis requires between {_MIN_DECISIONS} and "
            f"{_MAX_DECISIONS} decisions",
            details={
                "reason": "invalid_selection_count",
                "decision_ids": decision_ids,
            },
        )

    if len(set(decision_ids)) != len(decision_ids):
        duplicates = sorted(
            {
                decision_id
                for decision_id in decision_ids
                if decision_ids.count(decision_id) > 1
            }
        )
        raise DecisionPortfolioValidationError(
            "decision_ids must be unique",
            details={
                "reason": "duplicate_decision_ids",
                "duplicate_decision_ids": duplicates,
            },
        )


def _load_decisions(
    db: Session, user_id: int, decision_ids: list[int]
) -> list[SavedDecision]:
    rows = list(
        db.scalars(
            select(SavedDecision).where(
                SavedDecision.user_id == user_id,
                SavedDecision.id.in_(decision_ids),
            )
        ).all()
    )

    found_ids = {row.id for row in rows}
    missing_ids = sorted(set(decision_ids) - found_ids)

    if missing_ids:
        raise DecisionPortfolioNotFoundError(
            "one or more selected decisions were not found",
            missing_decision_ids=missing_ids,
        )

    rows.sort(key=lambda row: row.id)
    return rows


def _check_compatibility(decisions: list[SavedDecision]) -> None:
    incompatible = []

    for decision in decisions:
        if decision.status == "dismissed":
            incompatible.append(
                {
                    "decision_id": decision.id,
                    "decision_type": decision.decision_type,
                    "reason": "dismissed",
                }
            )
        elif decision.decision_type not in SUPPORTED_DECISION_TYPES:
            incompatible.append(
                {
                    "decision_id": decision.id,
                    "decision_type": decision.decision_type,
                    "reason": "unsupported_type",
                }
            )

    if incompatible:
        raise DecisionPortfolioValidationError(
            "one or more selected decisions are not eligible for "
            "portfolio analysis",
            details={
                "reason": "incompatible_decisions",
                "incompatible_decisions": incompatible,
            },
        )


def _parse_all_inputs(
    decisions: list[SavedDecision],
) -> list[MajorPurchaseSimulationRequest | WhatIfSimulationRequest]:
    payloads: list[MajorPurchaseSimulationRequest | WhatIfSimulationRequest] = []

    for decision in decisions:
        try:
            payloads.append(
                _parse_input(decision.decision_type, decision.input_snapshot)
            )
        except ValueError as exc:
            raise DecisionPortfolioValidationError(
                "one or more selected decisions have a persisted input "
                "that no longer matches its decision type's schema",
                details={
                    "reason": "invalid_persisted_input",
                    "decision_id": decision.id,
                },
            ) from exc

    return payloads


def _build_adjustments(
    decisions: list[SavedDecision],
    payloads: list[MajorPurchaseSimulationRequest | WhatIfSimulationRequest],
    *,
    horizon_days: int,
    baseline: SafeToSpendOut,
) -> list[_PortfolioAdjustment]:
    adjustments: list[_PortfolioAdjustment] = []

    for decision, payload in zip(decisions, payloads):
        if isinstance(payload, MajorPurchaseSimulationRequest):
            if (
                payload.purchase_date < baseline.as_of
                or payload.purchase_date > baseline.through_date
            ):
                raise DecisionPortfolioValidationError(
                    "one or more selected decisions no longer fit the "
                    "combined evaluation horizon",
                    details={
                        "reason": "purchase_date_out_of_horizon",
                        "decision_id": decision.id,
                    },
                )

            cost_delta_cents = payload.purchase_amount_cents
            monthly_capacity_delta_cents = 0
        else:
            # Reconstructed with the portfolio's shared horizon so
            # monthly changes prorate against the same window the
            # combined baseline was evaluated over.
            scenario_payload = payload.model_copy(
                update={"horizon_days": horizon_days}
            )

            if scenario_payload.scenario_type == "one_time_expense":
                try:
                    _validate_effective_date(
                        scenario_payload.effective_date,
                        baseline.as_of,
                        baseline.through_date,
                    )
                except ValueError as exc:
                    raise DecisionPortfolioValidationError(
                        "one or more selected decisions no longer fit "
                        "the combined evaluation horizon",
                        details={
                            "reason": "effective_date_out_of_horizon",
                            "decision_id": decision.id,
                        },
                    ) from exc

            cost_delta_cents, monthly_capacity_delta_cents = (
                _resolve_deltas(scenario_payload)
            )

        adjustments.append(
            _PortfolioAdjustment(
                source_decision_id=decision.id,
                decision_type=decision.decision_type,
                title=decision.title,
                cost_delta_cents=cost_delta_cents,
                monthly_capacity_delta_cents=monthly_capacity_delta_cents,
            )
        )

    return adjustments


def _rank_decision_impacts(
    adjustments: list[_PortfolioAdjustment],
    *,
    combined_raw_cents: int,
) -> list[DecisionPortfolioImpactOut]:
    """Incremental impact per decision without repeating any database
    query: the full portfolio's raw (pre-clamp) total is already
    known, so "portfolio without decision i" is pure arithmetic --
    add decision i's cost delta back and re-clamp. Bounded by the
    5-decision maximum selection.
    """
    combined_safe_cents = max(combined_raw_cents, 0)

    scored: list[tuple[_PortfolioAdjustment, int]] = []

    for adjustment in adjustments:
        raw_without_cents = (
            combined_raw_cents + adjustment.cost_delta_cents
        )
        safe_without_cents = max(raw_without_cents, 0)
        incremental_impact_cents = combined_safe_cents - safe_without_cents
        scored.append((adjustment, incremental_impact_cents))

    # Most negative (biggest pressure) first; decision_id ascending
    # breaks ties deterministically.
    scored.sort(key=lambda item: (item[1], item[0].source_decision_id))

    total_negative_cents = sum(
        -impact for _, impact in scored if impact < 0
    )

    results: list[DecisionPortfolioImpactOut] = []

    for rank, (adjustment, impact) in enumerate(scored, start=1):
        results.append(
            DecisionPortfolioImpactOut(
                decision_id=adjustment.source_decision_id,
                title=adjustment.title,
                decision_type=adjustment.decision_type,
                incremental_safe_to_spend_impact_cents=impact,
                risk_rank=rank,
                contribution_level=_contribution_level(
                    impact, total_negative_cents
                ),
            )
        )

    return results


def _contribution_level(
    impact_cents: int, total_negative_cents: int
) -> str:
    if impact_cents >= 0 or total_negative_cents <= 0:
        return "low"

    share = -impact_cents / total_negative_cents

    if share >= _HIGH_CONTRIBUTION_SHARE:
        return "high"

    if share >= _MEDIUM_CONTRIBUTION_SHARE:
        return "medium"

    return "low"


def _build_assumptions(
    *,
    horizon_days: int,
    safety_reserve_cents: int,
    essential_spending_cents: int,
) -> list[str]:
    assumptions = [
        f"Combined evaluation uses a shared {horizon_days}-day "
        "horizon, the longest horizon among the selected decisions.",
    ]

    if safety_reserve_cents > 0 or essential_spending_cents > 0:
        assumptions.append(
            "The highest safety reserve and essential spending "
            "amounts among the selected decisions protect the "
            "combined baseline."
        )

    assumptions.append(
        "Confidence reflects current data quality and is not "
        "adjusted for these hypothetical scenario inputs."
    )

    return assumptions
