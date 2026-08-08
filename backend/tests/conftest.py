import os

# Must run before any `app.*` import triggers `app.config`'s
# module-level `settings = Settings()`. APP_ENV has historically
# defaulted to "production" when unset (including in this test
# environment), which is a deliberately fail-safe default for real
# deployments but is not what a test run actually is -- forcing it
# here keeps tests independent of whatever a developer's local .env
# happens to set, and lets production-only validation (e.g. rejecting
# the default JWT secret) be tested without also firing here.
os.environ.setdefault("APP_ENV", "test")

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.rate_limit import reset_rate_limits


TEST_EMAIL = "test-user@example.com"
TEST_PASSWORD = "TestPassword123!"

test_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestingSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    bind=test_engine,
)


def override_get_db() -> Generator[Session, None, None]:
    db = TestingSessionLocal()

    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def isolated_database() -> Generator[None, None, None]:
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)

    app.dependency_overrides[get_db] = override_get_db
    reset_rate_limits()

    yield

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def user_id(client: TestClient) -> int:
    response = client.post(
        "/users",
        json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD,
        },
    )

    assert response.status_code == 201
    return response.json()["id"]


@pytest.fixture
def auth_headers(
    client: TestClient,
    user_id: int,
) -> dict[str, str]:
    response = client.post(
        "/users/login",
        json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD,
        },
    )

    assert response.status_code == 200

    token = response.json()["access_token"]

    return {
        "Authorization": f"Bearer {token}",
    }