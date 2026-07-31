from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import Budget, Transaction, User
from app.schemas import (
    BudgetCreate,
    BudgetOut,
    BudgetProgressOut,
)

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

@router.get(
    "/progress",
    response_model=list[BudgetProgressOut],
)
def budget_progress(
    user_id: int,
    month: str = Query(
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[BudgetProgressOut]:
    _authorize_user(user_id, current_user)

    budgets = list(
        db.scalars(
            select(Budget)
            .where(
                Budget.user_id == user_id,
                Budget.month == month,
            )
            .order_by(Budget.category)
        ).all()
    )

    transactions = list(
        db.scalars(
            select(Transaction).where(
                Transaction.user_id == user_id,
                Transaction.posted_on >= f"{month}-01",
                Transaction.posted_on < _next_month(month),
                Transaction.amount_cents < 0,
            )
        ).all()
    )

    spending_by_category: dict[str, int] = {}

    for transaction in transactions:
        spending_by_category[transaction.category] = (
            spending_by_category.get(transaction.category, 0)
            + abs(transaction.amount_cents)
        )

    return [
        _build_budget_progress(
            budget,
            spending_by_category.get(budget.category, 0),
        )
        for budget in budgets
    ]


def _next_month(month: str) -> str:
    year, month_number = map(int, month.split("-"))

    if month_number == 12:
        return f"{year + 1}-01-01"

    return f"{year}-{month_number + 1:02d}-01"


def _build_budget_progress(
    budget: Budget,
    spent_cents: int,
) -> BudgetProgressOut:
    remaining_cents = budget.limit_cents - spent_cents

    return BudgetProgressOut(
        category=budget.category,
        month=budget.month,
        limit_cents=budget.limit_cents,
        spent_cents=spent_cents,
        remaining_cents=remaining_cents,
        percent_used=round(
            spent_cents / budget.limit_cents * 100,
            1,
        ),
        over_budget_cents=max(-remaining_cents, 0),
    )
