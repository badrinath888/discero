from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from threading import Event, Lock

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import FinancialAccount, PlaidItem, Transaction
from app.routers import plaid as plaid_router
from app.services import plaid_service
from app.services.plaid_service import (
    PlaidTransactionData,
    PlaidTransactionSyncResult,
    PlaidServiceError,
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
        assert item.last_sync_attempted_at == item.last_synced_at
        assert item.sync_status == "succeeded"


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


def test_repeated_sync_is_idempotent_and_uses_saved_cursor(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    with TestingSessionLocal() as db:
        item = PlaidItem(
            user_id=user_id,
            provider_item_id="item-repeat",
            access_token_ciphertext="encrypted-token",
            status="active",
        )
        db.add(item)
        db.flush()
        db.add(FinancialAccount(
            plaid_item_id=item.id,
            provider_account_id="account-repeat",
            name="Checking",
            account_type="depository",
            currency="USD",
        ))
        db.commit()

    cursors: list[str | None] = []
    data = PlaidTransactionData(
        provider_transaction_id="transaction-repeat",
        provider_account_id="account-repeat",
        posted_on=date(2026, 8, 3),
        description="Repeat-safe transaction",
        merchant_name=None,
        amount_cents=-1000,
        category="Shopping",
        pending=False,
    )
    monkeypatch.setattr(plaid_router, "decrypt_token", lambda value: "token")

    def sync(access_token: str, cursor: str | None):
        cursors.append(cursor)
        return PlaidTransactionSyncResult(
            added=[data], modified=[], removed=[], next_cursor="cursor-repeat"
        )

    monkeypatch.setattr(plaid_router, "sync_transactions", sync)

    first = client.post(
        f"/users/{user_id}/plaid/sync", headers=auth_headers
    )
    second = client.post(
        f"/users/{user_id}/plaid/sync", headers=auth_headers
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert cursors == [None, "cursor-repeat"]
    with TestingSessionLocal() as db:
        rows = list(db.scalars(select(Transaction)).all())
        assert len(rows) == 1
        assert rows[0].provider_transaction_id == "transaction-repeat"


def test_failed_sync_preserves_cursor_and_success_time_then_retries(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    previous_success = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    with TestingSessionLocal() as db:
        item = PlaidItem(
            user_id=user_id,
            provider_item_id="item-retry",
            access_token_ciphertext="encrypted-token",
            status="active",
            sync_cursor="valid-cursor",
            last_synced_at=previous_success,
        )
        db.add(item)
        db.commit()
        item_id = item.id

    monkeypatch.setattr(plaid_router, "decrypt_token", lambda value: "token")
    attempts = 0

    def sync(access_token: str, cursor: str | None):
        nonlocal attempts
        attempts += 1
        assert cursor == "valid-cursor"
        if attempts == 1:
            raise PlaidServiceError("Unable to synchronize Plaid transactions")
        return PlaidTransactionSyncResult(
            added=[], modified=[], removed=[], next_cursor="retry-cursor"
        )

    monkeypatch.setattr(plaid_router, "sync_transactions", sync)

    failed = client.post(
        f"/users/{user_id}/plaid/sync", headers=auth_headers
    )
    assert failed.status_code == 502

    with TestingSessionLocal() as db:
        item = db.get(PlaidItem, item_id)
        assert item is not None
        assert item.sync_cursor == "valid-cursor"
        assert item.last_synced_at == previous_success.replace(tzinfo=None)
        assert item.last_sync_attempted_at is not None
        assert item.sync_status == "failed"
        assert item.sync_error == "Plaid synchronization failed"

    retried = client.post(
        f"/users/{user_id}/plaid/sync", headers=auth_headers
    )
    assert retried.status_code == 200

    with TestingSessionLocal() as db:
        item = db.get(PlaidItem, item_id)
        assert item is not None
        assert item.sync_cursor == "retry-cursor"
        assert item.sync_status == "succeeded"
        assert item.sync_error is None
        assert item.last_synced_at is not None
        assert item.last_synced_at > previous_success.replace(tzinfo=None)


def test_sync_marks_reconnect_required_without_moving_cursor(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    with TestingSessionLocal() as db:
        item = PlaidItem(
            user_id=user_id,
            provider_item_id="item-login-required",
            access_token_ciphertext="encrypted-token",
            status="active",
            sync_cursor="saved-cursor",
        )
        db.add(item)
        db.commit()
        item_id = item.id

    monkeypatch.setattr(plaid_router, "decrypt_token", lambda value: "token")

    def fail(access_token: str, cursor: str | None):
        raise PlaidServiceError(
            "This institution needs to be reconnected",
            reconnect_required=True,
        )

    monkeypatch.setattr(plaid_router, "sync_transactions", fail)
    response = client.post(
        f"/users/{user_id}/plaid/sync", headers=auth_headers
    )

    assert response.status_code == 502
    with TestingSessionLocal() as db:
        item = db.get(PlaidItem, item_id)
        assert item is not None
        assert item.status == "reconnect_required"
        assert item.sync_status == "failed"
        assert item.sync_error == "Reconnect required"
        assert item.sync_cursor == "saved-cursor"


def test_sync_rejects_an_item_already_being_synchronized(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    with TestingSessionLocal() as db:
        item = PlaidItem(
            user_id=user_id,
            provider_item_id="item-in-progress",
            access_token_ciphertext="encrypted-token",
            status="active",
            sync_status="syncing",
            last_sync_attempted_at=(
                datetime.now(timezone.utc) - timedelta(minutes=5)
            ),
        )
        db.add(item)
        db.commit()
        item_id = item.id

    monkeypatch.setattr(
        plaid_router,
        "sync_transactions",
        lambda access_token, cursor: (_ for _ in ()).throw(
            AssertionError("provider must not be called")
        ),
    )

    response = client.post(
        f"/users/{user_id}/plaid/sync", headers=auth_headers
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Plaid synchronization is already running"
    )

    disconnect = client.delete(
        f"/users/{user_id}/plaid/items/{item_id}", headers=auth_headers
    )
    assert disconnect.status_code == 409
    assert disconnect.json()["detail"] == (
        "Wait for synchronization to finish before disconnecting"
    )


def test_stale_sync_claim_can_be_reclaimed(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    stale_attempt = datetime.now(timezone.utc) - timedelta(minutes=16)
    with TestingSessionLocal() as db:
        item = PlaidItem(
            user_id=user_id,
            provider_item_id="item-stale-reclaim",
            access_token_ciphertext="encrypted-token",
            status="active",
            sync_status="syncing",
            sync_error="Previous synchronization was interrupted",
            last_sync_attempted_at=stale_attempt,
        )
        db.add(item)
        db.commit()
        item_id = item.id

    monkeypatch.setattr(plaid_router, "decrypt_token", lambda value: "token")

    def fail_after_claim(access_token: str, cursor: str | None):
        raise PlaidServiceError("Unable to synchronize Plaid transactions")

    monkeypatch.setattr(plaid_router, "sync_transactions", fail_after_claim)

    response = client.post(
        f"/users/{user_id}/plaid/sync", headers=auth_headers
    )

    assert response.status_code == 502
    with TestingSessionLocal() as db:
        item = db.get(PlaidItem, item_id)
        assert item is not None
        assert item.sync_status == "failed"
        assert item.sync_error == "Plaid synchronization failed"
        assert item.last_sync_attempted_at > stale_attempt.replace(tzinfo=None)


def test_reclaimed_stale_sync_completes_successfully(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    with TestingSessionLocal() as db:
        item = PlaidItem(
            user_id=user_id,
            provider_item_id="item-stale-success",
            access_token_ciphertext="encrypted-token",
            status="active",
            sync_status="syncing",
            sync_cursor="old-cursor",
            last_sync_attempted_at=(
                datetime.now(timezone.utc) - timedelta(minutes=16)
            ),
        )
        db.add(item)
        db.commit()
        item_id = item.id

    monkeypatch.setattr(plaid_router, "decrypt_token", lambda value: "token")
    monkeypatch.setattr(
        plaid_router,
        "sync_transactions",
        lambda access_token, cursor: PlaidTransactionSyncResult(
            added=[], modified=[], removed=[], next_cursor="new-cursor"
        ),
    )

    response = client.post(
        f"/users/{user_id}/plaid/sync", headers=auth_headers
    )

    assert response.status_code == 200
    with TestingSessionLocal() as db:
        item = db.get(PlaidItem, item_id)
        assert item is not None
        assert item.sync_status == "succeeded"
        assert item.sync_error is None
        assert item.sync_cursor == "new-cursor"
        assert item.last_synced_at is not None


def test_competing_requests_cannot_both_reclaim_a_stale_sync(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    with TestingSessionLocal() as db:
        db.add(PlaidItem(
            user_id=user_id,
            provider_item_id="item-stale-race",
            access_token_ciphertext="encrypted-token",
            status="active",
            sync_status="syncing",
            last_sync_attempted_at=(
                datetime.now(timezone.utc) - timedelta(minutes=16)
            ),
        ))
        db.commit()

    entered_provider = Event()
    release_provider = Event()
    calls_lock = Lock()
    provider_calls = 0
    monkeypatch.setattr(plaid_router, "decrypt_token", lambda value: "token")

    def blocking_sync(access_token: str, cursor: str | None):
        nonlocal provider_calls
        with calls_lock:
            provider_calls += 1
        entered_provider.set()
        assert release_provider.wait(timeout=5)
        return PlaidTransactionSyncResult(
            added=[], modified=[], removed=[], next_cursor="race-cursor"
        )

    monkeypatch.setattr(plaid_router, "sync_transactions", blocking_sync)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            client.post,
            f"/users/{user_id}/plaid/sync",
            headers=auth_headers,
        )
        assert entered_provider.wait(timeout=5)
        second = client.post(
            f"/users/{user_id}/plaid/sync", headers=auth_headers
        )
        release_provider.set()
        first_response = first.result(timeout=5)

    assert first_response.status_code == 200
    assert second.status_code == 409
    assert provider_calls == 1


def test_stale_recovery_failure_preserves_cursor_and_previous_success(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    previous_success = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    with TestingSessionLocal() as db:
        item = PlaidItem(
            user_id=user_id,
            provider_item_id="item-stale-metadata",
            access_token_ciphertext="encrypted-token",
            status="active",
            sync_status="syncing",
            sync_cursor="safe-cursor",
            last_synced_at=previous_success,
            last_sync_attempted_at=(
                datetime.now(timezone.utc) - timedelta(minutes=16)
            ),
        )
        db.add(item)
        db.commit()
        item_id = item.id

    monkeypatch.setattr(plaid_router, "decrypt_token", lambda value: "token")

    def fail(access_token: str, cursor: str | None):
        assert cursor == "safe-cursor"
        raise PlaidServiceError("Unable to synchronize Plaid transactions")

    monkeypatch.setattr(plaid_router, "sync_transactions", fail)
    response = client.post(
        f"/users/{user_id}/plaid/sync", headers=auth_headers
    )

    assert response.status_code == 502
    with TestingSessionLocal() as db:
        item = db.get(PlaidItem, item_id)
        assert item is not None
        assert item.sync_cursor == "safe-cursor"
        assert item.last_synced_at == previous_success.replace(tzinfo=None)
        assert item.sync_status == "failed"
        assert item.sync_error == "Plaid synchronization failed"


def test_sync_status_is_safe_owner_scoped_and_authenticated(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    with TestingSessionLocal() as db:
        db.add(PlaidItem(
            user_id=user_id,
            provider_item_id="item-status",
            institution_name="Status Bank",
            access_token_ciphertext="encrypted-secret-token",
            status="active",
            sync_status="failed",
            sync_error="Plaid synchronization failed",
        ))
        db.commit()

    unauthenticated = client.get(f"/users/{user_id}/plaid/sync/status")
    forbidden = client.get(
        f"/users/{user_id + 1}/plaid/sync/status", headers=auth_headers
    )
    response = client.get(
        f"/users/{user_id}/plaid/sync/status", headers=auth_headers
    )

    assert unauthenticated.status_code == 401
    assert forbidden.status_code == 403
    assert response.status_code == 200
    assert response.json()["items"][0]["sync_status"] == "failed"
    serialized = str(response.json())
    assert "encrypted-secret-token" not in serialized
    assert "sync_cursor" not in serialized


def test_plaid_service_uses_each_page_cursor_and_returns_final_cursor(
    monkeypatch,
) -> None:
    requests: list[str | None] = []
    responses = iter([
        {
            "added": [],
            "modified": [],
            "removed": [],
            "next_cursor": "page-cursor",
            "has_more": True,
        },
        {
            "added": [],
            "modified": [],
            "removed": [],
            "next_cursor": "final-cursor",
            "has_more": False,
        },
    ])

    class FakeClient:
        def transactions_sync(self, request):
            requests.append(request.cursor)
            return next(responses)

    monkeypatch.setattr(
        plaid_service, "get_plaid_client", lambda settings: FakeClient()
    )

    result = plaid_service.sync_transactions("access-token", "saved-cursor")

    assert requests == ["saved-cursor", "page-cursor"]
    assert result.next_cursor == "final-cursor"
