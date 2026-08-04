from fastapi.testclient import TestClient

from app.models import FinancialAccount, PlaidItem
from tests.conftest import TestingSessionLocal


def test_accounts_require_authentication(
    client: TestClient,
    user_id: int,
) -> None:
    response = client.get(
        f"/users/{user_id}/accounts"
    )

    assert response.status_code == 401


def test_accounts_reject_cross_user_access(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    response = client.get(
        f"/users/{user_id + 1}/accounts",
        headers=auth_headers,
    )

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "you cannot access another user's data"
    )


def test_accounts_return_empty_list(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    response = client.get(
        f"/users/{user_id}/accounts",
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json() == []


def test_accounts_return_safe_account_details(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    with TestingSessionLocal() as db:
        item = PlaidItem(
            user_id=user_id,
            provider_item_id="item-1",
            institution_id="ins_1",
            institution_name="First Platypus Bank",
            access_token_ciphertext="encrypted-token",
            status="active",
        )
        db.add(item)
        db.flush()

        db.add(
            FinancialAccount(
                plaid_item_id=item.id,
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
        )
        db.commit()

    response = client.get(
        f"/users/{user_id}/accounts",
        headers=auth_headers,
    )

    assert response.status_code == 200

    body = response.json()

    assert len(body) == 1
    assert body[0]["plaid_item_id"] == item.id
    assert body[0]["institution_name"] == (
        "First Platypus Bank"
    )
    assert body[0]["name"] == "Plaid Checking"
    assert body[0]["mask"] == "0000"
    assert body[0]["current_balance_cents"] == 125050
    assert body[0]["available_balance_cents"] == 120000
    assert body[0]["connection_status"] == "active"
    assert body[0]["sync_status"] == "idle"
    assert body[0]["sync_error"] is None
    assert body[0]["last_sync_attempted_at"] is None

    serialized = str(body)

    assert "encrypted-token" not in serialized
    assert "provider_account_id" not in serialized
    assert "provider_item_id" not in serialized
    assert "access_token_ciphertext" not in serialized
    assert "sync_cursor" not in serialized
