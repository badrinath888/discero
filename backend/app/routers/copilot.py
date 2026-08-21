from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.deps import get_copilot_client
from app.models import User
from app.rate_limit import authenticated_rate_limiter
from app.schemas import CopilotChatRequest, CopilotResponseOut
from app.services import copilot_audit
from app.services.copilot_service import (
    CopilotModelProvider,
    run_copilot_turn,
    unexpected_turn_failure_response,
)

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
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    client: CopilotModelProvider = Depends(get_copilot_client),
    _rate_limit: None = Depends(
        authenticated_rate_limiter(max_attempts=20, window_seconds=60)
    ),
) -> CopilotResponseOut:
    _authorize_user(user_id, current_user)

    # Scoped to this Copilot request only (not global tracing): lets
    # every audit row this turn produces be tied together, and gives
    # support a correlation id without exposing any request content.
    request_id = copilot_audit.new_request_id()
    response.headers["X-Request-Id"] = request_id

    try:
        return run_copilot_turn(
            db,
            user_id,
            current_user,
            payload.messages,
            client,
            request_id=request_id,
        )
    except HTTPException:
        raise
    except Exception as exc:
        # Narrow request-boundary safety net: run_copilot_turn already
        # handles every classified failure mode (validation, provider,
        # tool errors) internally and always returns a CopilotResponseOut
        # for them. Only a genuinely unexpected exception reaches here,
        # so there is no deterministic result being discarded -- one was
        # never built.
        return unexpected_turn_failure_response(
            db, user_id, request_id, exc
        )
