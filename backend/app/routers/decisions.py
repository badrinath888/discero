from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import User
from app.schemas import (
    DashboardDecisionIntelligenceOut,
    DecisionAdaptiveIntelligenceOut,
    DecisionCalibrationOut,
    DecisionOutcomeOut,
    DecisionPortfolioOut,
    DecisionPortfolioRequest,
    DecisionRerunOut,
    DecisionReviewQueueOut,
    DecisionTimelineOut,
    MultiStepScenarioPlanOut,
    MultiStepScenarioPlanRequest,
    SaveDecisionRequest,
    SavedDecisionOut,
    UpdateDecisionLifecycleRequest,
)
from app.services import (
    decision_adaptive_intelligence_service,
    decision_calibration_service,
    decision_change_explanation_service,
    decision_dashboard_intelligence_service,
    decision_history_service,
    decision_outcome_service,
    decision_portfolio_service,
    decision_review_service,
    decision_timeline_service,
    multi_step_scenario_service,
)

router = APIRouter(
    prefix="/users/{user_id}/decisions",
    tags=["decisions"],
)


def _authorize_user(
    user_id: int,
    current_user: User,
) -> None:
    if current_user.id != user_id:
        raise HTTPException(
            status_code=403,
            detail="you cannot access another user's data",
        )


@router.post(
    "",
    response_model=SavedDecisionOut,
    status_code=201,
)
def save_decision(
    user_id: int,
    payload: SaveDecisionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SavedDecisionOut:
    _authorize_user(user_id, current_user)

    try:
        return decision_history_service.save_decision(
            db, user_id, payload
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "",
    response_model=list[SavedDecisionOut],
)
def list_decisions(
    user_id: int,
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[SavedDecisionOut]:
    _authorize_user(user_id, current_user)

    return decision_history_service.list_decisions(
        db, user_id, limit=limit
    )


@router.get(
    "/calibration",
    response_model=DecisionCalibrationOut,
)
def get_decision_calibration(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DecisionCalibrationOut:
    _authorize_user(user_id, current_user)

    return decision_calibration_service.get_decision_calibration(db, user_id)


@router.get(
    "/adaptive-intelligence",
    response_model=DecisionAdaptiveIntelligenceOut,
)
def get_decision_adaptive_intelligence(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DecisionAdaptiveIntelligenceOut:
    _authorize_user(user_id, current_user)

    calibration = decision_calibration_service.get_decision_calibration(
        db, user_id
    )

    return decision_adaptive_intelligence_service.build_adaptive_intelligence(
        calibration
    )


@router.post(
    "/portfolio",
    response_model=DecisionPortfolioOut,
)
def evaluate_decision_portfolio(
    user_id: int,
    payload: DecisionPortfolioRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DecisionPortfolioOut:
    _authorize_user(user_id, current_user)

    items = payload.resolved_items()
    decision_ids = [item.decision_id for item in items]
    variants = {
        item.decision_id: item.variant
        for item in items
        if item.variant is not None
    }

    try:
        return decision_portfolio_service.evaluate_decision_portfolio(
            db, user_id, decision_ids, variants=variants
        )
    except decision_portfolio_service.DecisionPortfolioNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except decision_portfolio_service.DecisionPortfolioValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"message": str(exc), **exc.details},
        ) from exc


@router.post(
    "/multi-step",
    response_model=MultiStepScenarioPlanOut,
)
def evaluate_multi_step_scenario_plan(
    user_id: int,
    payload: MultiStepScenarioPlanRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MultiStepScenarioPlanOut:
    _authorize_user(user_id, current_user)

    try:
        return multi_step_scenario_service.evaluate_multi_step_scenario_plan(
            db, user_id, payload
        )
    except multi_step_scenario_service.MultiStepScenarioValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"message": str(exc), **exc.details},
        ) from exc


@router.get(
    "/review-queue",
    response_model=DecisionReviewQueueOut,
)
def get_decision_review_queue(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DecisionReviewQueueOut:
    _authorize_user(user_id, current_user)

    items = decision_review_service.build_review_queue(db, user_id)

    return DecisionReviewQueueOut(items=items, total_count=len(items))


@router.get(
    "/dashboard-intelligence",
    response_model=DashboardDecisionIntelligenceOut,
)
def get_dashboard_decision_intelligence(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DashboardDecisionIntelligenceOut:
    _authorize_user(user_id, current_user)

    return (
        decision_dashboard_intelligence_service.build_dashboard_intelligence(
            db, user_id
        )
    )


@router.get(
    "/{decision_id}",
    response_model=SavedDecisionOut,
)
def get_decision(
    user_id: int,
    decision_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SavedDecisionOut:
    _authorize_user(user_id, current_user)

    decision = decision_history_service.get_decision_with_outcome_metadata(
        db, user_id, decision_id
    )

    if decision is None:
        raise HTTPException(
            status_code=404, detail="saved decision not found"
        )

    return decision


@router.delete(
    "/{decision_id}",
    status_code=204,
)
def delete_decision(
    user_id: int,
    decision_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    _authorize_user(user_id, current_user)

    deleted = decision_history_service.delete_decision(
        db, user_id, decision_id
    )

    if not deleted:
        raise HTTPException(
            status_code=404, detail="saved decision not found"
        )


@router.patch(
    "/{decision_id}/status",
    response_model=SavedDecisionOut,
)
def update_decision_status(
    user_id: int,
    decision_id: int,
    payload: UpdateDecisionLifecycleRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SavedDecisionOut:
    _authorize_user(user_id, current_user)

    decision = decision_history_service.update_decision_status(
        db, user_id, decision_id, payload.status
    )

    if decision is None:
        raise HTTPException(
            status_code=404, detail="saved decision not found"
        )

    return decision


@router.post(
    "/{decision_id}/outcomes",
    response_model=DecisionOutcomeOut,
    status_code=201,
)
def evaluate_decision_outcome(
    user_id: int,
    decision_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DecisionOutcomeOut:
    _authorize_user(user_id, current_user)

    try:
        outcome = decision_outcome_service.evaluate_decision_outcome(
            db, user_id, decision_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if outcome is None:
        raise HTTPException(
            status_code=404, detail="saved decision not found"
        )

    return outcome


@router.get(
    "/{decision_id}/outcomes",
    response_model=list[DecisionOutcomeOut],
)
def list_decision_outcomes(
    user_id: int,
    decision_id: int,
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[DecisionOutcomeOut]:
    _authorize_user(user_id, current_user)

    outcomes = decision_outcome_service.list_decision_outcomes(
        db, user_id, decision_id, limit=limit
    )

    if outcomes is None:
        raise HTTPException(
            status_code=404, detail="saved decision not found"
        )

    return outcomes


@router.get(
    "/{decision_id}/timeline",
    response_model=DecisionTimelineOut,
)
def get_decision_timeline(
    user_id: int,
    decision_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DecisionTimelineOut:
    _authorize_user(user_id, current_user)

    timeline = decision_timeline_service.build_decision_timeline(
        db, user_id, decision_id
    )

    if timeline is None:
        raise HTTPException(
            status_code=404, detail="saved decision not found"
        )

    return timeline


@router.post(
    "/{decision_id}/rerun",
    response_model=DecisionRerunOut,
)
def rerun_decision(
    user_id: int,
    decision_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DecisionRerunOut:
    _authorize_user(user_id, current_user)

    outcome = decision_history_service.rerun_decision(
        db, user_id, decision_id
    )

    if outcome is None:
        raise HTTPException(
            status_code=404, detail="saved decision not found"
        )

    decision, evaluated_at, result_snapshot = outcome

    # Best-effort: the rerun result above is already a genuine,
    # successful deterministic recalculation. A change-explanation
    # failure (e.g. an unexpected legacy result_snapshot shape) must
    # never turn that success into a failed rerun.
    try:
        change_explanation = (
            decision_change_explanation_service.build_change_explanation(
                decision.result_snapshot, result_snapshot
            )
        )
    except Exception:
        change_explanation = None

    return DecisionRerunOut(
        decision_id=decision.id,
        decision_type=decision.decision_type,
        evaluated_at=evaluated_at,
        result_snapshot=result_snapshot,
        change_explanation=change_explanation,
    )
