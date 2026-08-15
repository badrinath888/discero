"""Saved Decision History.

A saved decision snapshots BOTH the inputs the user analyzed AND the
real deterministic result at that moment -- never just prose. Saving
and re-running both re-execute the actual deterministic service
server-side; a client-supplied "result" is never trusted or persisted
directly, so the stored snapshot is always a genuine calculation.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SavedDecision
from app.schemas import (
    BuyNowVsWaitRequest,
    FinancialStressTestRequest,
    MajorPurchaseSimulationRequest,
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


def list_decisions(
    db: Session, user_id: int, *, limit: int = _MAX_LISTED_DECISIONS
) -> list[SavedDecision]:
    return list(
        db.scalars(
            select(SavedDecision)
            .where(SavedDecision.user_id == user_id)
            .order_by(SavedDecision.created_at.desc())
            .limit(limit)
        ).all()
    )


def get_decision(
    db: Session, user_id: int, decision_id: int
) -> SavedDecision | None:
    return db.scalar(
        select(SavedDecision).where(
            SavedDecision.id == decision_id,
            SavedDecision.user_id == user_id,
        )
    )


def delete_decision(db: Session, user_id: int, decision_id: int) -> bool:
    decision = get_decision(db, user_id, decision_id)

    if decision is None:
        return False

    db.delete(decision)
    db.commit()
    return True


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
