from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import PlaidItem, Transaction
from app.services import decision_data_freshness_service
from tests.conftest import TestingSessionLocal
from tests.test_decisions import create_user, register_and_login

TEST_DATE = date(2026, 8, 21)


def _add_transaction(db: Session, user_id: int, posted_on: date) -> None:
    db.add(
        Transaction(
            user_id=user_id,
            posted_on=posted_on,
            description="Test",
            amount_cents=-1000,
        )
    )
    db.commit()


def _add_plaid_item(
    db: Session,
    user_id: int,
    *,
    last_synced_at: datetime | None,
    status: str = "active",
) -> PlaidItem:
    item = PlaidItem(
        user_id=user_id,
        provider_item_id=f"item-{uuid4().hex}",
        institution_name="Test Bank",
        access_token_ciphertext="encrypted-test-token",
        status=status,
        last_synced_at=last_synced_at,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def test_freshness_no_financial_data_is_unavailable() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)

        freshness = decision_data_freshness_service.get_data_freshness(
            db, user.id, as_of=TEST_DATE
        )

        assert freshness.latest_transaction_date is None
        assert freshness.days_since_latest_transaction is None
        assert freshness.account_data_updated_at is None
        assert freshness.freshness_status == "unavailable"


def test_freshness_recent_transaction_is_current() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        _add_transaction(db, user.id, TEST_DATE)

        freshness = decision_data_freshness_service.get_data_freshness(
            db, user.id, as_of=TEST_DATE
        )

        assert freshness.latest_transaction_date == TEST_DATE
        assert freshness.days_since_latest_transaction == 0
        assert freshness.freshness_status == "current"


def test_freshness_stale_transaction_is_stale() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        _add_transaction(db, user.id, TEST_DATE - timedelta(days=45))

        freshness = decision_data_freshness_service.get_data_freshness(
            db, user.id, as_of=TEST_DATE
        )

        assert freshness.days_since_latest_transaction == 45
        assert freshness.freshness_status == "stale"


def test_freshness_uses_most_recent_of_multiple_transactions() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        _add_transaction(db, user.id, TEST_DATE - timedelta(days=20))
        _add_transaction(db, user.id, TEST_DATE - timedelta(days=5))

        freshness = decision_data_freshness_service.get_data_freshness(
            db, user.id, as_of=TEST_DATE
        )

        assert freshness.latest_transaction_date == TEST_DATE - timedelta(
            days=5
        )
        assert freshness.days_since_latest_transaction == 5
        assert freshness.freshness_status == "recent"


def test_freshness_account_timestamp_available() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        _add_plaid_item(
            db,
            user.id,
            last_synced_at=datetime(
                2026, 8, 20, 12, 0, tzinfo=timezone.utc
            ),
        )

        freshness = decision_data_freshness_service.get_data_freshness(
            db, user.id, as_of=TEST_DATE
        )

        assert freshness.account_data_updated_at is not None
        assert freshness.days_since_account_update == 1


def test_freshness_account_timestamp_unavailable() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        _add_plaid_item(db, user.id, last_synced_at=None)

        freshness = decision_data_freshness_service.get_data_freshness(
            db, user.id, as_of=TEST_DATE
        )

        assert freshness.account_data_updated_at is None
        assert freshness.days_since_account_update is None
        assert freshness.freshness_status == "unavailable"


def test_freshness_active_item_contributes_account_sync_freshness() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        _add_plaid_item(
            db,
            user.id,
            status="active",
            last_synced_at=datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc),
        )

        freshness = decision_data_freshness_service.get_data_freshness(
            db, user.id, as_of=TEST_DATE
        )

        assert freshness.account_data_updated_at is not None
        assert freshness.days_since_account_update == 1


def test_freshness_disconnected_item_does_not_count_as_current() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        _add_plaid_item(
            db,
            user.id,
            status="reconnect_required",
            last_synced_at=datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc),
        )

        freshness = decision_data_freshness_service.get_data_freshness(
            db, user.id, as_of=TEST_DATE
        )

        # A disconnected item's historical sync timestamp must never be
        # presented as evidence that account data is currently fresh.
        assert freshness.account_data_updated_at is None
        assert freshness.days_since_account_update is None


def test_freshness_active_and_inactive_items_use_active_timestamp_only() -> (
    None
):
    with TestingSessionLocal() as db:
        user = create_user(db)
        _add_plaid_item(
            db,
            user.id,
            status="reconnect_required",
            last_synced_at=datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc),
        )
        _add_plaid_item(
            db,
            user.id,
            status="active",
            last_synced_at=datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc),
        )

        freshness = decision_data_freshness_service.get_data_freshness(
            db, user.id, as_of=TEST_DATE
        )

        # The disconnected item's timestamp is more recent, but only
        # the active item's timestamp is a truthful sync signal.
        assert freshness.days_since_account_update == 3


def test_freshness_no_active_items_is_truthfully_unavailable() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        _add_plaid_item(
            db,
            user.id,
            status="reconnect_required",
            last_synced_at=datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc),
        )
        _add_transaction(db, user.id, TEST_DATE - timedelta(days=1))

        freshness = decision_data_freshness_service.get_data_freshness(
            db, user.id, as_of=TEST_DATE
        )

        assert freshness.account_data_updated_at is None
        assert freshness.days_since_account_update is None
        # Transaction freshness remains available independently of the
        # disconnected Plaid item -- it's factual transaction history,
        # not synced-account evidence.
        assert freshness.days_since_latest_transaction == 1
        assert freshness.freshness_status == "current"


def test_freshness_factual_age_calculation_is_exact() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        _add_transaction(db, user.id, TEST_DATE - timedelta(days=9))

        freshness = decision_data_freshness_service.get_data_freshness(
            db, user.id, as_of=TEST_DATE
        )

        assert freshness.days_since_latest_transaction == 9
        assert (
            f"through {(TEST_DATE - timedelta(days=9)).isoformat()}"
            in freshness.notices[0]
        )


def test_freshness_date_boundary_never_negative() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        # A transaction dated "in the future" relative to as_of (e.g. a
        # pending/post-dated entry) must never produce a negative age.
        _add_transaction(db, user.id, TEST_DATE + timedelta(days=1))

        freshness = decision_data_freshness_service.get_data_freshness(
            db, user.id, as_of=TEST_DATE
        )

        assert freshness.days_since_latest_transaction == 0


def test_freshness_cross_user_isolation() -> None:
    with TestingSessionLocal() as db:
        user_a = create_user(db)
        user_b = create_user(db)
        _add_transaction(db, user_a.id, TEST_DATE)

        freshness_b = decision_data_freshness_service.get_data_freshness(
            db, user_b.id, as_of=TEST_DATE
        )

        assert freshness_b.latest_transaction_date is None


def test_freshness_never_mutates_data() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        _add_transaction(db, user.id, TEST_DATE - timedelta(days=5))

        decision_data_freshness_service.get_data_freshness(
            db, user.id, as_of=TEST_DATE
        )

        remaining = (
            db.query(Transaction).filter(Transaction.user_id == user.id).all()
        )
        assert len(remaining) == 1
        assert remaining[0].posted_on == TEST_DATE - timedelta(days=5)


# --- HTTP endpoint -------------------------------------------------------


def test_data_freshness_endpoint_requires_authentication(
    client: TestClient,
) -> None:
    response = client.get("/users/9999/decisions/data-freshness")
    assert response.status_code == 401


def test_data_freshness_endpoint_blocks_other_user(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "freshness-owner")

    response = client.get(
        f"/users/{user_id + 1}/decisions/data-freshness", headers=headers
    )

    assert response.status_code == 403


def test_data_freshness_endpoint_returns_facts(client: TestClient) -> None:
    user_id, headers = register_and_login(client, "freshness-http")

    response = client.get(
        f"/users/{user_id}/decisions/data-freshness", headers=headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["freshness_status"] == "unavailable"
    assert "evaluated_at" in body
