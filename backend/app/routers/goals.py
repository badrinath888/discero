from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import GoalContribution, SavingsGoal, User
from app.schemas import (
    GoalContributionCreate,
    GoalContributionOut,
    GoalContributionUpdate,
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


def _get_contribution_or_404(
    goal_id: int,
    contribution_id: int,
    db: Session,
) -> GoalContribution:
    contribution = db.scalar(
        select(GoalContribution).where(
            GoalContribution.id == contribution_id,
            GoalContribution.goal_id == goal_id,
        )
    )

    if contribution is None:
        raise HTTPException(
            status_code=404,
            detail="goal contribution not found",
        )

    return contribution


def _signed_amount(
    amount_cents: int,
    contribution_type: str,
) -> int:
    if contribution_type == "withdrawal":
        return -amount_cents

    return amount_cents


def _calculate_goal_balance(
    goal_id: int,
    db: Session,
    exclude_contribution_id: int | None = None,
) -> int:
    query = select(GoalContribution).where(
        GoalContribution.goal_id == goal_id
    )

    if exclude_contribution_id is not None:
        query = query.where(
            GoalContribution.id != exclude_contribution_id
        )

    contributions = db.scalars(query).all()

    return sum(
        _signed_amount(
            contribution.amount_cents,
            contribution.contribution_type,
        )
        for contribution in contributions
    )


def _normalize_note(note: str | None) -> str | None:
    if note is None:
        return None

    normalized = note.strip()
    return normalized or None


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
        saved_cents=0,
        target_date=payload.target_date,
    )

    db.add(goal)
    db.flush()

    if payload.saved_cents > 0:
        opening_balance = GoalContribution(
            goal_id=goal.id,
            amount_cents=payload.saved_cents,
            contribution_type="deposit",
            contributed_on=date.today(),
            note="Opening balance",
        )

        db.add(opening_balance)
        goal.saved_cents = payload.saved_cents

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


@router.get(
    "/{goal_id}/contributions",
    response_model=list[GoalContributionOut],
)
def list_goal_contributions(
    user_id: int,
    goal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[GoalContribution]:
    _authorize_user(user_id, current_user)
    _get_goal_or_404(user_id, goal_id, db)

    contributions = db.scalars(
        select(GoalContribution)
        .where(GoalContribution.goal_id == goal_id)
        .order_by(
            GoalContribution.contributed_on.desc(),
            GoalContribution.created_at.desc(),
            GoalContribution.id.desc(),
        )
    ).all()

    return list(contributions)


@router.post(
    "/{goal_id}/contributions",
    response_model=GoalContributionOut,
    status_code=201,
)
def create_goal_contribution(
    user_id: int,
    goal_id: int,
    payload: GoalContributionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> GoalContribution:
    _authorize_user(user_id, current_user)

    goal = _get_goal_or_404(
        user_id,
        goal_id,
        db,
    )

    signed_amount = _signed_amount(
        payload.amount_cents,
        payload.contribution_type,
    )

    projected_balance = goal.saved_cents + signed_amount

    if projected_balance < 0:
        raise HTTPException(
            status_code=422,
            detail="withdrawal cannot exceed the amount currently saved",
        )

    contribution = GoalContribution(
        goal_id=goal.id,
        amount_cents=payload.amount_cents,
        contribution_type=payload.contribution_type,
        contributed_on=payload.contributed_on,
        note=_normalize_note(payload.note),
    )

    db.add(contribution)
    goal.saved_cents = projected_balance

    db.commit()
    db.refresh(contribution)

    return contribution


@router.patch(
    "/{goal_id}/contributions/{contribution_id}",
    response_model=GoalContributionOut,
)
def update_goal_contribution(
    user_id: int,
    goal_id: int,
    contribution_id: int,
    payload: GoalContributionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> GoalContribution:
    _authorize_user(user_id, current_user)

    goal = _get_goal_or_404(
        user_id,
        goal_id,
        db,
    )

    contribution = _get_contribution_or_404(
        goal_id,
        contribution_id,
        db,
    )

    changes = payload.model_dump(exclude_unset=True)

    new_amount = changes.get(
        "amount_cents",
        contribution.amount_cents,
    )

    new_type = changes.get(
        "contribution_type",
        contribution.contribution_type,
    )

    balance_without_current = _calculate_goal_balance(
        goal.id,
        db,
        exclude_contribution_id=contribution.id,
    )

    projected_balance = (
        balance_without_current
        + _signed_amount(
            new_amount,
            new_type,
        )
    )

    if projected_balance < 0:
        raise HTTPException(
            status_code=422,
            detail=(
                "contribution change would make "
                "the goal balance negative"
            ),
        )

    if "amount_cents" in changes:
        contribution.amount_cents = changes["amount_cents"]

    if "contribution_type" in changes:
        contribution.contribution_type = changes[
            "contribution_type"
        ]

    if "contributed_on" in changes:
        contribution.contributed_on = changes[
            "contributed_on"
        ]

    if "note" in changes:
        contribution.note = _normalize_note(
            changes["note"]
        )

    goal.saved_cents = projected_balance

    db.commit()
    db.refresh(contribution)

    return contribution


@router.delete(
    "/{goal_id}/contributions/{contribution_id}",
    status_code=204,
)
def delete_goal_contribution(
    user_id: int,
    goal_id: int,
    contribution_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    _authorize_user(user_id, current_user)

    goal = _get_goal_or_404(
        user_id,
        goal_id,
        db,
    )

    contribution = _get_contribution_or_404(
        goal_id,
        contribution_id,
        db,
    )

    projected_balance = _calculate_goal_balance(
        goal.id,
        db,
        exclude_contribution_id=contribution.id,
    )

    if projected_balance < 0:
        raise HTTPException(
            status_code=422,
            detail=(
                "deleting this contribution would make "
                "the goal balance negative"
            ),
        )

    db.delete(contribution)
    goal.saved_cents = projected_balance

    db.commit()