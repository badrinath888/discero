from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import FinancialAccount, PlaidItem
from app.routers import plaid as plaid_router
from app.services.plaid_service import (
    PlaidAccountData,
    PlaidConfigurationError,
    PlaidExchangeResult,
    PlaidServiceError,
)
from app.token_encryption import TokenEncryptionError
from tests.conftest import TestingSessionLocal


def test_link_token_requires_authentication(
    client: TestClient,
    user_id: int,
) -> None:
    response = client.post(
        f"/users/{user_id}/plaid/link-token"
    )

    assert response.status_code == 401
    assert response.json()["detail"] == (
        "authentication required"
    )


def test_link_token_rejects_cross_user_access(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    response = client.post(
        f"/users/{user_id + 1}/plaid/link-token",
        headers=auth_headers,
    )

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "you cannot access another user's data"
    )


def test_link_token_returns_token(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        plaid_router,
        "create_link_token",
        lambda user_id: "link-sandbox-test-token",
    )

    response = client.post(
        f"/users/{user_id}/plaid/link-token",
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json() == {
        "link_token": "link-sandbox-test-token"
    }


def test_link_token_handles_missing_configuration(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    def raise_error(user_id: int) -> str:
        raise PlaidConfigurationError(
            "Plaid credentials are not configured"
        )

    monkeypatch.setattr(
        plaid_router,
        "create_link_token",
        raise_error,
    )

    response = client.post(
        f"/users/{user_id}/plaid/link-token",
        headers=auth_headers,
    )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Plaid credentials are not configured"
    )


def test_link_token_handles_plaid_failure(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    def raise_error(user_id: int) -> str:
        raise PlaidServiceError(
            "Unable to create Plaid Link token"
        )

    monkeypatch.setattr(
        plaid_router,
        "create_link_token",
        raise_error,
    )

    response = client.post(
        f"/users/{user_id}/plaid/link-token",
        headers=auth_headers,
    )

    assert response.status_code == 502
    assert response.json()["detail"] == (
        "Unable to create Plaid Link token"
    )


def test_exchange_token_requires_authentication(
    client: TestClient,
    user_id: int,
) -> None:
    response = client.post(
        f"/users/{user_id}/plaid/exchange-token",
        json={"public_token": "public-sandbox-token"},
    )

    assert response.status_code == 401


def test_exchange_token_rejects_cross_user_access(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    response = client.post(
        f"/users/{user_id + 1}/plaid/exchange-token",
        headers=auth_headers,
        json={"public_token": "public-sandbox-token"},
    )

    assert response.status_code == 403


def test_exchange_token_saves_encrypted_item_and_accounts(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    plaintext_access_token = "access-sandbox-secret-token"

    monkeypatch.setattr(
        plaid_router,
        "exchange_public_token",
        lambda public_token: PlaidExchangeResult(
            access_token=plaintext_access_token,
            item_id="item-sandbox-1",
        ),
    )

    monkeypatch.setattr(
        plaid_router,
        "get_accounts",
        lambda access_token: [
            PlaidAccountData(
                provider_account_id="account-1",
                name="Plaid Checking",
                official_name="Plaid Gold Checking",
                account_type="depository",
                account_subtype="checking",
                mask="0000",
                current_balance_cents=125050,
                available_balance_cents=120000,
                currency="USD",
            )
        ],
    )

    monkeypatch.setattr(
        plaid_router,
        "encrypt_token",
        lambda token: "encrypted-access-token",
    )

    response = client.post(
        f"/users/{user_id}/plaid/exchange-token",
        headers=auth_headers,
        json={
            "public_token": "public-sandbox-token",
            "institution_id": "ins_109508",
            "institution_name": "First Platypus Bank",
        },
    )

    assert response.status_code == 201

    body = response.json()

    assert body["institution_name"] == (
        "First Platypus Bank"
    )
    assert body["status"] == "active"
    assert body["accounts"] == [
        {
            "id": body["accounts"][0]["id"],
            "name": "Plaid Checking",
            "official_name": "Plaid Gold Checking",
            "account_type": "depository",
            "account_subtype": "checking",
            "mask": "0000",
            "current_balance_cents": 125050,
            "available_balance_cents": 120000,
            "currency": "USD",
        }
    ]

    assert plaintext_access_token not in str(body)
    assert "access_token_ciphertext" not in body
    assert "provider_item_id" not in body

    with TestingSessionLocal() as db:
        item = db.scalar(
            select(PlaidItem).where(
                PlaidItem.provider_item_id
                == "item-sandbox-1"
            )
        )

        assert item is not None
        assert item.user_id == user_id
        assert (
            item.access_token_ciphertext
            == "encrypted-access-token"
        )
        assert (
            item.access_token_ciphertext
            != plaintext_access_token
        )

        account = db.scalar(
            select(FinancialAccount).where(
                FinancialAccount.provider_account_id
                == "account-1"
            )
        )

        assert account is not None
        assert account.plaid_item_id == item.id
        assert account.current_balance_cents == 125050


def test_exchange_token_updates_existing_item_and_account(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    with TestingSessionLocal() as db:
        item = PlaidItem(
            user_id=user_id,
            provider_item_id="item-sandbox-1",
            institution_name="Old Bank",
            access_token_ciphertext="old-ciphertext",
            status="active",
        )
        db.add(item)
        db.flush()

        db.add(
            FinancialAccount(
                plaid_item_id=item.id,
                provider_account_id="account-1",
                name="Old Checking",
                account_type="depository",
                account_subtype="checking",
                current_balance_cents=10000,
                currency="USD",
            )
        )
        db.commit()

    monkeypatch.setattr(
        plaid_router,
        "exchange_public_token",
        lambda public_token: PlaidExchangeResult(
            access_token="new-access-token",
            item_id="item-sandbox-1",
        ),
    )

    monkeypatch.setattr(
        plaid_router,
        "get_accounts",
        lambda access_token: [
            PlaidAccountData(
                provider_account_id="account-1",
                name="Updated Checking",
                official_name=None,
                account_type="depository",
                account_subtype="checking",
                mask="1111",
                current_balance_cents=25000,
                available_balance_cents=24000,
                currency="USD",
            )
        ],
    )

    monkeypatch.setattr(
        plaid_router,
        "encrypt_token",
        lambda token: "new-ciphertext",
    )

    response = client.post(
        f"/users/{user_id}/plaid/exchange-token",
        headers=auth_headers,
        json={
            "public_token": "public-sandbox-token",
            "institution_name": "Updated Bank",
        },
    )

    assert response.status_code == 201

    with TestingSessionLocal() as db:
        items = list(
            db.scalars(select(PlaidItem)).all()
        )
        accounts = list(
            db.scalars(select(FinancialAccount)).all()
        )

        assert len(items) == 1
        assert len(accounts) == 1
        assert items[0].institution_name == "Updated Bank"
        assert (
            items[0].access_token_ciphertext
            == "new-ciphertext"
        )
        assert accounts[0].name == "Updated Checking"
        assert accounts[0].current_balance_cents == 25000


def test_exchange_token_handles_plaid_failure(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    def raise_error(
        public_token: str,
    ) -> PlaidExchangeResult:
        raise PlaidServiceError(
            "Unable to exchange Plaid public token"
        )

    monkeypatch.setattr(
        plaid_router,
        "exchange_public_token",
        raise_error,
    )

    response = client.post(
        f"/users/{user_id}/plaid/exchange-token",
        headers=auth_headers,
        json={"public_token": "public-sandbox-token"},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == (
        "Unable to exchange Plaid public token"
    )


def test_exchange_token_handles_encryption_failure(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        plaid_router,
        "exchange_public_token",
        lambda public_token: PlaidExchangeResult(
            access_token="access-token",
            item_id="item-1",
        ),
    )

    monkeypatch.setattr(
        plaid_router,
        "get_accounts",
        lambda access_token: [],
    )

    def raise_error(token: str) -> str:
        raise TokenEncryptionError(
            "Token encryption key is not configured"
        )

    monkeypatch.setattr(
        plaid_router,
        "encrypt_token",
        raise_error,
    )

    response = client.post(
        f"/users/{user_id}/plaid/exchange-token",
        headers=auth_headers,
        json={"public_token": "public-sandbox-token"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Token encryption key is not configured"
    )