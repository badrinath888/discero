from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import User
from app.schemas import SafeToSpendOut, SafeToSpendRequest
from app.services.safe_to_spend_service import (
    calculate_current_safe_to_spend,
)

router = APIRouter(
    prefix="/users/{user_id}/safe-to-spend",
    tags=["safe to spend"],
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
    response_model=SafeToSpendOut,
)
def get_safe_to_spend(
    user_id: int,
    payload: SafeToSpendRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SafeToSpendOut:
    _authorize_user(user_id, current_user)

    # This is the CURRENT (dashboard/Overview) Safe-to-Spend figure --
    # always the enriched calculation (projected income + goal reserve
    # folded in) regardless of what the request body's
    # include_projected_income/include_goal_reserve say, so it can
    # never diverge from Copilot's get_safe_to_spend. Scenario features
    # (Major Purchase, Buy Now vs Wait, etc.) call
    # `calculate_safe_to_spend` directly and are unaffected.
    return calculate_current_safe_to_spend(
        db,
        user_id,
        safety_reserve_cents=payload.safety_reserve_cents,
        essential_spending_cents=payload.essential_spending_cents,
        horizon_days=payload.horizon_days,
    )
