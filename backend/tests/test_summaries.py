import io

from fastapi.testclient import TestClient

from app.models import FinancialAccount, PlaidItem
from tests.conftest import TestingSessionLocal


def _upload(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
    csv_text: str,
) -> None:
    files = {
        "file": (
            "t.csv",
            io.BytesIO(csv_text.encode()),
            "text/csv",
        )
    }

    response = client.post(
        f"/users/{user_id}/transactions/upload",
        files=files,
        headers=auth_headers,
    )

    assert response.status_code == 200


def test_overview(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    _upload(
        client,
        user_id,
        auth_headers,
        "date,description,amount\n"
        "2026-01-06,ACME Payroll,2000.00\n"
        "2026-01-07,Whole Foods,-150.00\n"
        "2026-01-08,Rent,-850.00\n",
    )

    response = client.get(
        f"/users/{user_id}/summary/overview",
        headers=auth_headers,
    )

    assert response.status_code == 200

    overview = response.json()

    assert overview["total_income_cents"] == 200000
    assert overview["total_spending_cents"] == 100000
    assert overview["net_cents"] == 100000
    assert overview["transaction_count"] == 3


def test_by_month(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    _upload(
        client,
        user_id,
        auth_headers,
        "date,description,amount\n"
        "2026-01-06,ACME Payroll,2000.00\n"
        "2026-01-20,Whole Foods,-100.00\n"
        "2026-02-06,ACME Payroll,2000.00\n"
        "2026-02-15,Rent,-850.00\n",
    )

    response = client.get(
        f"/users/{user_id}/summary/by-month",
        headers=auth_headers,
    )

    assert response.status_code == 200

    months = response.json()

    assert [month["month"] for month in months] == [
        "2026-01",
        "2026-02",
    ]

    january = months[0]

    assert january["income_cents"] == 200000
    assert january["spending_cents"] == 10000
    assert january["net_cents"] == 190000

    february = months[1]

    assert february["income_cents"] == 200000
    assert february["spending_cents"] == 85000
    assert february["net_cents"] == 115000


def test_summaries_require_authentication(
    client: TestClient,
) -> None:
    overview = client.get(
        "/users/999/summary/overview"
    )

    by_month = client.get(
        "/users/999/summary/by-month"
    )

    assert overview.status_code == 401
    assert by_month.status_code == 401


def test_cross_user_summary_access_rejected(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    response = client.get(
        f"/users/{user_id + 1}/summary/overview",
        headers=auth_headers,
    )

    assert response.status_code == 403

def test_monthly_insights_compare_spending(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    _upload(
        client,
        user_id,
        auth_headers,
        "date,description,amount,category\n"
        "2026-01-05,Payroll,3000.00,Income\n"
        "2026-01-10,Restaurant,-100.00,Dining\n"
        "2026-02-05,Payroll,3000.00,Income\n"
        "2026-02-10,Restaurant,-150.00,Dining\n"
        "2026-02-12,Rent,-1000.00,Housing\n",
    )

    response = client.get(
        f"/users/{user_id}/summary/insights",
        params={"month": "2026-02"},
        headers=auth_headers,
    )

    assert response.status_code == 200

    body = response.json()

    assert body["month"] == "2026-02"
    assert body["previous_month"] == "2026-01"
    assert body["income_cents"] == 300000
    assert body["spending_cents"] == 115000
    assert body["net_cents"] == 185000
    assert body["spending_change_cents"] == 105000
    assert body["spending_change_percent"] == 1050.0
    assert body["savings_rate_percent"] == 61.7

    kinds = {
        insight["kind"]
        for insight in body["insights"]
    }

    assert "highest_category" in kinds
    assert "monthly_spending_change" in kinds
    assert "category_increase" in kinds
    assert "savings_rate" in kinds


def test_monthly_insights_without_previous_history(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    _upload(
        client,
        user_id,
        auth_headers,
        "date,description,amount,category\n"
        "2026-03-05,Payroll,2000.00,Income\n"
        "2026-03-10,Groceries,-400.00,Groceries\n",
    )

    response = client.get(
        f"/users/{user_id}/summary/insights",
        params={"month": "2026-03"},
        headers=auth_headers,
    )

    assert response.status_code == 200

    body = response.json()

    assert body["spending_change_percent"] is None
    assert body["savings_rate_percent"] == 80.0


def test_monthly_insights_reject_invalid_month(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    response = client.get(
        f"/users/{user_id}/summary/insights",
        params={"month": "2026-13"},
        headers=auth_headers,
    )

    assert response.status_code == 422


def test_monthly_insights_require_authentication(
    client: TestClient,
    user_id: int,
) -> None:
    response = client.get(
        f"/users/{user_id}/summary/insights",
        params={"month": "2026-02"},
    )

    assert response.status_code == 401


def test_monthly_insights_reject_cross_user_access(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    response = client.get(
        f"/users/{user_id + 1}/summary/insights",
        params={"month": "2026-02"},
        headers=auth_headers,
    )

    assert response.status_code == 403


def test_cash_flow_forecast_uses_liquid_account_balance(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    with TestingSessionLocal() as db:
        item = PlaidItem(
            user_id=user_id,
            provider_item_id="forecast-item",
            institution_id="ins_forecast",
            institution_name="Forecast Bank",
            access_token_ciphertext="encrypted",
            status="active",
        )
        db.add(item)
        db.flush()

        db.add(
            FinancialAccount(
                plaid_item_id=item.id,
                provider_account_id="forecast-checking",
                name="Checking",
                account_type="depository",
                account_subtype="checking",
                current_balance_cents=125000,
                available_balance_cents=120000,
                currency="USD",
            )
        )
        db.commit()

    response = client.get(
        f"/users/{user_id}/summary/cash-flow-forecast",
        params={"as_of": "2026-02-28"},
        headers=auth_headers,
    )

    assert response.status_code == 200

    body = response.json()

    assert body["as_of"] == "2026-02-28"
    assert body["month_end"] == "2026-02-28"
    assert body["days_remaining"] == 0
    assert body["liquid_balance_cents"] == 120000
    assert body["expected_income_cents"] == 0
    assert body["upcoming_bills_cents"] == 0
    assert body["projected_end_balance_cents"] == 120000
    assert body["low_balance_risk"] is False


def test_cash_flow_forecast_estimates_remaining_income(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    _upload(
        client,
        user_id,
        auth_headers,
        "date,description,amount,category\n"
        "2026-02-01,Payroll,1000.00,Income\n",
    )

    response = client.get(
        f"/users/{user_id}/summary/cash-flow-forecast",
        params={"as_of": "2026-02-10"},
        headers=auth_headers,
    )

    assert response.status_code == 200

    body = response.json()

    assert body["income_received_cents"] == 100000
    assert body["days_remaining"] == 18
    assert body["expected_income_cents"] == 180000
    assert body["projected_end_balance_cents"] == 180000
    assert body["low_balance_risk"] is False


def test_cash_flow_forecast_detects_low_balance_risk(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    _upload(
        client,
        user_id,
        auth_headers,
        "date,description,amount,category\n"
        "2026-01-20,Streaming Service,-25.00,Subscriptions\n"
        "2026-01-27,Streaming Service,-25.00,Subscriptions\n"
        "2026-02-03,Streaming Service,-25.00,Subscriptions\n",
    )

    response = client.get(
        f"/users/{user_id}/summary/cash-flow-forecast",
        params={"as_of": "2026-02-04"},
        headers=auth_headers,
    )

    assert response.status_code == 200

    body = response.json()

    assert body["liquid_balance_cents"] == 0
    assert body["expected_income_cents"] == 0
    assert body["upcoming_bills_cents"] == 2500
    assert body["projected_end_balance_cents"] == -2500
    assert body["low_balance_risk"] is True

    assert len(body["upcoming_cash_flows"]) == 1

    upcoming = body["upcoming_cash_flows"][0]

    assert upcoming["merchant"] == "Streaming Service"
    assert upcoming["amount_cents"] == 2500
    assert upcoming["expected_date"] == "2026-02-10"
    assert upcoming["kind"] == "expense"
    assert upcoming["confidence_score"] >= 60


def test_cash_flow_forecast_requires_authentication(
    client: TestClient,
    user_id: int,
) -> None:
    response = client.get(
        f"/users/{user_id}/summary/cash-flow-forecast",
        params={"as_of": "2026-02-10"},
    )

    assert response.status_code == 401


def test_cash_flow_forecast_rejects_cross_user_access(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    response = client.get(
        f"/users/{user_id + 1}/summary/cash-flow-forecast",
        params={"as_of": "2026-02-10"},
        headers=auth_headers,
    )

    assert response.status_code == 403


def test_cash_flow_forecast_rejects_invalid_date(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    response = client.get(
        f"/users/{user_id}/summary/cash-flow-forecast",
        params={"as_of": "not-a-date"},
        headers=auth_headers,
    )

    assert response.status_code == 422
