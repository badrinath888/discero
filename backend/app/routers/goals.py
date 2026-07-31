from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import SavingsGoal, User
from app.schemas import (
    SavingsGoalCreate,
    SavingsGoalOut,
    SavingsGoalUpdate,
)

router = APIRouter(
    prefix="/users/{user_id}/goals",
    tags=["savings goals"],
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


def _get_goal_or_404(
    user_id: int,
    goal_id: int,
    db: Session,
) -> SavingsGoal:
    goal = db.scalar(
        select(SavingsGoal).where(
            SavingsGoal.id == goal_id,
            SavingsGoal.user_id == user_id,
        )
    )

    if goal is None:
        raise HTTPException(
            status_code=404,
            detail="savings goal not found",
        )

    return goal


def _goal_out(goal: SavingsGoal) -> SavingsGoalOut:
    remaining = max(
        goal.target_cents - goal.saved_cents,
        0,
    )

    if goal.saved_cents >= goal.target_cents:
        status = "completed"
    elif goal.target_date and goal.target_date < date.today():
        status = "overdue"
    else:
        status = "active"

    return SavingsGoalOut(
        id=goal.id,
        name=goal.name,
        target_cents=goal.target_cents,
        saved_cents=goal.saved_cents,
        remaining_cents=remaining,
        progress_percent=round(
            goal.saved_cents / goal.target_cents * 100,
            1,
        ),
        target_date=goal.target_date,
        status=status,
        created_at=goal.created_at,
        updated_at=goal.updated_at,
    )


@router.get(
    "",
    response_model=list[SavingsGoalOut],
)
def list_goals(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[SavingsGoalOut]:
    _authorize_user(user_id, current_user)

    goals = db.scalars(
        select(SavingsGoal)
        .where(SavingsGoal.user_id == user_id)
        .order_by(
            SavingsGoal.created_at.desc(),
            SavingsGoal.id.desc(),
        )
    ).all()

    return [_goal_out(goal) for goal in goals]


@router.post(
    "",
    response_model=SavingsGoalOut,
    status_code=201,
)
def create_goal(
    user_id: int,
    payload: SavingsGoalCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SavingsGoalOut:
    _authorize_user(user_id, current_user)

    name = payload.name.strip()

    if not name:
        raise HTTPException(
            status_code=422,
            detail="goal name cannot be empty",
        )

    goal = SavingsGoal(
        user_id=user_id,
        name=name,
        target_cents=payload.target_cents,
        saved_cents=payload.saved_cents,
        target_date=payload.target_date,
    )

    db.add(goal)
    db.commit()
    db.refresh(goal)

    return _goal_out(goal)


@router.patch(
    "/{goal_id}",
    response_model=SavingsGoalOut,
)
def update_goal(
    user_id: int,
    goal_id: int,
    payload: SavingsGoalUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SavingsGoalOut:
    _authorize_user(user_id, current_user)

    goal = _get_goal_or_404(
        user_id,
        goal_id,
        db,
    )

    changes = payload.model_dump(exclude_unset=True)

    if "name" in changes:
        name = changes["name"].strip()

        if not name:
            raise HTTPException(
                status_code=422,
                detail="goal name cannot be empty",
            )

        goal.name = name

    if "target_cents" in changes:
        goal.target_cents = changes["target_cents"]

    if "saved_cents" in changes:
        goal.saved_cents = changes["saved_cents"]

    if "target_date" in changes:
        goal.target_date = changes["target_date"]

    db.commit()
    db.refresh(goal)

    return _goal_out(goal)


@router.delete(
    "/{goal_id}",
    status_code=204,
)
def delete_goal(
    user_id: int,
    goal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    _authorize_user(user_id, current_user)

    goal = _get_goal_or_404(
        user_id,
        goal_id,
        db,
    )

    db.delete(goal)
    db.commit()
