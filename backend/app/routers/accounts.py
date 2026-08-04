from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import FinancialAccount, PlaidItem, User
from app.schemas import ConnectedAccountOut

router = APIRouter(
    prefix="/users/{user_id}/accounts",
    tags=["accounts"],
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
    response_model=list[ConnectedAccountOut],
)
def list_accounts(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ConnectedAccountOut]:
    _authorize_user(user_id, current_user)

    statement = (
        select(FinancialAccount, PlaidItem)
        .join(
            PlaidItem,
            FinancialAccount.plaid_item_id == PlaidItem.id,
        )
        .where(PlaidItem.user_id == user_id)
        .order_by(
            PlaidItem.institution_name,
            FinancialAccount.name,
        )
    )

    return [
        ConnectedAccountOut(
            id=account.id,
            plaid_item_id=item.id,
            institution_name=item.institution_name,
            name=account.name,
            official_name=account.official_name,
            account_type=account.account_type,
            account_subtype=account.account_subtype,
            mask=account.mask,
            current_balance_cents=(
                account.current_balance_cents
            ),
            available_balance_cents=(
                account.available_balance_cents
            ),
            currency=account.currency,
            connection_status=item.status,
            sync_status=item.sync_status,
            sync_error=item.sync_error,
            last_sync_attempted_at=item.last_sync_attempted_at,
            last_synced_at=item.last_synced_at,
        )
        for account, item in db.execute(statement).all()
    ]
