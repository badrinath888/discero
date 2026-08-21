"""Saved Decision History.

A saved decision snapshots BOTH the inputs the user analyzed AND the
real deterministic result at that moment -- never just prose. Saving
and re-running both re-execute the actual deterministic service
server-side; a client-supplied "result" is never trusted or persisted
directly, so the stored snapshot is always a genuine calculation.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import DecisionOutcome, SavedDecision
from app.schemas import (
    BuyNowVsWaitRequest,
    DecisionLifecycleStatus,
    FinancialStressTestRequest,
    MajorPurchaseSimulationRequest,
    MultiStepScenarioPlanRequest,
    SaveDecisionRequest,
    ScenarioComparisonRequest,
    WhatIfComparisonRequest,
    WhatIfSimulationRequest,
)
from app.services.buy_now_vs_wait_service import evaluate_buy_now_vs_wait
from app.services.financial_stress_test_service import (
    run_financial_stress_test,
)
from app.services.major_purchase_service import simulate_major_purchase
from app.services.multi_step_scenario_service import (
    evaluate_multi_step_scenario_plan,
)
from app.services.scenario_comparison_service import (
    compare_major_purchase_scenarios,
)
from app.services.what_if_comparison_service import (
    compare_what_if_scenarios,
)
from app.services.what_if_service import simulate_what_if

_MAX_LISTED_DECISIONS = 50

_REQUEST_MODELS: dict[str, type[BaseModel]] = {
    "major_purchase": MajorPurchaseSimulationRequest,
    "scenario_comparison": ScenarioComparisonRequest,
    "stress_test": FinancialStressTestRequest,
    "buy_now_vs_wait": BuyNowVsWaitRequest,
    "what_if": WhatIfSimulationRequest,
    "what_if_comparison": WhatIfComparisonRequest,
    "multi_step_plan": MultiStepScenarioPlanRequest,
}


def _run(db: Session, user_id: int, decision_type: str, payload, as_of: date):
    if decision_type == "major_purchase":
        return simulate_major_purchase(db, user_id, payload, as_of=as_of)
    if decision_type == "scenario_comparison":
        return compare_major_purchase_scenarios(
            db, user_id, payload, as_of=as_of
        )
    if decision_type == "stress_test":
        return run_financial_stress_test(db, user_id, payload, as_of=as_of)
    if decision_type == "buy_now_vs_wait":
        return evaluate_buy_now_vs_wait(db, user_id, payload, as_of=as_of)
    if decision_type == "what_if":
        return simulate_what_if(db, user_id, payload, as_of=as_of)
    if decision_type == "what_if_comparison":
        return compare_what_if_scenarios(db, user_id, payload, as_of=as_of)
    if decision_type == "multi_step_plan":
        return evaluate_multi_step_scenario_plan(
            db, user_id, payload, as_of=as_of
        )
    raise ValueError(f"unknown decision_type: {decision_type}")


def _parse_input(decision_type: str, raw_input: dict) -> BaseModel:
    model_cls = _REQUEST_MODELS[decision_type]

    try:
        return model_cls(**raw_input)
    except ValidationError as exc:
        raise ValueError(
            f"invalid input for {decision_type}: {exc}"
        ) from exc


def save_decision(
    db: Session,
    user_id: int,
    request: SaveDecisionRequest,
    *,
    as_of: date | None = None,
) -> SavedDecision:
    calculation_date = as_of or date.today()
    payload = _parse_input(request.decision_type, request.input)
    result = _run(db, user_id, request.decision_type, payload, calculation_date)

    decision = SavedDecision(
        user_id=user_id,
        decision_type=request.decision_type,
        title=request.title,
        input_snapshot=payload.model_dump(mode="json"),
        result_snapshot=result.model_dump(mode="json"),
    )
    db.add(decision)
    db.commit()
    db.refresh(decision)

    return decision


def _attach_outcome_metadata(
    db: Session, user_id: int, decisions: list[SavedDecision]
) -> list[SavedDecision]:
    """Sets transient outcome_count/latest_outcome_at attributes on each
    decision from a single grouped aggregate query -- never one query
    per decision, regardless of how many decisions are passed in.
    """
    if not decisions:
        return decisions

    decision_ids = [decision.id for decision in decisions]

    rows = db.execute(
        select(
            DecisionOutcome.decision_id,
            func.count(DecisionOutcome.id),
            func.max(DecisionOutcome.evaluated_at),
        )
        .where(
            DecisionOutcome.user_id == user_id,
            DecisionOutcome.decision_id.in_(decision_ids),
        )
        .group_by(DecisionOutcome.decision_id)
    ).all()

    metadata_by_decision_id = {
        decision_id: (count, latest_outcome_at)
        for decision_id, count, latest_outcome_at in rows
    }

    for decision in decisions:
        count, latest_outcome_at = metadata_by_decision_id.get(
            decision.id, (0, None)
        )
        decision.outcome_count = count
        decision.latest_outcome_at = latest_outcome_at

    return decisions


def list_decisions(
    db: Session, user_id: int, *, limit: int = _MAX_LISTED_DECISIONS
) -> list[SavedDecision]:
    decisions = list(
        db.scalars(
            select(SavedDecision)
            .where(SavedDecision.user_id == user_id)
            .order_by(SavedDecision.created_at.desc())
            .limit(limit)
        ).all()
    )
    return _attach_outcome_metadata(db, user_id, decisions)


def get_decision(
    db: Session, user_id: int, decision_id: int
) -> SavedDecision | None:
    return db.scalar(
        select(SavedDecision).where(
            SavedDecision.id == decision_id,
            SavedDecision.user_id == user_id,
        )
    )


def get_decision_with_outcome_metadata(
    db: Session, user_id: int, decision_id: int
) -> SavedDecision | None:
    decision = get_decision(db, user_id, decision_id)

    if decision is None:
        return None

    _attach_outcome_metadata(db, user_id, [decision])
    return decision


def delete_decision(db: Session, user_id: int, decision_id: int) -> bool:
    decision = get_decision(db, user_id, decision_id)

    if decision is None:
        return False

    db.delete(decision)
    db.commit()
    return True


def update_decision_status(
    db: Session,
    user_id: int,
    decision_id: int,
    new_status: DecisionLifecycleStatus,
) -> SavedDecision | None:
    """Transitions a saved decision's lifecycle status.

    acted_on_at is set the first time a decision reaches "acted_on"
    and is never cleared by a later transition (including a later
    "dismissed") -- it stays as audit evidence of when the user first
    acted on the decision, even if a later re-evaluation moves the
    status again.
    """
    decision = get_decision(db, user_id, decision_id)

    if decision is None:
        return None

    decision.status = new_status

    if new_status == "acted_on" and decision.acted_on_at is None:
        decision.acted_on_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(decision)

    _attach_outcome_metadata(db, user_id, [decision])
    return decision


def rerun_decision(
    db: Session,
    user_id: int,
    decision_id: int,
    *,
    as_of: date | None = None,
) -> tuple[SavedDecision, date, dict] | None:
    """Re-executes the saved inputs against CURRENT data.

    Returns (the unmodified saved decision, the date it was
    re-evaluated at, a fresh result snapshot) so callers can show
    "then" vs. "now" without overwriting history.
    """
    decision = get_decision(db, user_id, decision_id)

    if decision is None:
        return None

    calculation_date = as_of or date.today()
    payload = _parse_input(decision.decision_type, decision.input_snapshot)
    result = _run(
        db, user_id, decision.decision_type, payload, calculation_date
    )

    return decision, calculation_date, result.model_dump(mode="json")
