from datetime import date

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models import FinancialAccount, PlaidItem, Transaction, User


def add_transactions(transactions: list[Transaction]) -> None:
    override = app.dependency_overrides[get_db]
    db_generator = override()
    db = next(db_generator)

    try:
        db.add_all(transactions)
        db.commit()
    finally:
        try:
            next(db_generator)
        except StopIteration:
            pass


def seed_transactions(user_id: int) -> None:
    add_transactions(
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


def test_duplicate_filter_omitted_and_false_are_unchanged(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    seed_transactions(user_id)

    omitted = client.get(
        f"/users/{user_id}/transactions/search",
        headers=auth_headers,
    )
    disabled = client.get(
        f"/users/{user_id}/transactions/search",
        params={"duplicates_only": "false"},
        headers=auth_headers,
    )

    assert omitted.status_code == 200
    assert disabled.status_code == 200
    assert disabled.json() == omitted.json()


def test_duplicate_filter_returns_all_group_members_once_with_totals(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    add_transactions(
        [
            Transaction(
                user_id=user_id,
                posted_on=date(2026, 8, 10),
                description="Coffee purchase one",
                merchant_name="  North Coffee  ",
                amount_cents=-725,
                category="Dining",
                source="csv",
                pending=False,
            ),
            Transaction(
                user_id=user_id,
                posted_on=date(2026, 8, 10),
                description="Coffee purchase two",
                merchant_name="north coffee",
                amount_cents=-725,
                category="Dining",
                source="plaid",
                pending=False,
            ),
            Transaction(
                user_id=user_id,
                posted_on=date(2026, 8, 10),
                description="Coffee purchase three",
                merchant_name="NORTH COFFEE",
                amount_cents=-725,
                category="Dining",
                source="plaid",
                pending=False,
            ),
            Transaction(
                user_id=user_id,
                posted_on=date(2026, 8, 10),
                description="ACME PAYROLL",
                merchant_name="Acme",
                amount_cents=250000,
                category="Income",
                source="csv",
                pending=False,
            ),
            Transaction(
                user_id=user_id,
                posted_on=date(2026, 8, 10),
                description="Different amount",
                merchant_name="North Coffee",
                amount_cents=-700,
                category="Dining",
                source="csv",
                pending=False,
            ),
            Transaction(
                user_id=user_id,
                posted_on=date(2026, 8, 13),
                description="Outside the 1-day window",
                merchant_name="North Coffee",
                amount_cents=-725,
                category="Dining",
                source="csv",
                pending=False,
            ),
        ]
    )

    response = client.get(
        f"/users/{user_id}/transactions/search",
        params={"duplicates_only": "true", "page_size": 2},
        headers=auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["total_pages"] == 2
    assert len(body["items"]) == 2
    assert len({item["id"] for item in body["items"]}) == 2
    assert body["total_income_cents"] == 0
    assert body["total_spending_cents"] == 2175
    assert body["net_cents"] == -2175

    second_page = client.get(
        f"/users/{user_id}/transactions/search",
        params={
            "duplicates_only": "true",
            "page": 2,
            "page_size": 2,
        },
        headers=auth_headers,
    )
    assert second_page.status_code == 200
    assert len(second_page.json()["items"]) == 1


def test_duplicate_filter_matches_same_merchant_and_amount_one_day_apart(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    add_transactions(
        [
            Transaction(
                user_id=user_id,
                posted_on=date(2026, 7, 14),
                description="REI purchase",
                merchant_name="Rei",
                amount_cents=-6430,
                category="Shopping",
                source="plaid",
                pending=False,
            ),
            Transaction(
                user_id=user_id,
                posted_on=date(2026, 7, 15),
                description="REI purchase",
                merchant_name="Rei",
                amount_cents=-6430,
                category="Shopping",
                source="plaid",
                pending=False,
            ),
            Transaction(
                user_id=user_id,
                posted_on=date(2026, 7, 17),
                description="REI purchase, outside window",
                merchant_name="Rei",
                amount_cents=-6430,
                category="Shopping",
                source="plaid",
                pending=False,
            ),
        ]
    )

    response = client.get(
        f"/users/{user_id}/transactions/search",
        params={"duplicates_only": "true"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert {item["posted_on"] for item in body["items"]} == {
        "2026-07-14",
        "2026-07-15",
    }


def test_duplicate_filter_falls_back_to_description_for_blank_merchant(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    add_transactions(
        [
            Transaction(
                user_id=user_id,
                posted_on=date(2026, 8, 12),
                description="  CORNER MARKET  ",
                merchant_name=None,
                amount_cents=-4200,
                category="Groceries",
                source="csv",
                pending=False,
            ),
            Transaction(
                user_id=user_id,
                posted_on=date(2026, 8, 12),
                description="corner market",
                merchant_name="   ",
                amount_cents=-4200,
                category="Groceries",
                source="csv",
                pending=False,
            ),
        ]
    )

    response = client.get(
        f"/users/{user_id}/transactions/search",
        params={"duplicates_only": "true"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["total"] == 2


def test_duplicate_filter_does_not_match_a_transaction_to_itself(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    add_transactions(
        [
            Transaction(
                user_id=user_id,
                posted_on=date(2026, 8, 12),
                description="ONLY TRANSACTION",
                merchant_name="Only Merchant",
                amount_cents=-1234,
                category="Shopping",
                source="csv",
                pending=False,
            )
        ]
    )

    response = client.get(
        f"/users/{user_id}/transactions/search",
        params={"duplicates_only": "true"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["total"] == 0


def test_duplicate_filter_prefers_merchant_over_matching_description(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    add_transactions(
        [
            Transaction(
                user_id=user_id,
                posted_on=date(2026, 8, 13),
                description="SAME DESCRIPTION",
                merchant_name="Merchant One",
                amount_cents=-1800,
                category="Shopping",
                source="csv",
                pending=False,
            ),
            Transaction(
                user_id=user_id,
                posted_on=date(2026, 8, 13),
                description="SAME DESCRIPTION",
                merchant_name="Merchant Two",
                amount_cents=-1800,
                category="Shopping",
                source="csv",
                pending=False,
            ),
        ]
    )

    response = client.get(
        f"/users/{user_id}/transactions/search",
        params={"duplicates_only": "true"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["total"] == 0


def test_duplicate_filter_isolates_users(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    override = app.dependency_overrides[get_db]
    db_generator = override()
    db = next(db_generator)

    try:
        other_user = User(
            email="duplicate-other@example.com",
            password_hash="not-used",
        )
        db.add(other_user)
        db.flush()
        db.add_all(
            [
                Transaction(
                    user_id=user_id,
                    posted_on=date(2026, 8, 14),
                    description="Shared merchant",
                    merchant_name="Shared Merchant",
                    amount_cents=-9900,
                    category="Shopping",
                    source="csv",
                    pending=False,
                ),
                Transaction(
                    user_id=other_user.id,
                    posted_on=date(2026, 8, 14),
                    description="Shared merchant",
                    merchant_name="Shared Merchant",
                    amount_cents=-9900,
                    category="Shopping",
                    source="csv",
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

    response = client.get(
        f"/users/{user_id}/transactions/search",
        params={"duplicates_only": "true"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["total"] == 0


def test_duplicate_filter_combines_with_existing_filters(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    override = app.dependency_overrides[get_db]
    db_generator = override()
    db = next(db_generator)

    try:
        item = PlaidItem(
            user_id=user_id,
            provider_item_id="duplicate-filter-item",
            institution_name="Test Bank",
            access_token_ciphertext="encrypted",
            status="active",
        )
        db.add(item)
        db.flush()
        account = FinancialAccount(
            plaid_item_id=item.id,
            provider_account_id="duplicate-filter-account",
            name="Checking",
            account_type="depository",
            currency="USD",
        )
        db.add(account)
        db.flush()
        db.add_all(
            [
                Transaction(
                    user_id=user_id,
                    financial_account_id=account.id,
                    posted_on=date(2026, 8, 15),
                    description="TARGET PAYMENT A",
                    merchant_name="Target Merchant",
                    amount_cents=-3200,
                    category="Dining",
                    source="plaid",
                    pending=True,
                ),
                Transaction(
                    user_id=user_id,
                    posted_on=date(2026, 8, 15),
                    description="TARGET PAYMENT B",
                    merchant_name="Target Merchant",
                    amount_cents=-3200,
                    category="Dining",
                    source="csv",
                    pending=False,
                ),
            ]
        )
        db.commit()
        account_id = account.id
    finally:
        try:
            next(db_generator)
        except StopIteration:
            pass

    response = client.get(
        f"/users/{user_id}/transactions/search",
        params={
            "duplicates_only": "true",
            "search": "target",
            "category": "Dining",
            "source": "plaid",
            "account_id": account_id,
            "start_date": "2026-08-15",
            "end_date": "2026-08-15",
            "pending": "true",
            "transaction_type": "spending",
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["source"] == "plaid"
    assert body["items"][0]["financial_account_id"] == account_id
    assert body["total_spending_cents"] == 3200
