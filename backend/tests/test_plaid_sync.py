from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import FinancialAccount, PlaidItem, Transaction
from app.routers import plaid as plaid_router
from app.services.plaid_service import (
    PlaidTransactionData,
    PlaidTransactionSyncResult,
)
from tests.conftest import TestingSessionLocal


def test_sync_requires_authentication(
    client: TestClient,
    user_id: int,
) -> None:
    response = client.post(
        f"/users/{user_id}/plaid/sync"
    )

    assert response.status_code == 401


def test_sync_rejects_cross_user_access(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    response = client.post(
        f"/users/{user_id + 1}/plaid/sync",
        headers=auth_headers,
    )

    assert response.status_code == 403


def test_sync_without_connected_items(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    response = client.post(
        f"/users/{user_id}/plaid/sync",
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["added"] == 0
    assert response.json()["modified"] == 0
    assert response.json()["removed"] == 0
    assert response.json()["items_synced"] == 0


def test_sync_adds_transaction_and_saves_cursor(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    with TestingSessionLocal() as db:
        item = PlaidItem(
            user_id=user_id,
            provider_item_id="item-sync-1",
            institution_name="First Platypus Bank",
            access_token_ciphertext="encrypted-token",
            status="active",
        )
        db.add(item)
        db.flush()

        db.add(
            FinancialAccount(
                plaid_item_id=item.id,
                provider_account_id="account-sync-1",
                name="Plaid Checking",
                account_type="depository",
                account_subtype="checking",
                currency="USD",
            )
        )
        db.commit()

    monkeypatch.setattr(
        plaid_router,
        "decrypt_token",
        lambda ciphertext: "access-token",
    )

    monkeypatch.setattr(
        plaid_router,
        "sync_transactions",
        lambda access_token, cursor: PlaidTransactionSyncResult(
            added=[
                PlaidTransactionData(
                    provider_transaction_id="transaction-sync-1",
                    provider_account_id="account-sync-1",
                    posted_on=date(2026, 7, 30),
                    description="Coffee Shop",
                    merchant_name="Coffee Shop",
                    amount_cents=-1250,
                    category="Dining",
                    pending=False,
                )
            ],
            modified=[],
            removed=[],
            next_cursor="cursor-1",
        ),
    )

    response = client.post(
        f"/users/{user_id}/plaid/sync",
        headers=auth_headers,
    )

    assert response.status_code == 200

    body = response.json()

    assert body["added"] == 1
    assert body["modified"] == 0
    assert body["removed"] == 0
    assert body["items_synced"] == 1

    with TestingSessionLocal() as db:
        transaction = db.scalar(
            select(Transaction).where(
                Transaction.provider_transaction_id
                == "transaction-sync-1"
            )
        )

        assert transaction is not None
        assert transaction.user_id == user_id
        assert transaction.amount_cents == -1250
        assert transaction.category == "Dining"
        assert transaction.source == "plaid"
        assert transaction.pending is False

        item = db.scalar(
            select(PlaidItem).where(
                PlaidItem.provider_item_id == "item-sync-1"
            )
        )

        assert item is not None
        assert item.sync_cursor == "cursor-1"
        assert item.last_synced_at is not None


def test_sync_modifies_and_removes_transactions(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    with TestingSessionLocal() as db:
        item = PlaidItem(
            user_id=user_id,
            provider_item_id="item-sync-1",
            access_token_ciphertext="encrypted-token",
            status="active",
            sync_cursor="old-cursor",
        )
        db.add(item)
        db.flush()

        account = FinancialAccount(
            plaid_item_id=item.id,
            provider_account_id="account-sync-1",
            name="Plaid Checking",
            account_type="depository",
            account_subtype="checking",
            currency="USD",
        )
        db.add(account)
        db.flush()

        db.add_all(
            [
                Transaction(
                    user_id=user_id,
                    financial_account_id=account.id,
                    provider_transaction_id="transaction-update",
                    posted_on=date(2026, 7, 20),
                    description="Old Description",
                    amount_cents=-500,
                    category="Uncategorized",
                    source="plaid",
                    pending=True,
                ),
                Transaction(
                    user_id=user_id,
                    financial_account_id=account.id,
                    provider_transaction_id="transaction-remove",
                    posted_on=date(2026, 7, 21),
                    description="Removed Transaction",
                    amount_cents=-700,
                    category="Shopping",
                    source="plaid",
                    pending=False,
                ),
            ]
        )
        db.commit()

    monkeypatch.setattr(
        plaid_router,
        "decrypt_token",
        lambda ciphertext: "access-token",
    )

    monkeypatch.setattr(
        plaid_router,
        "sync_transactions",
        lambda access_token, cursor: PlaidTransactionSyncResult(
            added=[],
            modified=[
                PlaidTransactionData(
                    provider_transaction_id="transaction-update",
                    provider_account_id="account-sync-1",
                    posted_on=date(2026, 7, 30),
                    description="Updated Merchant",
                    merchant_name="Updated Merchant",
                    amount_cents=-2000,
                    category="Shopping",
                    pending=False,
                )
            ],
            removed=["transaction-remove"],
            next_cursor="new-cursor",
        ),
    )

    response = client.post(
        f"/users/{user_id}/plaid/sync",
        headers=auth_headers,
    )

    assert response.status_code == 200

    body = response.json()

    assert body["added"] == 0
    assert body["modified"] == 1
    assert body["removed"] == 1
    assert body["items_synced"] == 1

    with TestingSessionLocal() as db:
        updated = db.scalar(
            select(Transaction).where(
                Transaction.provider_transaction_id
                == "transaction-update"
            )
        )

        removed = db.scalar(
            select(Transaction).where(
                Transaction.provider_transaction_id
                == "transaction-remove"
            )
        )

        item = db.scalar(
            select(PlaidItem).where(
                PlaidItem.provider_item_id == "item-sync-1"
            )
        )

        assert updated is not None
        assert updated.description == "Updated Merchant"
        assert updated.amount_cents == -2000
        assert updated.category == "Shopping"
        assert updated.pending is False
        assert removed is None
        assert item is not None
        assert item.sync_cursor == "new-cursor"


def test_sync_preserves_locked_category(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    with TestingSessionLocal() as db:
        item = PlaidItem(
            user_id=user_id,
            provider_item_id="item-locked-category",
            access_token_ciphertext="encrypted-token",
            status="active",
            sync_cursor="old-cursor",
        )
        db.add(item)
        db.flush()

        account = FinancialAccount(
            plaid_item_id=item.id,
            provider_account_id="account-locked-category",
            name="Plaid Checking",
            account_type="depository",
            account_subtype="checking",
            currency="USD",
        )
        db.add(account)
        db.flush()

        db.add(
            Transaction(
                user_id=user_id,
                financial_account_id=account.id,
                provider_transaction_id="transaction-locked-category",
                posted_on=date(2026, 7, 20),
                description="Original Merchant",
                amount_cents=-1000,
                category="Groceries",
                category_locked=True,
                source="plaid",
                pending=False,
            )
        )
        db.commit()

    monkeypatch.setattr(
        plaid_router,
        "decrypt_token",
        lambda ciphertext: "access-token",
    )

    monkeypatch.setattr(
        plaid_router,
        "sync_transactions",
        lambda access_token, cursor: PlaidTransactionSyncResult(
            added=[],
            modified=[
                PlaidTransactionData(
                    provider_transaction_id=(
                        "transaction-locked-category"
                    ),
                    provider_account_id="account-locked-category",
                    posted_on=date(2026, 7, 30),
                    description="Updated Merchant",
                    merchant_name="Updated Merchant",
                    amount_cents=-2500,
                    category="Shopping",
                    pending=False,
                )
            ],
            removed=[],
            next_cursor="new-cursor",
        ),
    )

    response = client.post(
        f"/users/{user_id}/plaid/sync",
        headers=auth_headers,
    )

    assert response.status_code == 200

    with TestingSessionLocal() as db:
        transaction = db.scalar(
            select(Transaction).where(
                Transaction.provider_transaction_id
                == "transaction-locked-category"
            )
        )

        assert transaction is not None
        assert transaction.category == "Groceries"
        assert transaction.category_locked is True
        assert transaction.description == "Updated Merchant"
        assert transaction.amount_cents == -2500
