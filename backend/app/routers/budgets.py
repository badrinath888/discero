from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import Budget, Transaction, User
from app.schemas import (
    BudgetCopyResult,
    BudgetCopyRequest,
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
    month: str = Query(
        pattern=r"^[1-9]\d{3}-(0[1-9]|1[0-2])$",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Budget]:
    _authorize_user(user_id, current_user)

    statement = (
        select(Budget)
        .where(
            Budget.user_id == user_id,
            Budget.month == month,
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


@router.delete("/{category}", status_code=204)
def delete_budget(
    user_id: int,
    category: str,
    month: str = Query(
        pattern=r"^[1-9]\d{3}-(0[1-9]|1[0-2])$",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    _authorize_user(user_id, current_user)

    budget = db.scalar(
        select(Budget).where(
            Budget.user_id == user_id,
            Budget.category == category,
            Budget.month == month,
        )
    )

    if budget is None:
        raise HTTPException(
            status_code=404,
            detail="budget not found",
        )

    db.delete(budget)
    db.commit()

    return Response(status_code=204)


@router.post(
    "/copy",
    response_model=BudgetCopyResult,
)
def copy_budgets(
    user_id: int,
    payload: BudgetCopyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BudgetCopyResult:
    _authorize_user(user_id, current_user)

    if payload.source_month == payload.target_month:
        raise HTTPException(
            status_code=422,
            detail="source and target months must differ",
        )

    return _copy_budgets(
        user_id,
        payload.source_month,
        payload.target_month,
        payload.overwrite,
        db,
    )


@router.post(
    "/copy-previous",
    response_model=BudgetCopyResult,
)
def copy_previous_month_budgets(
    user_id: int,
    month: str = Query(
        pattern=r"^[1-9]\d{3}-(0[1-9]|1[0-2])$",
    ),
    overwrite: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BudgetCopyResult:
    _authorize_user(user_id, current_user)

    return _copy_budgets(
        user_id,
        _previous_month(month),
        month,
        overwrite,
        db,
    )


def _copy_budgets(
    user_id: int,
    source_month: str,
    target_month: str,
    overwrite: bool,
    db: Session,
) -> BudgetCopyResult:

    source_budgets = list(
        db.scalars(
            select(Budget)
            .where(
                Budget.user_id == user_id,
                Budget.month == source_month,
            )
            .order_by(Budget.category)
        ).all()
    )

    if not source_budgets:
        raise HTTPException(
            status_code=404,
            detail=f"no budgets found for {source_month}",
        )

    target_budgets = {
        budget.category: budget
        for budget in db.scalars(
            select(Budget).where(
                Budget.user_id == user_id,
                Budget.month == target_month,
            )
        ).all()
    }

    copied = 0
    updated = 0
    skipped = 0

    for source_budget in source_budgets:
        target_budget = target_budgets.get(source_budget.category)

        if target_budget is None:
            target_budget = Budget(
                user_id=user_id,
                category=source_budget.category,
                month=target_month,
                limit_cents=source_budget.limit_cents,
            )
            db.add(target_budget)
            target_budgets[source_budget.category] = target_budget
            copied += 1
        elif overwrite:
            target_budget.limit_cents = source_budget.limit_cents
            updated += 1
        else:
            skipped += 1

    db.commit()

    budgets = list(
        db.scalars(
            select(Budget)
            .where(
                Budget.user_id == user_id,
                Budget.month == target_month,
            )
            .order_by(Budget.category)
        ).all()
    )

    return BudgetCopyResult(
        source_month=source_month,
        target_month=target_month,
        copied=copied,
        updated=updated,
        skipped=skipped,
        budgets=budgets,
    )


@router.get(
    "/progress",
    response_model=list[BudgetProgressOut],
)
def budget_progress(
    user_id: int,
    month: str = Query(
        pattern=r"^[1-9]\d{3}-(0[1-9]|1[0-2])$",
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
                Transaction.posted_on >= _month_start(month),
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


def _previous_month(month: str) -> str:
    year, month_number = map(int, month.split("-"))

    if month_number == 1:
        return f"{year - 1}-12"

    return f"{year}-{month_number - 1:02d}"


def _month_start(month: str) -> date:
    return date.fromisoformat(f"{month}-01")


def _next_month(month: str) -> date:
    year, month_number = map(int, month.split("-"))

    if month_number == 12:
        return date(year + 1, 1, 1)

    return date(year, month_number + 1, 1)


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
        overspent=remaining_cents < 0,
    )
