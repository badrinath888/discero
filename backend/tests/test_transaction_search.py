from datetime import date

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models import Transaction


def seed_transactions(user_id: int) -> None:
    override = app.dependency_overrides[get_db]
    db_generator = override()
    db = next(db_generator)

    try:
        db.add_all(
            [
                Transaction(
                    user_id=user_id,
                    posted_on=date(2026, 8, 6),
                    description="ACME PAYROLL",
                    merchant_name="Acme",
                    amount_cents=250000,
                    category="Income",
                    source="plaid",
                    pending=False,
                ),
                Transaction(
                    user_id=user_id,
                    posted_on=date(2026, 8, 5),
                    description="COFFEE SHOP",
                    merchant_name="North Coffee",
                    amount_cents=-725,
                    category="Dining",
                    source="plaid",
                    pending=True,
                ),
                Transaction(
                    user_id=user_id,
                    posted_on=date(2026, 8, 4),
                    description="WHOLE FOODS",
                    merchant_name="Whole Foods",
                    amount_cents=-5210,
                    category="Groceries",
                    source="csv",
                    pending=False,
                ),
                Transaction(
                    user_id=user_id,
                    posted_on=date(2026, 8, 3),
                    description="CITY ELECTRIC",
                    merchant_name="City Electric",
                    amount_cents=-8400,
                    category="Utilities",
                    source="csv",
                    pending=False,
                ),
                Transaction(
                    user_id=user_id,
                    posted_on=date(2026, 8, 2),
                    description="UBER TRIP",
                    merchant_name="Uber",
                    amount_cents=-2490,
                    category="Transport",
                    source="plaid",
                    pending=False,
                ),
            ]
        )
        db.commit()
    finally:
        try:
            next(db_generator)
        except StopIteration:
            pass


def test_transaction_search_paginates_and_summarizes(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    seed_transactions(user_id)

    response = client.get(
        f"/users/{user_id}/transactions/search",
        params={"page": 1, "page_size": 2},
        headers=auth_headers,
    )

    assert response.status_code == 200
    body = response.json()

    assert body["total"] == 5
    assert body["page"] == 1
    assert body["page_size"] == 2
    assert body["total_pages"] == 3
    assert len(body["items"]) == 2
    assert body["items"][0]["description"] == "ACME PAYROLL"
    assert body["items"][1]["description"] == "COFFEE SHOP"
    assert body["total_income_cents"] == 250000
    assert body["total_spending_cents"] == 16825
    assert body["net_cents"] == 233175


def test_transaction_search_filters(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    seed_transactions(user_id)

    response = client.get(
        f"/users/{user_id}/transactions/search",
        params={
            "search": "coffee",
            "source": "plaid",
            "pending": "true",
            "transaction_type": "spending",
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    body = response.json()

    assert body["total"] == 1
    assert body["items"][0]["merchant_name"] == "North Coffee"
    assert body["total_income_cents"] == 0
    assert body["total_spending_cents"] == 725
    assert body["net_cents"] == -725


def test_transaction_search_filters_dates_and_category(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    seed_transactions(user_id)

    response = client.get(
        f"/users/{user_id}/transactions/search",
        params={
            "category": "Groceries",
            "start_date": "2026-08-04",
            "end_date": "2026-08-04",
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    body = response.json()

    assert body["total"] == 1
    assert body["items"][0]["description"] == "WHOLE FOODS"


def test_transaction_search_rejects_invalid_date_range(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    response = client.get(
        f"/users/{user_id}/transactions/search",
        params={
            "start_date": "2026-08-10",
            "end_date": "2026-08-01",
        },
        headers=auth_headers,
    )

    assert response.status_code == 422
    assert (
        response.json()["detail"]
        == "start_date cannot be after end_date"
    )
