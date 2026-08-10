from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import User
from app.schemas import RecurringIntelligenceOut
from app.services.recurring_intelligence_service import (
    evaluate_recurring_intelligence,
)

router = APIRouter(
    prefix="/users/{user_id}/recurring-intelligence",
    tags=["recurring intelligence"],
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
    response_model=RecurringIntelligenceOut,
)
def get_recurring_intelligence(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RecurringIntelligenceOut:
    _authorize_user(user_id, current_user)

    return evaluate_recurring_intelligence(db, user_id)
