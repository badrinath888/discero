from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import get_db
from app.main import app
from app.models import Transaction, User


def add_transactions(
    user_id: int,
    count: int = 3,
    *,
    category: str = "Dining",
) -> list[int]:
    override = app.dependency_overrides[get_db]
    db_generator = override()
    db = next(db_generator)

    try:
        transactions = [
            Transaction(
                user_id=user_id,
                posted_on=date(2026, 8, 20),
                description=f"Bulk transaction {index}",
                amount_cents=-(index + 1) * 100,
                category=category,
                source="csv",
                pending=False,
            )
            for index in range(count)
        ]
        db.add_all(transactions)
        db.commit()
        return [transaction.id for transaction in transactions]
    finally:
        try:
            next(db_generator)
        except StopIteration:
            pass


def transaction_state(transaction_ids: list[int]) -> dict[int, tuple[str, bool]]:
    override = app.dependency_overrides[get_db]
    db_generator = override()
    db = next(db_generator)

    try:
        transactions = db.scalars(
            select(Transaction).where(Transaction.id.in_(transaction_ids))
        ).all()
        return {
            transaction.id: (
                transaction.category,
                transaction.category_locked,
            )
            for transaction in transactions
        }
    finally:
        try:
            next(db_generator)
        except StopIteration:
            pass


def add_other_user_transaction() -> int:
    override = app.dependency_overrides[get_db]
    db_generator = override()
    db = next(db_generator)

    try:
        other_user = User(
            email="bulk-other@example.com",
            password_hash="not-used",
        )
        db.add(other_user)
        db.flush()
        transaction = Transaction(
            user_id=other_user.id,
            posted_on=date(2026, 8, 20),
            description="Other user transaction",
            amount_cents=-500,
            category="Dining",
            source="csv",
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


def test_bulk_category_update_deduplicates_locks_and_preserves_input_order(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    transaction_ids = add_transactions(user_id)
    requested_ids = [
        transaction_ids[2],
        transaction_ids[0],
        transaction_ids[2],
        transaction_ids[1],
    ]

    response = client.patch(
        f"/users/{user_id}/transactions/bulk/category",
        json={
            "transaction_ids": requested_ids,
            "category": "Groceries",
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert [transaction["id"] for transaction in body] == [
        transaction_ids[2],
        transaction_ids[0],
        transaction_ids[1],
    ]
    assert {transaction["category"] for transaction in body} == {
        "Groceries"
    }
    assert transaction_state(transaction_ids) == {
        transaction_id: ("Groceries", True)
        for transaction_id in transaction_ids
    }


def test_bulk_delete_deduplicates_and_deletes_once(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    transaction_ids = add_transactions(user_id)

    response = client.post(
        f"/users/{user_id}/transactions/bulk/delete",
        json={
            "transaction_ids": [
                transaction_ids[1],
                transaction_ids[0],
                transaction_ids[1],
            ]
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json() == {"deleted": 2}
    assert transaction_state(transaction_ids) == {
        transaction_ids[2]: ("Dining", False)
    }


@pytest.mark.parametrize(
    ("transaction_ids", "message"),
    [
        ([], "at least one transaction ID is required"),
        ([0], "transaction IDs must be positive"),
        ([-1], "transaction IDs must be positive"),
        (list(range(1, 102)), "no more than 100 transaction IDs are allowed"),
    ],
)
def test_bulk_transaction_ids_are_validated(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
    transaction_ids: list[int],
    message: str,
) -> None:
    response = client.post(
        f"/users/{user_id}/transactions/bulk/delete",
        json={"transaction_ids": transaction_ids},
        headers=auth_headers,
    )

    assert response.status_code == 422
    assert message in response.text


def test_bulk_category_rejects_blank_category_without_updates(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    transaction_ids = add_transactions(user_id)

    response = client.patch(
        f"/users/{user_id}/transactions/bulk/category",
        json={
            "transaction_ids": transaction_ids,
            "category": "   ",
        },
        headers=auth_headers,
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "category cannot be empty"
    assert transaction_state(transaction_ids) == {
        transaction_id: ("Dining", False)
        for transaction_id in transaction_ids
    }


def test_missing_transaction_causes_no_partial_category_update(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    transaction_ids = add_transactions(user_id)

    response = client.patch(
        f"/users/{user_id}/transactions/bulk/category",
        json={
            "transaction_ids": [transaction_ids[0], 999_999],
            "category": "Groceries",
        },
        headers=auth_headers,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == (
        "one or more transactions were not found"
    )
    assert transaction_state(transaction_ids) == {
        transaction_id: ("Dining", False)
        for transaction_id in transaction_ids
    }


def test_missing_transaction_causes_no_partial_delete(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    transaction_ids = add_transactions(user_id)

    response = client.post(
        f"/users/{user_id}/transactions/bulk/delete",
        json={"transaction_ids": [transaction_ids[0], 999_999]},
        headers=auth_headers,
    )

    assert response.status_code == 404
    assert transaction_state(transaction_ids) == {
        transaction_id: ("Dining", False)
        for transaction_id in transaction_ids
    }


@pytest.mark.parametrize("operation", ["category", "delete"])
def test_cross_user_transaction_causes_full_rollback(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
    operation: str,
) -> None:
    transaction_ids = add_transactions(user_id)
    other_transaction_id = add_other_user_transaction()
    payload: dict[str, object] = {
        "transaction_ids": [transaction_ids[0], other_transaction_id]
    }

    if operation == "category":
        payload["category"] = "Groceries"
        response = client.patch(
            f"/users/{user_id}/transactions/bulk/category",
            json=payload,
            headers=auth_headers,
        )
    else:
        response = client.post(
            f"/users/{user_id}/transactions/bulk/delete",
            json=payload,
            headers=auth_headers,
        )

    assert response.status_code == 404
    assert transaction_state(
        [*transaction_ids, other_transaction_id]
    ) == {
        **{
            transaction_id: ("Dining", False)
            for transaction_id in transaction_ids
        },
        other_transaction_id: ("Dining", False),
    }


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        (
            "patch",
            "category",
            {"transaction_ids": [1], "category": "Groceries"},
        ),
        ("post", "delete", {"transaction_ids": [1]}),
    ],
)
def test_bulk_routes_require_authentication(
    client: TestClient,
    user_id: int,
    method: str,
    path: str,
    payload: dict[str, object],
) -> None:
    response = getattr(client, method)(
        f"/users/{user_id}/transactions/bulk/{path}",
        json=payload,
    )

    assert response.status_code == 401
