from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import FinancialAccount, PlaidItem, Transaction, User
from app.schemas import (
    FinancialAccountOut,
    PlaidConnectionOut,
    PlaidExchangeRequest,
    PlaidLinkTokenOut,
    PlaidSyncOut,
)
from app.services.plaid_service import (
    PlaidConfigurationError,
    PlaidServiceError,
    create_link_token,
    exchange_public_token,
    get_accounts,
    remove_item,
    sync_transactions,
)
from app.token_encryption import (
    decrypt_token,
    TokenEncryptionError,
    encrypt_token,
)

router = APIRouter(
    prefix="/users/{user_id}/plaid",
    tags=["plaid"],
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
    "/link-token",
    response_model=PlaidLinkTokenOut,
)
def create_plaid_link_token(
    user_id: int,
    current_user: User = Depends(get_current_user),
) -> PlaidLinkTokenOut:
    _authorize_user(user_id, current_user)

    try:
        link_token = create_link_token(
            user_id=current_user.id,
        )
    except PlaidConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc
    except PlaidServiceError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc

    return PlaidLinkTokenOut(
        link_token=link_token,
    )


@router.post(
    "/exchange-token",
    response_model=PlaidConnectionOut,
    status_code=201,
)
def exchange_plaid_token(
    user_id: int,
    payload: PlaidExchangeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PlaidConnectionOut:
    _authorize_user(user_id, current_user)

    try:
        exchange = exchange_public_token(
            payload.public_token,
        )
        plaid_accounts = get_accounts(
            exchange.access_token,
        )
        encrypted_access_token = encrypt_token(
            exchange.access_token,
        )
    except PlaidConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc
    except TokenEncryptionError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc
    except PlaidServiceError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc

    plaid_item = db.scalar(
        select(PlaidItem).where(
            PlaidItem.provider_item_id == exchange.item_id
        )
    )

    if (
        plaid_item is not None
        and plaid_item.user_id != user_id
    ):
        raise HTTPException(
            status_code=409,
            detail="Plaid connection already belongs to another user",
        )

    try:
        if plaid_item is None:
            plaid_item = PlaidItem(
                user_id=user_id,
                provider_item_id=exchange.item_id,
                institution_id=_clean_optional(
                    payload.institution_id
                ),
                institution_name=_clean_optional(
                    payload.institution_name
                ),
                access_token_ciphertext=encrypted_access_token,
                status="active",
            )
            db.add(plaid_item)
            db.flush()
        else:
            plaid_item.access_token_ciphertext = (
                encrypted_access_token
            )
            plaid_item.status = "active"

            if payload.institution_id is not None:
                plaid_item.institution_id = _clean_optional(
                    payload.institution_id
                )

            if payload.institution_name is not None:
                plaid_item.institution_name = _clean_optional(
                    payload.institution_name
                )

        accounts = _upsert_accounts(
            db=db,
            plaid_item=plaid_item,
            account_data=plaid_accounts,
        )

        db.commit()

        for account in accounts:
            db.refresh(account)

        db.refresh(plaid_item)
    except SQLAlchemyError as exc:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail="Unable to save Plaid connection",
        ) from exc

    return PlaidConnectionOut(
        item_id=plaid_item.id,
        institution_name=plaid_item.institution_name,
        status=plaid_item.status,
        accounts=[
            FinancialAccountOut.model_validate(account)
            for account in accounts
        ],
    )



@router.delete(
    "/items/{item_id}",
    status_code=204,
)
def disconnect_plaid_item(
    user_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    _authorize_user(user_id, current_user)

    plaid_item = db.scalar(
        select(PlaidItem).where(
            PlaidItem.id == item_id,
            PlaidItem.user_id == user_id,
        )
    )

    if plaid_item is None:
        raise HTTPException(
            status_code=404,
            detail="Plaid connection not found",
        )

    try:
        access_token = decrypt_token(
            plaid_item.access_token_ciphertext
        )
        remove_item(access_token)
    except PlaidConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc
    except TokenEncryptionError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc
    except PlaidServiceError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc

    try:
        db.delete(plaid_item)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail="Unable to remove Plaid connection",
        ) from exc


@router.post(
    "/sync",
    response_model=PlaidSyncOut,
)
def synchronize_plaid_transactions(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PlaidSyncOut:
    _authorize_user(user_id, current_user)

    plaid_items = list(
        db.scalars(
            select(PlaidItem)
            .where(PlaidItem.user_id == user_id)
            .order_by(PlaidItem.id)
        ).all()
    )

    synced_at = datetime.now(timezone.utc)

    if not plaid_items:
        return PlaidSyncOut(
            added=0,
            modified=0,
            removed=0,
            items_synced=0,
            synced_at=synced_at,
        )

    account_rows = list(
        db.scalars(
            select(FinancialAccount)
            .join(PlaidItem)
            .where(PlaidItem.user_id == user_id)
        ).all()
    )

    accounts_by_provider_id = {
        account.provider_account_id: account
        for account in account_rows
    }

    sync_results = []

    try:
        for plaid_item in plaid_items:
            access_token = decrypt_token(
                plaid_item.access_token_ciphertext
            )

            result = sync_transactions(
                access_token=access_token,
                cursor=plaid_item.sync_cursor,
            )

            sync_results.append(
                (plaid_item, result)
            )
    except PlaidConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc
    except TokenEncryptionError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc
    except PlaidServiceError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc

    incoming_ids = {
        transaction.provider_transaction_id
        for _, result in sync_results
        for transaction in [
            *result.added,
            *result.modified,
        ]
    }

    removed_ids = {
        transaction_id
        for _, result in sync_results
        for transaction_id in result.removed
    }

    relevant_ids = incoming_ids | removed_ids

    existing_transactions = {
        transaction.provider_transaction_id: transaction
        for transaction in db.scalars(
            select(Transaction).where(
                Transaction.user_id == user_id,
                Transaction.provider_transaction_id.in_(
                    relevant_ids
                ),
            )
        ).all()
        if transaction.provider_transaction_id
    } if relevant_ids else {}

    added_count = 0
    modified_count = 0
    removed_count = 0

    try:
        for plaid_item, result in sync_results:
            for data in result.added:
                account = accounts_by_provider_id.get(
                    data.provider_account_id
                )

                if account is None:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "Plaid transaction account mapping "
                            "is missing"
                        ),
                    )

                transaction = existing_transactions.get(
                    data.provider_transaction_id
                )

                if transaction is None:
                    transaction = Transaction(
                        user_id=user_id,
                        financial_account_id=account.id,
                        provider_transaction_id=(
                            data.provider_transaction_id
                        ),
                        posted_on=data.posted_on,
                        description=data.description,
                        merchant_name=data.merchant_name,
                        amount_cents=data.amount_cents,
                        category=data.category,
                        source="plaid",
                        pending=data.pending,
                    )

                    db.add(transaction)

                    existing_transactions[
                        data.provider_transaction_id
                    ] = transaction

                    added_count += 1
                else:
                    _apply_plaid_transaction(
                        transaction=transaction,
                        account=account,
                        data=data,
                    )

                    modified_count += 1

            for data in result.modified:
                account = accounts_by_provider_id.get(
                    data.provider_account_id
                )

                if account is None:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "Plaid transaction account mapping "
                            "is missing"
                        ),
                    )

                transaction = existing_transactions.get(
                    data.provider_transaction_id
                )

                if transaction is None:
                    transaction = Transaction(
                        user_id=user_id,
                        financial_account_id=account.id,
                        provider_transaction_id=(
                            data.provider_transaction_id
                        ),
                        posted_on=data.posted_on,
                        description=data.description,
                        merchant_name=data.merchant_name,
                        amount_cents=data.amount_cents,
                        category=data.category,
                        source="plaid",
                        pending=data.pending,
                    )

                    db.add(transaction)

                    existing_transactions[
                        data.provider_transaction_id
                    ] = transaction

                    added_count += 1
                else:
                    _apply_plaid_transaction(
                        transaction=transaction,
                        account=account,
                        data=data,
                    )

                    modified_count += 1

            for provider_transaction_id in result.removed:
                transaction = existing_transactions.get(
                    provider_transaction_id
                )

                if transaction is None:
                    continue

                db.delete(transaction)
                removed_count += 1

                existing_transactions.pop(
                    provider_transaction_id,
                    None,
                )

            plaid_item.sync_cursor = result.next_cursor
            plaid_item.last_synced_at = synced_at
            plaid_item.status = "active"

        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail="Unable to save synchronized transactions",
        ) from exc

    return PlaidSyncOut(
        added=added_count,
        modified=modified_count,
        removed=removed_count,
        items_synced=len(sync_results),
        synced_at=synced_at,
    )


def _apply_plaid_transaction(
    transaction: Transaction,
    account: FinancialAccount,
    data,
) -> None:
    transaction.financial_account_id = account.id
    transaction.posted_on = data.posted_on
    transaction.description = data.description
    transaction.merchant_name = data.merchant_name
    transaction.amount_cents = data.amount_cents

    if not transaction.category_locked:
        transaction.category = data.category

    transaction.source = "plaid"
    transaction.pending = data.pending

def _upsert_accounts(
    db: Session,
    plaid_item: PlaidItem,
    account_data: list,
) -> list[FinancialAccount]:
    existing_accounts = {
        account.provider_account_id: account
        for account in db.scalars(
            select(FinancialAccount).where(
                FinancialAccount.plaid_item_id
                == plaid_item.id
            )
        ).all()
    }

    saved_accounts: list[FinancialAccount] = []

    for data in account_data:
        account = existing_accounts.get(
            data.provider_account_id
        )

        if account is None:
            account = FinancialAccount(
                plaid_item_id=plaid_item.id,
                provider_account_id=data.provider_account_id,
                name=data.name,
                official_name=data.official_name,
                account_type=data.account_type,
                account_subtype=data.account_subtype,
                mask=data.mask,
                current_balance_cents=(
                    data.current_balance_cents
                ),
                available_balance_cents=(
                    data.available_balance_cents
                ),
                currency=data.currency,
            )
            db.add(account)
        else:
            account.name = data.name
            account.official_name = data.official_name
            account.account_type = data.account_type
            account.account_subtype = data.account_subtype
            account.mask = data.mask
            account.current_balance_cents = (
                data.current_balance_cents
            )
            account.available_balance_cents = (
                data.available_balance_cents
            )
            account.currency = data.currency

        saved_accounts.append(account)

    db.flush()

    return saved_accounts


def _clean_optional(
    value: str | None,
) -> str | None:
    if value is None:
        return None

    cleaned = value.strip()

    return cleaned or None