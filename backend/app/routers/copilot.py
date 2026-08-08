from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.deps import get_copilot_client
from app.models import User
from app.rate_limit import rate_limiter
from app.schemas import CopilotChatRequest, CopilotResponseOut
from app.services.copilot_service import CopilotClient, run_copilot_turn

router = APIRouter(
    prefix="/users/{user_id}/copilot",
    tags=["copilot"],
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
    "/chat",
    response_model=CopilotResponseOut,
)
def chat(
    user_id: int,
    payload: CopilotChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    client: CopilotClient = Depends(get_copilot_client),
    _rate_limit: None = Depends(
        rate_limiter(max_attempts=20, window_seconds=60)
    ),
) -> CopilotResponseOut:
    _authorize_user(user_id, current_user)

    return run_copilot_turn(
        db,
        user_id,
        current_user,
        payload.messages,
        client,
    )
