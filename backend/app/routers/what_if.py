from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import User
from app.schemas import (
    WhatIfComparisonOut,
    WhatIfComparisonRequest,
    WhatIfSimulationOut,
    WhatIfSimulationRequest,
)
from app.services.what_if_comparison_service import (
    compare_what_if_scenarios,
)
from app.services.what_if_service import simulate_what_if

router = APIRouter(
    prefix="/users/{user_id}/what-if",
    tags=["what if"],
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
    response_model=WhatIfSimulationOut,
)
def run_what_if_simulation(
    user_id: int,
    payload: WhatIfSimulationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WhatIfSimulationOut:
    _authorize_user(user_id, current_user)

    try:
        return simulate_what_if(
            db,
            user_id,
            payload,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc


@router.post(
    "/compare",
    response_model=WhatIfComparisonOut,
)
def compare_what_if_scenarios_endpoint(
    user_id: int,
    payload: WhatIfComparisonRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WhatIfComparisonOut:
    _authorize_user(user_id, current_user)

    try:
        return compare_what_if_scenarios(
            db,
            user_id,
            payload,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc
