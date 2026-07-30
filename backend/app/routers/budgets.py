from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import Budget, User
from app.schemas import BudgetCreate, BudgetOut

router = APIRouter(
    prefix="/users/{user_id}/budgets",
    tags=["budgets"],
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


@router.get("", response_model=list[BudgetOut])
def list_budgets(
    user_id: int,
    month: str | None = Query(
        default=None,
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Budget]:
    _authorize_user(user_id, current_user)

    selected_month = month or date.today().strftime("%Y-%m")

    statement = (
        select(Budget)
        .where(
            Budget.user_id == user_id,
            Budget.month == selected_month,
        )
        .order_by(Budget.category)
    )

    return list(db.scalars(statement).all())


@router.put("", response_model=BudgetOut)
def save_budget(
    user_id: int,
    payload: BudgetCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Budget:
    _authorize_user(user_id, current_user)

    category = payload.category.strip()

    if not category:
        raise HTTPException(
            status_code=422,
            detail="category cannot be empty",
        )

    budget = db.scalar(
        select(Budget).where(
            Budget.user_id == user_id,
            Budget.category == category,
            Budget.month == payload.month,
        )
    )

    if budget is None:
        budget = Budget(
            user_id=user_id,
            category=category,
            month=payload.month,
            limit_cents=payload.limit_cents,
        )
        db.add(budget)
    else:
        budget.limit_cents = payload.limit_cents

    db.commit()
    db.refresh(budget)

    return budget