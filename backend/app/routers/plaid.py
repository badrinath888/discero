from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, or_, select, update
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
    PlaidItemOut,
    PlaidSyncOut,
    PlaidSyncStatusOut,
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

SYNC_CLAIM_TIMEOUT = timedelta(minutes=15)


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
            plaid_item.sync_status = "idle"
            plaid_item.sync_error = None

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
    if plaid_item.sync_status == "syncing":
        raise HTTPException(
            status_code=409,
            detail="Wait for synchronization to finish before disconnecting",
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
        account_ids = list(
            db.scalars(
                select(FinancialAccount.id).where(
                    FinancialAccount.plaid_item_id == plaid_item.id
                )
            ).all()
        )

        # Plaid-imported transactions belong to this item's accounts and
        # have no independent existence once the item is disconnected --
        # left in place, financial_account_id would go NULL (via the
        # accounts' ON DELETE SET NULL) and they'd resurface in the UI as
        # stale, unlinked-looking duplicates. CSV/manual transactions are
        # untouched by the source filter even if they happen to reference
        # one of these accounts.
        if account_ids:
            db.execute(
                delete(Transaction)
                .where(
                    Transaction.user_id == user_id,
                    Transaction.financial_account_id.in_(account_ids),
                    Transaction.source == "plaid",
                )
                .execution_options(synchronize_session=False)
            )

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

    added_count = 0
    modified_count = 0
    removed_count = 0

    for plaid_item in plaid_items:
        counts = _sync_plaid_item(
            db=db,
            user_id=user_id,
            item_id=plaid_item.id,
            attempted_at=synced_at,
        )
        added_count += counts[0]
        modified_count += counts[1]
        removed_count += counts[2]

    return PlaidSyncOut(
        added=added_count,
        modified=modified_count,
        removed=removed_count,
        items_synced=len(plaid_items),
        synced_at=synced_at,
    )


@router.get(
    "/sync/status",
    response_model=PlaidSyncStatusOut,
)
def get_plaid_sync_status(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PlaidSyncStatusOut:
    _authorize_user(user_id, current_user)

    items = list(
        db.scalars(
            select(PlaidItem)
            .where(PlaidItem.user_id == user_id)
            .order_by(PlaidItem.id)
        ).all()
    )

    return PlaidSyncStatusOut(
        items=[
            PlaidItemOut(
                id=item.id,
                institution_name=item.institution_name,
                status=item.status,
                sync_status=item.sync_status,
                sync_error=item.sync_error,
                last_sync_attempted_at=item.last_sync_attempted_at,
                last_synced_at=item.last_synced_at,
            )
            for item in items
        ]
    )


def _sync_plaid_item(
    db: Session,
    user_id: int,
    item_id: int,
    attempted_at: datetime,
) -> tuple[int, int, int]:
    attempted_at = (
        attempted_at.replace(tzinfo=timezone.utc)
        if attempted_at.tzinfo is None
        else attempted_at.astimezone(timezone.utc)
    )
    stale_before = attempted_at - SYNC_CLAIM_TIMEOUT
    claim = db.execute(
        update(PlaidItem)
        .where(
            PlaidItem.id == item_id,
            PlaidItem.user_id == user_id,
            or_(
                PlaidItem.sync_status != "syncing",
                PlaidItem.last_sync_attempted_at.is_(None),
                PlaidItem.last_sync_attempted_at <= stale_before,
            ),
        )
        .values(
            sync_status="syncing",
            sync_error=None,
            last_sync_attempted_at=attempted_at,
        )
        .execution_options(synchronize_session=False)
    )
    if claim.rowcount == 0:
        db.rollback()
        exists = db.scalar(
            select(PlaidItem.id).where(
                PlaidItem.id == item_id,
                PlaidItem.user_id == user_id,
            )
        )
        if exists is None:
            raise HTTPException(404, "Plaid connection not found")
        raise HTTPException(409, "Plaid synchronization is already running")
    db.commit()

    plaid_item = db.scalar(
        select(PlaidItem).where(
            PlaidItem.id == item_id,
            PlaidItem.user_id == user_id,
        )
    )
    if plaid_item is None:
        raise HTTPException(404, "Plaid connection not found")

    try:
        access_token = decrypt_token(plaid_item.access_token_ciphertext)
        result = sync_transactions(
            access_token=access_token,
            cursor=plaid_item.sync_cursor,
        )
        return _store_sync_result(
            db=db,
            user_id=user_id,
            item_id=item_id,
            result=result,
            synced_at=attempted_at,
        )
    except PlaidConfigurationError as exc:
        _record_sync_failure(
            db, user_id, item_id, "Plaid integration is unavailable"
        )
        raise HTTPException(503, str(exc)) from exc
    except TokenEncryptionError as exc:
        _record_sync_failure(
            db, user_id, item_id, "Stored connection could not be read"
        )
        raise HTTPException(503, str(exc)) from exc
    except PlaidServiceError as exc:
        _record_sync_failure(
            db,
            user_id,
            item_id,
            "Reconnect required"
            if exc.reconnect_required
            else "Plaid synchronization failed",
            reconnect_required=exc.reconnect_required,
        )
        raise HTTPException(502, str(exc)) from exc


def _store_sync_result(
    db: Session,
    user_id: int,
    item_id: int,
    result,
    synced_at: datetime,
) -> tuple[int, int, int]:
    try:
        plaid_item = db.scalar(
            select(PlaidItem).where(
                PlaidItem.id == item_id,
                PlaidItem.user_id == user_id,
            )
        )
        if plaid_item is None:
            raise HTTPException(404, "Plaid connection not found")

        accounts = list(
            db.scalars(
                select(FinancialAccount).where(
                    FinancialAccount.plaid_item_id == plaid_item.id
                )
            ).all()
        )
        accounts_by_provider_id = {
            account.provider_account_id: account for account in accounts
        }
        account_ids = {account.id for account in accounts}
        incoming = [*result.added, *result.modified]
        relevant_ids = {
            data.provider_transaction_id for data in incoming
        } | set(result.removed)
        existing_transactions = {
            transaction.provider_transaction_id: transaction
            for transaction in db.scalars(
                select(Transaction).where(
                    Transaction.user_id == user_id,
                    Transaction.provider_transaction_id.in_(relevant_ids),
                )
            ).all()
            if transaction.provider_transaction_id
        } if relevant_ids else {}

        added_count = 0
        modified_count = 0
        for data in incoming:
            account = accounts_by_provider_id.get(data.provider_account_id)
            if account is None:
                raise HTTPException(
                    409, "Plaid transaction account mapping is missing"
                )
            transaction = existing_transactions.get(
                data.provider_transaction_id
            )
            if transaction is None:
                transaction = Transaction(
                    user_id=user_id,
                    financial_account_id=account.id,
                    provider_transaction_id=data.provider_transaction_id,
                    posted_on=data.posted_on,
                    description=data.description,
                    merchant_name=data.merchant_name,
                    amount_cents=data.amount_cents,
                    category=data.category,
                    source="plaid",
                    pending=data.pending,
                )
                db.add(transaction)
                existing_transactions[data.provider_transaction_id] = transaction
                added_count += 1
            else:
                if (
                    transaction.financial_account_id is not None
                    and transaction.financial_account_id not in account_ids
                ):
                    raise HTTPException(
                        409, "Plaid transaction ownership mismatch"
                    )
                _apply_plaid_transaction(transaction, account, data)
                modified_count += 1

        removed_count = 0
        for provider_transaction_id in result.removed:
            transaction = existing_transactions.get(provider_transaction_id)
            if transaction is None:
                continue
            if (
                transaction.financial_account_id is not None
                and transaction.financial_account_id not in account_ids
            ):
                raise HTTPException(409, "Plaid transaction ownership mismatch")
            db.delete(transaction)
            removed_count += 1

        plaid_item.sync_cursor = result.next_cursor
        plaid_item.last_synced_at = synced_at
        plaid_item.sync_status = "succeeded"
        plaid_item.sync_error = None
        plaid_item.status = "active"
        db.commit()
        return added_count, modified_count, removed_count
    except HTTPException as exc:
        db.rollback()
        _record_sync_failure(db, user_id, item_id, str(exc.detail))
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        _record_sync_failure(
            db, user_id, item_id, "Synchronized data could not be saved"
        )
        raise HTTPException(
            500, "Unable to save synchronized transactions"
        ) from exc


def _record_sync_failure(
    db: Session,
    user_id: int,
    item_id: int,
    summary: str,
    reconnect_required: bool = False,
) -> None:
    db.rollback()
    plaid_item = db.scalar(
        select(PlaidItem).where(
            PlaidItem.id == item_id,
            PlaidItem.user_id == user_id,
        )
    )
    if plaid_item is None:
        return
    plaid_item.sync_status = "failed"
    plaid_item.sync_error = summary[:255]
    if reconnect_required:
        plaid_item.status = "reconnect_required"
    db.commit()


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
