from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import get_db
from app.main import app
from app.models import Transaction, User


def transaction_row(transaction_id: int) -> Transaction:
    override = app.dependency_overrides[get_db]
    db_generator = override()
    db = next(db_generator)

    try:
        transaction = db.scalar(
            select(Transaction).where(Transaction.id == transaction_id)
        )
        assert transaction is not None
        db.refresh(transaction)
        return transaction
    finally:
        try:
            next(db_generator)
        except StopIteration:
            pass


def add_transaction(
    user_id: int,
    *,
    posted_on: date = date(2026, 8, 1),
    description: str = "Existing transaction",
    amount_cents: int = -1_500,
    category: str = "Dining",
    source: str = "csv",
) -> int:
    override = app.dependency_overrides[get_db]
    db_generator = override()
    db = next(db_generator)

    try:
        transaction = Transaction(
            user_id=user_id,
            posted_on=posted_on,
            description=description,
            amount_cents=amount_cents,
            category=category,
            source=source,
            pending=False,
        )
        db.add(transaction)
        db.commit()
        return transaction.id
    finally:
        try:
            next(db_generator)
        except StopIteration:
            pass


def add_other_user(client: TestClient) -> tuple[int, dict[str, str]]:
    response = client.post(
        "/users",
        json={
            "email": "other-edit@example.com",
            "password": "TestPassword123!",
        },
    )
    assert response.status_code == 201
    other_user_id = response.json()["id"]

    login = client.post(
        "/users/login",
        json={
            "email": "other-edit@example.com",
            "password": "TestPassword123!",
        },
    )
    assert login.status_code == 200
    token = login.json()["access_token"]

    return other_user_id, {"Authorization": f"Bearer {token}"}


class TestCreateTransaction:
    def test_creates_manual_transaction_with_expected_fields(
        self,
        client: TestClient,
        user_id: int,
        auth_headers: dict[str, str],
    ) -> None:
        response = client.post(
            f"/users/{user_id}/transactions",
            json={
                "posted_on": "2026-08-01",
                "description": "Cash tip",
                "merchant_name": "  Local Diner  ",
                "amount_cents": -1_200,
                "category": "Dining",
            },
            headers=auth_headers,
        )

        assert response.status_code == 201
        body = response.json()
        assert body["description"] == "Cash tip"
        assert body["merchant_name"] == "Local Diner"
        assert body["amount_cents"] == -1_200
        assert body["category"] == "Dining"
        assert body["source"] == "manual"
        assert body["pending"] is False
        assert body["financial_account_id"] is None

        row = transaction_row(body["id"])
        assert row.category_locked is True

    def test_defaults_category_to_uncategorized(
        self,
        client: TestClient,
        user_id: int,
        auth_headers: dict[str, str],
    ) -> None:
        response = client.post(
            f"/users/{user_id}/transactions",
            json={
                "posted_on": "2026-08-01",
                "description": "Unlabeled expense",
                "amount_cents": -500,
            },
            headers=auth_headers,
        )

        assert response.status_code == 201
        assert response.json()["category"] == "Uncategorized"
        assert response.json()["merchant_name"] is None

    def test_blank_merchant_name_normalizes_to_null(
        self,
        client: TestClient,
        user_id: int,
        auth_headers: dict[str, str],
    ) -> None:
        response = client.post(
            f"/users/{user_id}/transactions",
            json={
                "posted_on": "2026-08-01",
                "description": "Blank merchant",
                "merchant_name": "   ",
                "amount_cents": -500,
            },
            headers=auth_headers,
        )

        assert response.status_code == 201
        assert response.json()["merchant_name"] is None

    @pytest.mark.parametrize(
        "payload",
        [
            {
                "posted_on": "2026-08-01",
                "description": "Zero amount",
                "amount_cents": 0,
            },
            {
                "posted_on": "2026-08-01",
                "description": "   ",
                "amount_cents": -500,
            },
            {
                "posted_on": "2026-08-01",
                "description": "Blank category",
                "amount_cents": -500,
                "category": "   ",
            },
        ],
    )
    def test_rejects_invalid_payloads(
        self,
        client: TestClient,
        user_id: int,
        auth_headers: dict[str, str],
        payload: dict,
    ) -> None:
        response = client.post(
            f"/users/{user_id}/transactions",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 422

    def test_cannot_create_transaction_for_another_user(
        self,
        client: TestClient,
        user_id: int,
        auth_headers: dict[str, str],
    ) -> None:
        other_user_id, _ = add_other_user(client)

        response = client.post(
            f"/users/{other_user_id}/transactions",
            json={
                "posted_on": "2026-08-01",
                "description": "Cross-user attempt",
                "amount_cents": -500,
            },
            headers=auth_headers,
        )

        assert response.status_code == 403


class TestUpdateTransaction:
    def test_category_only_update_preserves_existing_behavior(
        self,
        client: TestClient,
        user_id: int,
        auth_headers: dict[str, str],
    ) -> None:
        transaction_id = add_transaction(user_id)

        response = client.patch(
            f"/users/{user_id}/transactions/{transaction_id}",
            json={"category": "Groceries"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["category"] == "Groceries"
        assert body["description"] == "Existing transaction"
        assert transaction_row(transaction_id).category_locked is True

    def test_full_edit_updates_every_provided_field(
        self,
        client: TestClient,
        user_id: int,
        auth_headers: dict[str, str],
    ) -> None:
        transaction_id = add_transaction(user_id)

        response = client.patch(
            f"/users/{user_id}/transactions/{transaction_id}",
            json={
                "posted_on": "2026-08-15",
                "description": "Updated description",
                "merchant_name": "New Merchant",
                "amount_cents": 4_200,
                "category": "Income",
            },
            headers=auth_headers,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["posted_on"] == "2026-08-15"
        assert body["description"] == "Updated description"
        assert body["merchant_name"] == "New Merchant"
        assert body["amount_cents"] == 4_200
        assert body["category"] == "Income"

    def test_partial_edit_only_changes_provided_fields(
        self,
        client: TestClient,
        user_id: int,
        auth_headers: dict[str, str],
    ) -> None:
        transaction_id = add_transaction(
            user_id,
            description="Original description",
            amount_cents=-750,
        )

        response = client.patch(
            f"/users/{user_id}/transactions/{transaction_id}",
            json={"amount_cents": -900},
            headers=auth_headers,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["amount_cents"] == -900
        assert body["description"] == "Original description"
        assert body["category"] == "Dining"

    def test_rejects_empty_payload(
        self,
        client: TestClient,
        user_id: int,
        auth_headers: dict[str, str],
    ) -> None:
        transaction_id = add_transaction(user_id)

        response = client.patch(
            f"/users/{user_id}/transactions/{transaction_id}",
            json={},
            headers=auth_headers,
        )

        assert response.status_code == 422

    def test_rejects_zero_amount(
        self,
        client: TestClient,
        user_id: int,
        auth_headers: dict[str, str],
    ) -> None:
        transaction_id = add_transaction(user_id)

        response = client.patch(
            f"/users/{user_id}/transactions/{transaction_id}",
            json={"amount_cents": 0},
            headers=auth_headers,
        )

        assert response.status_code == 422

    def test_rejects_blank_description(
        self,
        client: TestClient,
        user_id: int,
        auth_headers: dict[str, str],
    ) -> None:
        transaction_id = add_transaction(user_id)

        response = client.patch(
            f"/users/{user_id}/transactions/{transaction_id}",
            json={"description": "   "},
            headers=auth_headers,
        )

        assert response.status_code == 422

    def test_returns_404_for_missing_transaction(
        self,
        client: TestClient,
        user_id: int,
        auth_headers: dict[str, str],
    ) -> None:
        response = client.patch(
            f"/users/{user_id}/transactions/999999",
            json={"category": "Groceries"},
            headers=auth_headers,
        )

        assert response.status_code == 404

    def test_cannot_edit_another_users_transaction(
        self,
        client: TestClient,
        user_id: int,
        auth_headers: dict[str, str],
    ) -> None:
        other_user_id, other_headers = add_other_user(client)
        other_transaction_id = add_transaction(
            other_user_id,
            description="Belongs to other user",
        )

        cross_user_path_response = client.patch(
            f"/users/{other_user_id}/transactions/{other_transaction_id}",
            json={"category": "Groceries"},
            headers=auth_headers,
        )
        assert cross_user_path_response.status_code == 403

        wrong_owner_response = client.patch(
            f"/users/{user_id}/transactions/{other_transaction_id}",
            json={"category": "Groceries"},
            headers=other_headers,
        )
        assert wrong_owner_response.status_code == 403

        same_user_wrong_transaction_response = client.patch(
            f"/users/{user_id}/transactions/{other_transaction_id}",
            json={"category": "Groceries"},
            headers=auth_headers,
        )
        assert same_user_wrong_transaction_response.status_code == 404


class TestDeleteTransaction:
    def test_deletes_owned_transaction(
        self,
        client: TestClient,
        user_id: int,
        auth_headers: dict[str, str],
    ) -> None:
        transaction_id = add_transaction(user_id)

        response = client.delete(
            f"/users/{user_id}/transactions/{transaction_id}",
            headers=auth_headers,
        )

        assert response.status_code == 204

        follow_up = client.patch(
            f"/users/{user_id}/transactions/{transaction_id}",
            json={"category": "Groceries"},
            headers=auth_headers,
        )
        assert follow_up.status_code == 404

    def test_returns_404_for_missing_transaction(
        self,
        client: TestClient,
        user_id: int,
        auth_headers: dict[str, str],
    ) -> None:
        response = client.delete(
            f"/users/{user_id}/transactions/999999",
            headers=auth_headers,
        )

        assert response.status_code == 404

    def test_cannot_delete_another_users_transaction(
        self,
        client: TestClient,
        user_id: int,
        auth_headers: dict[str, str],
    ) -> None:
        other_user_id, _ = add_other_user(client)
        other_transaction_id = add_transaction(other_user_id)

        response = client.delete(
            f"/users/{user_id}/transactions/{other_transaction_id}",
            headers=auth_headers,
        )

        assert response.status_code == 404
