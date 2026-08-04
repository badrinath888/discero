from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import RecurringItem, User
from app.schemas import (
    RecurringItemCreate,
    RecurringItemOut,
    RecurringItemUpdate,
)

router = APIRouter(
    prefix="/users/{user_id}/recurring-items",
    tags=["recurring items"],
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


def _get_item_or_404(
    user_id: int,
    item_id: int,
    db: Session,
) -> RecurringItem:
    item = db.scalar(
        select(RecurringItem).where(
            RecurringItem.id == item_id,
            RecurringItem.user_id == user_id,
        )
    )

    if item is None:
        raise HTTPException(
            status_code=404,
            detail="recurring item not found",
        )

    return item


@router.get(
    "",
    response_model=list[RecurringItemOut],
)
def list_recurring_items(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[RecurringItem]:
    _authorize_user(user_id, current_user)

    statement = (
        select(RecurringItem)
        .where(RecurringItem.user_id == user_id)
        .order_by(
            RecurringItem.next_payment,
            RecurringItem.id,
        )
    )

    return list(db.scalars(statement).all())


@router.post(
    "",
    response_model=RecurringItemOut,
    status_code=201,
)
def create_recurring_item(
    user_id: int,
    payload: RecurringItemCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RecurringItem:
    _authorize_user(user_id, current_user)

    merchant = payload.merchant.strip()
    normalized_merchant = payload.normalized_merchant.strip().upper()

    if not merchant or not normalized_merchant:
        raise HTTPException(
            status_code=422,
            detail="merchant cannot be empty",
        )

    item = RecurringItem(
        user_id=user_id,
        merchant=merchant,
        normalized_merchant=normalized_merchant,
        category=payload.category.strip()
        if payload.category
        else None,
        amount_cents=payload.amount_cents,
        frequency=payload.frequency,
        last_payment=payload.last_payment,
        next_payment=payload.next_payment,
        status=payload.status,
        confidence_score=payload.confidence_score,
        price_change_percent=payload.price_change_percent,
        price_change_warning=payload.price_change_warning,
    )

    db.add(item)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="recurring item already exists",
        ) from None

    db.refresh(item)

    return item


@router.patch(
    "/{item_id}",
    response_model=RecurringItemOut,
)
def update_recurring_item(
    user_id: int,
    item_id: int,
    payload: RecurringItemUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RecurringItem:
    _authorize_user(user_id, current_user)

    item = _get_item_or_404(
        user_id,
        item_id,
        db,
    )

    changes = payload.model_dump(exclude_unset=True)

    if "category" in changes:
        category = changes["category"]
        item.category = (
            category.strip()
            if category
            else None
        )

    if "amount_cents" in changes:
        item.amount_cents = changes["amount_cents"]

    if "frequency" in changes:
        item.frequency = changes["frequency"]

    if "next_payment" in changes:
        item.next_payment = changes["next_payment"]

    if "status" in changes:
        item.status = changes["status"]

    db.commit()
    db.refresh(item)

    return item


@router.delete(
    "/{item_id}",
    status_code=204,
)
def delete_recurring_item(
    user_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    _authorize_user(user_id, current_user)

    item = _get_item_or_404(
        user_id,
        item_id,
        db,
    )

    db.delete(item)
    db.commit()