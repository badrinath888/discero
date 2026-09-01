from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import User
from app.schemas import (
    BuyNowVsWaitOut,
    BuyNowVsWaitRequest,
    MajorPurchaseSimulationOut,
    MajorPurchaseSimulationRequest,
    ScenarioComparisonOut,
    ScenarioComparisonRequest,
)
from app.services.buy_now_vs_wait_service import evaluate_buy_now_vs_wait
from app.services.major_purchase_service import (
    simulate_major_purchase,
)
from app.services.scenario_comparison_service import (
    compare_major_purchase_scenarios,
)

router = APIRouter(
    prefix="/users/{user_id}/major-purchase",
    tags=["major purchase"],
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
    "/simulate",
    response_model=MajorPurchaseSimulationOut,
)
def simulate_purchase(
    user_id: int,
    payload: MajorPurchaseSimulationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MajorPurchaseSimulationOut:
    _authorize_user(user_id, current_user)

    try:
        # The direct Major Purchase Simulator must evaluate against the
        # same canonical CURRENT Safe-to-Spend baseline shown on the
        # Overview dashboard and by Copilot's get_safe_to_spend -- see
        # simulate_major_purchase's docstring.
        return simulate_major_purchase(
            db,
            user_id,
            payload,
            include_projected_income=True,
            include_goal_reserve=True,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc


@router.post(
    "/compare",
    response_model=ScenarioComparisonOut,
)
def compare_purchase_scenarios(
    user_id: int,
    payload: ScenarioComparisonRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ScenarioComparisonOut:
    _authorize_user(user_id, current_user)

    try:
        return compare_major_purchase_scenarios(
            db,
            user_id,
            payload,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc


@router.post(
    "/buy-now-vs-wait",
    response_model=BuyNowVsWaitOut,
)
def buy_now_vs_wait(
    user_id: int,
    payload: BuyNowVsWaitRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BuyNowVsWaitOut:
    _authorize_user(user_id, current_user)

    try:
        return evaluate_buy_now_vs_wait(
            db,
            user_id,
            payload,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc