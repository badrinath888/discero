import io
from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.models import FinancialAccount, PlaidItem, RecurringItem
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

    horizons = {h["horizon_days"]: h for h in body["horizon_outlook"]}
    assert set(horizons) == {30, 60, 90}

    for horizon_days, horizon in horizons.items():
        assert horizon["expected_income_cents"] == 0
        assert horizon["known_obligations_cents"] == 0
        assert horizon["projected_balance_cents"] == 120000
        assert horizon["shortfall_cents"] == 0
        # Blended with the overall forecast confidence (which factors
        # in income consistency / transaction history / data
        # freshness) -- no transaction history at all correctly pulls
        # this below the obligations-only 88.0 it used to show.
        assert horizon["confidence_score"] == 62.4
        assert horizon["through_date"] == (
            date(2026, 2, 28) + timedelta(days=horizon_days)
        ).isoformat()


def test_cash_flow_forecast_horizon_outlook_counts_multiple_occurrences(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    with TestingSessionLocal() as db:
        item = PlaidItem(
            user_id=user_id,
            provider_item_id="forecast-recurring-item",
            institution_id="ins_forecast_recurring",
            institution_name="Forecast Bank",
            access_token_ciphertext="encrypted",
            status="active",
        )
        db.add(item)
        db.flush()

        db.add(
            FinancialAccount(
                plaid_item_id=item.id,
                provider_account_id="forecast-recurring-checking",
                name="Checking",
                account_type="depository",
                account_subtype="checking",
                current_balance_cents=200_000,
                available_balance_cents=200_000,
                currency="USD",
            )
        )

        db.add(
            RecurringItem(
                user_id=user_id,
                merchant="Rent",
                normalized_merchant="RENT",
                amount_cents=10_000,
                frequency="Monthly",
                last_payment=date(2026, 1, 5),
                next_payment=date(2026, 2, 5),
                status="active",
                confidence_score=95.0,
            )
        )
        db.commit()

    response = client.get(
        f"/users/{user_id}/summary/cash-flow-forecast",
        params={"as_of": "2026-02-01"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    horizons = {
        h["horizon_days"]: h
        for h in response.json()["horizon_outlook"]
    }

    # A single monthly bill recurs 1/2/3 times across a 30/60/90-day
    # horizon -- not once each time, which was the bug.
    assert horizons[30]["known_obligations_cents"] == 10_000
    assert horizons[30]["projected_balance_cents"] == 190_000

    assert horizons[60]["known_obligations_cents"] == 20_000
    assert horizons[60]["projected_balance_cents"] == 180_000

    assert horizons[90]["known_obligations_cents"] == 30_000
    assert horizons[90]["projected_balance_cents"] == 170_000


def test_cash_flow_forecast_horizon_confidence_reflects_data_richness(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    with TestingSessionLocal() as db:
        item = PlaidItem(
            user_id=user_id,
            provider_item_id="forecast-rich-item",
            institution_id="ins_forecast_rich",
            institution_name="Forecast Bank",
            access_token_ciphertext="encrypted",
            status="active",
        )
        db.add(item)
        db.flush()
        db.add(
            FinancialAccount(
                plaid_item_id=item.id,
                provider_account_id="forecast-rich-checking",
                name="Checking",
                account_type="depository",
                account_subtype="checking",
                current_balance_cents=500_000,
                available_balance_cents=500_000,
                currency="USD",
            )
        )
        db.commit()

    # Six months of consistent income + spending history, plus recent
    # activity right up to the forecast date.
    rows = ["date,description,amount,category"]
    for month in range(1, 7):
        rows.append(f"2026-{month:02d}-01,Payroll,3000.00,Income")
        rows.append(f"2026-{month:02d}-05,Rent,-1500.00,Housing")
    rows.append("2026-07-01,Payroll,3000.00,Income")
    rows.append("2026-07-02,Groceries,-100.00,Groceries")

    _upload(client, user_id, auth_headers, "\n".join(rows) + "\n")

    response = client.get(
        f"/users/{user_id}/summary/cash-flow-forecast",
        params={"as_of": "2026-07-10"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    horizons = response.json()["horizon_outlook"]
    assert horizons

    for horizon in horizons:
        # Six months of consistent income/spending history must score
        # meaningfully higher than the no-history case (62.4, see
        # test_cash_flow_forecast_uses_liquid_account_balance) --
        # sparse/erratic data must never masquerade as high
        # confidence for a pace-based income estimate.
        assert horizon["confidence_score"] > 62.4


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
        "2026-01-20,Netflix Streaming,-25.00,Subscriptions\n"
        "2026-01-27,Netflix Streaming,-25.00,Subscriptions\n"
        "2026-02-03,Netflix Streaming,-25.00,Subscriptions\n",
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

    assert upcoming["merchant"] == "Netflix Streaming"
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
