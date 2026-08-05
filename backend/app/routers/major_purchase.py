from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import User
from app.schemas import (
    MajorPurchaseSimulationOut,
    MajorPurchaseSimulationRequest,
)
from app.services.major_purchase_service import (
    simulate_major_purchase,
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
        return simulate_major_purchase(
            db,
            user_id,
            payload,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc