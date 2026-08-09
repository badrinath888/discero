from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import User
from app.schemas import RecommendationsOut
from app.services.recommendation_service import evaluate_recommendations

router = APIRouter(
    prefix="/users/{user_id}/recommendations",
    tags=["recommendations"],
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
    response_model=RecommendationsOut,
)
def get_recommendations(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RecommendationsOut:
    _authorize_user(user_id, current_user)

    return evaluate_recommendations(db, user_id, current_user)
