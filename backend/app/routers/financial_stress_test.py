from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import User
from app.schemas import (
    FinancialStressTestOut,
    FinancialStressTestRequest,
)
from app.services.financial_stress_test_service import (
    run_financial_stress_test,
)

router = APIRouter(
    prefix="/users/{user_id}/financial-stress-test",
    tags=["financial stress test"],
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
    response_model=FinancialStressTestOut,
)
def run_stress_test(
    user_id: int,
    payload: FinancialStressTestRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FinancialStressTestOut:
    _authorize_user(user_id, current_user)

    try:
        return run_financial_stress_test(
            db,
            user_id,
            payload,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc
