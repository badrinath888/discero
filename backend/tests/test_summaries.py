import io


def _upload(client, user_id, csv_text: str):
    files = {"file": ("t.csv", io.BytesIO(csv_text.encode()), "text/csv")}
    resp = client.post(f"/users/{user_id}/transactions/upload", files=files)
    assert resp.status_code == 200
    return resp


def test_overview(client, user_id):
    _upload(
        client,
        user_id,
        "date,description,amount\n"
        "2026-01-06,ACME Payroll,2000.00\n"
        "2026-01-07,Whole Foods,-150.00\n"
        "2026-01-08,Rent,-850.00\n",
    )
    ov = client.get(f"/users/{user_id}/summary/overview").json()
    assert ov["total_income_cents"] == 200000
    assert ov["total_spending_cents"] == 100000
    assert ov["net_cents"] == 100000
    assert ov["transaction_count"] == 3


def test_by_month(client, user_id):
    _upload(
        client,
        user_id,
        "date,description,amount\n"
        "2026-01-06,ACME Payroll,2000.00\n"
        "2026-01-20,Whole Foods,-100.00\n"
        "2026-02-06,ACME Payroll,2000.00\n"
        "2026-02-15,Rent,-850.00\n",
    )
    months = client.get(f"/users/{user_id}/summary/by-month").json()
    assert [m["month"] for m in months] == ["2026-01", "2026-02"]

    jan = months[0]
    assert jan["income_cents"] == 200000
    assert jan["spending_cents"] == 10000
    assert jan["net_cents"] == 190000

    feb = months[1]
    assert feb["net_cents"] == 200000 - 85000


def test_summaries_require_existing_user(client):
    assert client.get("/users/999/summary/overview").status_code == 404
    assert client.get("/users/999/summary/by-month").status_code == 404
