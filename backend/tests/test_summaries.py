import io

from fastapi.testclient import TestClient


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