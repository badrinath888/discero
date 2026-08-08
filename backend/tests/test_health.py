from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_check() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_check_reaches_database() -> None:
    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_security_headers_are_present() -> None:
    response = client.get("/health")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert (
        response.headers["referrer-policy"]
        == "strict-origin-when-cross-origin"
    )
    assert response.headers["x-frame-options"] == "DENY"
    # Plain HTTP in tests: HSTS must not be sent.
    assert "strict-transport-security" not in response.headers


def test_hsts_header_present_when_forwarded_as_https() -> None:
    response = client.get(
        "/health", headers={"x-forwarded-proto": "https"}
    )

    assert "strict-transport-security" in response.headers