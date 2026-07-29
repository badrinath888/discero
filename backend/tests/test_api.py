import io


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_create_and_get_user(client):
    resp = client.post("/users", json={"email": "a@b.com"})
    assert resp.status_code == 201
    uid = resp.json()["id"]
    assert client.get(f"/users/{uid}").json()["email"] == "a@b.com"


def test_duplicate_email_rejected(client):
    client.post("/users", json={"email": "dup@b.com"})
    resp = client.post("/users", json={"email": "dup@b.com"})
    assert resp.status_code == 409


def test_upload_flow_and_summary(client, user_id):
    csv_bytes = (
        "date,description,amount\n"
        "2026-01-05,Whole Foods,-52.10\n"
        "2026-01-06,Starbucks,-6.25\n"
        "2026-01-06,ACME Payroll,2000.00\n"
    ).encode()
    files = {"file": ("txns.csv", io.BytesIO(csv_bytes), "text/csv")}

    resp = client.post(f"/users/{user_id}/transactions/upload", files=files)
    assert resp.status_code == 200
    body = resp.json()
    assert body["imported"] == 3
    assert body["rejected"] == 0

    txns = client.get(f"/users/{user_id}/transactions").json()
    assert len(txns) == 3

    summary = client.get(f"/users/{user_id}/summary/by-category").json()
    cats = {row["category"]: row["total_cents"] for row in summary}
    assert cats["Groceries"] == -5210
    assert cats["Income"] == 200000


def test_upload_rejects_non_csv(client, user_id):
    files = {"file": ("data.txt", io.BytesIO(b"hello"), "text/plain")}
    resp = client.post(f"/users/{user_id}/transactions/upload", files=files)
    assert resp.status_code == 400


def test_upload_for_missing_user_404(client):
    files = {"file": ("t.csv", io.BytesIO(b"date,description,amount\n"), "text/csv")}
    resp = client.post("/users/9999/transactions/upload", files=files)
    assert resp.status_code == 404
