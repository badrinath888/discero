from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import User
from app.schemas import (
    GoalConflictDetectionOut,
    GoalConflictDetectionRequest,
)
from app.services.goal_conflict_detection_service import (
    detect_goal_conflicts,
)

router = APIRouter(
    prefix="/users/{user_id}/goal-conflicts",
    tags=["goal conflict detection"],
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
    response_model=GoalConflictDetectionOut,
)
def analyze_goal_conflicts(
    user_id: int,
    payload: GoalConflictDetectionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> GoalConflictDetectionOut:
    _authorize_user(user_id, current_user)

    return detect_goal_conflicts(
        db,
        user_id,
        payload,
    )
