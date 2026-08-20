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
    BuyNowVsWaitRequest,
    DecisionPortfolioBaselineOut,
    DecisionPortfolioCombinedOut,
    DecisionPortfolioImpactOut,
    DecisionPortfolioItemRequest,
    DecisionPortfolioOut,
    DecisionPortfolioSelectionOut,
    DecisionType,
    FinancialStressTestRequest,
    GoalConflictDetectionRequest,
    MajorPurchaseSimulationRequest,
    SafeToSpendOut,
    SafeToSpendRequest,
    WhatIfComparisonRequest,
    WhatIfSimulationRequest,
)
from app.services.decision_goal_conflict_intelligence_service import (
    build_goal_conflict_intelligence,
)
from app.services.decision_history_service import _parse_input
from app.services.financial_stress_test_service import (
    _average_monthly_income_cents as _stress_average_monthly_income_cents,
)
from app.services.financial_stress_test_service import _resolve_stress_amount
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

# Every supported type is reconstructed from its persisted input into
# one of three linear representations (MajorPurchaseSimulationRequest,
# WhatIfSimulationRequest, or FinancialStressTestRequest) before
# combination -- never from result_snapshot. buy_now_vs_wait and
# what_if_comparison are alternative-branch types: an explicit variant
# selects exactly one persisted branch, which is then normalized into
# one of those same three shapes (see `_resolve_buy_now_vs_wait` /
# `_resolve_what_if_comparison`) rather than inventing a fourth
# combination rule. scenario_comparison stays unsupported -- nothing
# in SavedDecision records which option (if either) the user actually
# chose after saving, so including it would silently treat an
# unchosen alternative as a real financial event.
#
# buy_now_vs_wait's WAIT branch is a narrower case of that same
# problem: outside the portfolio, WAIT is only meaningfully different
# from BUY_NOW because `buy_now_vs_wait_service` re-runs
# `calculate_safe_to_spend` with `as_of` shifted forward to the wait
# date. A portfolio evaluates every selected decision against ONE
# shared baseline at ONE as_of (today) -- there is no per-decision
# baseline to shift, and shifting the whole portfolio's baseline for
# one decision's sake would misrepresent every other selected
# decision. So WAIT is accepted as a recognized variant but rejected
# with a structured error (see `_resolve_buy_now_vs_wait`) rather than
# silently reusing BUY_NOW's math under a "wait" label.
SUPPORTED_DECISION_TYPES: frozenset[str] = frozenset(
    {
        "major_purchase",
        "what_if",
        "stress_test",
        "buy_now_vs_wait",
        "what_if_comparison",
    }
)

_VARIANT_DECISION_TYPES: frozenset[str] = frozenset(
    {"buy_now_vs_wait", "what_if_comparison"}
)

# "wait" is recognized (rejected with `wait_branch_unsupported`, not
# `invalid_variant`) rather than omitted -- see the module docstring.
_BUY_NOW_VS_WAIT_VARIANTS: frozenset[str] = frozenset({"buy_now", "wait"})

# Positional, display-label-independent branch identifiers.
# WhatIfComparisonRequest.scenarios holds 2-3 entries; a scenario's
# variant key is always its index in that persisted list, never its
# label.
_WHAT_IF_COMPARISON_OPTION_KEYS: tuple[str, ...] = (
    "option_a",
    "option_b",
    "option_c",
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
    variants: dict[int, str] | None = None,
    as_of: date | None = None,
) -> DecisionPortfolioOut:
    calculation_date = as_of or date.today()
    variants = variants or {}

    _validate_selection(decision_ids)
    decisions = _load_decisions(db, user_id, decision_ids)
    _check_compatibility(decisions)
    payloads, variant_labels, warnings = _parse_all_inputs(
        decisions, variants
    )

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
        db,
        user_id,
        decisions,
        payloads,
        horizon_days=horizon_days,
        baseline=baseline,
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
                variant=variant_labels.get(decision.id, (None, None))[0],
                variant_label=variant_labels.get(
                    decision.id, (None, None)
                )[1],
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
        goal_conflict_intelligence=build_goal_conflict_intelligence(
            goal_impacts
        ),
        conflicts=conflicts,
        warnings=[*baseline.warnings, *warnings],
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


_ResolvedPayload = (
    MajorPurchaseSimulationRequest
    | WhatIfSimulationRequest
    | FinancialStressTestRequest
)


def _resolve_buy_now_vs_wait(
    decision: SavedDecision,
    payload: BuyNowVsWaitRequest,
    variant: str | None,
) -> tuple[MajorPurchaseSimulationRequest, str, str]:
    if variant is None:
        raise DecisionPortfolioValidationError(
            "buy_now_vs_wait decisions require an explicit variant "
            "('buy_now') before they can be added to a portfolio",
            details={
                "reason": "variant_required",
                "decision_id": decision.id,
            },
        )

    if variant not in _BUY_NOW_VS_WAIT_VARIANTS:
        raise DecisionPortfolioValidationError(
            "unrecognized variant for this decision",
            details={
                "reason": "invalid_variant",
                "decision_id": decision.id,
            },
        )

    if variant == "wait":
        # WAIT is a recognized branch of this decision, not a bad
        # input -- it is rejected because the portfolio has no way to
        # honor it faithfully. Outside the portfolio, WAIT means
        # "evaluate safe-to-spend as of the wait date"; inside the
        # portfolio there is only one shared as_of (today) for every
        # selected decision, so a purchase dated for the wait date
        # would land against today's baseline with no financial
        # difference from BUY_NOW -- a real date presented as a real
        # calculation while actually being identical to BUY_NOW in
        # every number that matters.
        raise DecisionPortfolioValidationError(
            "the wait branch of a buy-now-vs-wait decision can't be "
            "evaluated in a portfolio: portfolio analysis uses one "
            "shared baseline as of today, and there is no time-aware "
            "baseline to project forward to the wait date. Add the "
            "buy_now branch instead, or evaluate this decision on its "
            "own outside the portfolio.",
            details={
                "reason": "wait_branch_unsupported",
                "decision_id": decision.id,
            },
        )

    resolved = MajorPurchaseSimulationRequest(
        purchase_name=payload.purchase_name,
        purchase_amount_cents=payload.purchase_amount_cents,
        purchase_date=payload.buy_now_date,
        safety_reserve_cents=payload.safety_reserve_cents,
        essential_spending_cents=payload.essential_spending_cents,
        horizon_days=payload.horizon_days,
    )
    return resolved, variant, "Buy now"


def _resolve_what_if_comparison(
    decision: SavedDecision,
    payload: WhatIfComparisonRequest,
    variant: str | None,
) -> tuple[WhatIfSimulationRequest, str, str]:
    # Branch identity is the scenario's stable position
    # (option_a/option_b/option_c, matching the option_a/option_b
    # convention scenario_comparison already uses elsewhere), never
    # its display label. A label is user-authored text meant to be
    # shown, not a key to be matched on: two scenarios can share a
    # display label after an old decision was saved under a looser
    # schema, and a label long enough to be a reasonable scenario name
    # could still be defensible while an equally long variant string
    # is not. Positional keys sidestep both.
    if variant is None:
        raise DecisionPortfolioValidationError(
            "what_if_comparison decisions require an explicit variant "
            "('option_a', 'option_b', ...) before they can be added to "
            "a portfolio",
            details={
                "reason": "variant_required",
                "decision_id": decision.id,
            },
        )

    option_keys = _WHAT_IF_COMPARISON_OPTION_KEYS[: len(payload.scenarios)]

    if variant not in option_keys:
        raise DecisionPortfolioValidationError(
            "unrecognized variant for this decision",
            details={
                "reason": "invalid_variant",
                "decision_id": decision.id,
            },
        )

    scenario = payload.scenarios[option_keys.index(variant)]

    resolved = WhatIfSimulationRequest(
        scenario_type=scenario.scenario_type,
        scenario_name=scenario.label,
        amount_cents=scenario.amount_cents,
        effective_date=scenario.effective_date,
        monthly_amount_change_cents=scenario.monthly_amount_change_cents,
        monthly_income_loss_cents=scenario.monthly_income_loss_cents,
        duration_months=scenario.duration_months,
        safety_reserve_cents=payload.safety_reserve_cents,
        essential_spending_cents=payload.essential_spending_cents,
        horizon_days=payload.horizon_days,
    )
    return resolved, variant, scenario.label


def _parse_all_inputs(
    decisions: list[SavedDecision],
    variants: dict[int, str],
) -> tuple[list[_ResolvedPayload], dict[int, tuple[str, str]], list[str]]:
    payloads: list[_ResolvedPayload] = []
    variant_labels: dict[int, tuple[str, str]] = {}
    warnings: list[str] = []

    for decision in decisions:
        try:
            raw_payload = _parse_input(
                decision.decision_type, decision.input_snapshot
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

        variant = variants.get(decision.id)

        if decision.decision_type not in _VARIANT_DECISION_TYPES:
            if variant is not None:
                raise DecisionPortfolioValidationError(
                    "a branch variant was provided for a decision that "
                    "does not use one",
                    details={
                        "reason": "invalid_variant",
                        "decision_id": decision.id,
                    },
                )
            payloads.append(raw_payload)
            continue

        if decision.decision_type == "buy_now_vs_wait":
            resolved, variant_key, variant_label = _resolve_buy_now_vs_wait(
                decision, raw_payload, variant
            )
        else:
            resolved, variant_key, variant_label = _resolve_what_if_comparison(
                decision, raw_payload, variant
            )

        payloads.append(resolved)
        variant_labels[decision.id] = (variant_key, variant_label)

    return payloads, variant_labels, warnings


def _build_adjustments(
    db: Session,
    user_id: int,
    decisions: list[SavedDecision],
    payloads: list[_ResolvedPayload],
    *,
    horizon_days: int,
    baseline: SafeToSpendOut,
) -> list[_PortfolioAdjustment]:
    adjustments: list[_PortfolioAdjustment] = []
    average_monthly_income_cents: int | None = None

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
        elif isinstance(payload, FinancialStressTestRequest):
            if (
                payload.event_date < baseline.as_of
                or payload.event_date > baseline.through_date
            ):
                raise DecisionPortfolioValidationError(
                    "one or more selected decisions no longer fit the "
                    "combined evaluation horizon",
                    details={
                        "reason": "event_date_out_of_horizon",
                        "decision_id": decision.id,
                    },
                )

            if average_monthly_income_cents is None:
                average_monthly_income_cents = (
                    _stress_average_monthly_income_cents(
                        db, user_id, baseline.as_of
                    )
                )

            try:
                cost_delta_cents, monthly_capacity_delta_cents = (
                    _resolve_stress_amount(
                        payload,
                        average_monthly_income_cents=(
                            average_monthly_income_cents
                        ),
                        recurring_obligations_cents=(
                            baseline.breakdown.upcoming_obligations_cents
                        ),
                    )
                )
            except ValueError as exc:
                raise DecisionPortfolioValidationError(
                    "one or more selected decisions could not be "
                    "evaluated against current financial data",
                    details={
                        "reason": "stress_amount_unresolvable",
                        "decision_id": decision.id,
                    },
                ) from exc
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
