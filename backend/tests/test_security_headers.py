"""Response headers, CORS, body-size limits, and production-only
surface gating (API docs).
"""

import os
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

_BACKEND_DIR = Path(__file__).resolve().parent.parent


def test_security_headers_present_on_every_response(
    client: TestClient,
) -> None:
    resp = client.get("/health")

    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Cache-Control"] == "no-store"
    assert "Content-Security-Policy" in resp.headers


def test_hsts_only_set_over_https(client: TestClient) -> None:
    plain = client.get("/health")
    assert "Strict-Transport-Security" not in plain.headers

    https = client.get(
        "/health", headers={"X-Forwarded-Proto": "https"}
    )
    assert "Strict-Transport-Security" in https.headers
    assert "max-age=63072000" in https.headers["Strict-Transport-Security"]
    assert "includeSubDomains" in https.headers["Strict-Transport-Security"]


def test_no_store_applies_to_authenticated_financial_data(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    resp = client.get(f"/users/{user_id}/accounts", headers=auth_headers)
    assert resp.headers["Cache-Control"] == "no-store"


def test_docs_are_reachable_outside_production(client: TestClient) -> None:
    # The test suite runs with APP_ENV=test (see conftest.py) -- docs
    # are intentionally available in every non-production environment.
    resp = client.get("/openapi.json")
    assert resp.status_code == 200


def test_docs_are_disabled_in_production() -> None:
    """Spawns a fresh interpreter with APP_ENV=production so the
    app_env-gated docs_url/redoc_url/openapi_url computation in
    app/main.py (evaluated once at import time) is exercised for real,
    rather than relying on monkeypatching an already-imported module.
    """
    script = (
        "from app.main import app\n"
        "assert app.docs_url is None, app.docs_url\n"
        "assert app.redoc_url is None, app.redoc_url\n"
        "assert app.openapi_url is None, app.openapi_url\n"
        "print('OK')\n"
    )
    db_path = _BACKEND_DIR / "_security_test_prod_check.db"

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=_BACKEND_DIR,
        env={
            "PATH": os.environ.get("PATH", ""),
            "APP_ENV": "production",
            "JWT_SECRET": "a-real-randomly-generated-production-secret",
            "CORS_ORIGINS": "https://discero-app.vercel.app",
            "DATABASE_URL": f"sqlite:///{db_path.name}",
        },
        capture_output=True,
        text=True,
    )

    if db_path.exists():
        db_path.unlink()

    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout


def test_oversized_request_body_is_rejected(client: TestClient) -> None:
    big_password = "x" * (7 * 1024 * 1024)
    resp = client.post(
        "/users",
        json={"email": "toolarge@example.com", "password": big_password},
    )

    assert resp.status_code == 413
    assert resp.json()["detail"] == "request body too large"


def test_body_within_limit_is_processed_normally(
    client: TestClient,
) -> None:
    resp = client.post(
        "/users",
        json={"email": "normalsize@example.com", "password": "ValidPass123!"},
    )
    assert resp.status_code == 201
