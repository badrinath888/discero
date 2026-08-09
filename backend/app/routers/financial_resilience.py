from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import User
from app.schemas import FinancialResilienceOut
from app.services.financial_resilience_service import (
    evaluate_financial_resilience,
)

router = APIRouter(
    prefix="/users/{user_id}/financial-resilience",
    tags=["financial resilience"],
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
    response_model=FinancialResilienceOut,
)
def get_financial_resilience(
    user_id: int,
    essential_spending_cents: int | None = Query(default=None, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FinancialResilienceOut:
    _authorize_user(user_id, current_user)

    return evaluate_financial_resilience(
        db,
        user_id,
        essential_spending_cents=essential_spending_cents,
    )
