from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import User
from app.schemas import SpendingAnomaliesOut
from app.services.spending_anomaly_service import detect_spending_anomalies

router = APIRouter(
    prefix="/users/{user_id}/spending-anomalies",
    tags=["spending anomalies"],
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


@router.get(
    "",
    response_model=SpendingAnomaliesOut,
)
def get_spending_anomalies(
    user_id: int,
    lookback_months: int = Query(default=6, ge=1, le=24),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SpendingAnomaliesOut:
    _authorize_user(user_id, current_user)

    return detect_spending_anomalies(
        db,
        user_id,
        lookback_months=lookback_months,
        limit=limit,
    )
