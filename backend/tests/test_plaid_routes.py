from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import FinancialAccount, PlaidItem, Transaction
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


def test_exchange_token_rejects_duplicate_account_reconnect(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    # Regression test for the production incident: relinking the same
    # Sandbox Tartan Bank connection via a fresh (non-update-mode) Link
    # session returns a brand-new item_id *and* brand-new
    # provider_account_id values -- so this must be caught by
    # institution_id + mask/type/subtype fingerprinting, not by
    # comparing provider_item_id or provider_account_id.
    with TestingSessionLocal() as db:
        item = PlaidItem(
            user_id=user_id,
            provider_item_id="item-tartan-1",
            institution_id="ins_tartan",
            institution_name="Tartan Bank",
            access_token_ciphertext="ciphertext-1",
            status="active",
            sync_status="succeeded",
        )
        db.add(item)
        db.flush()

        db.add(
            FinancialAccount(
                plaid_item_id=item.id,
                provider_account_id="tartan-account-1",
                name="Plaid Checking",
                account_type="depository",
                account_subtype="checking",
                mask="0000",
                current_balance_cents=100000,
                currency="USD",
            )
        )
        db.commit()

    removed_tokens: list[str] = []

    monkeypatch.setattr(
        plaid_router,
        "exchange_public_token",
        lambda public_token: PlaidExchangeResult(
            # A different item_id, exactly as Plaid returns for a fresh
            # Link session against the same institution.
            access_token="access-token-duplicate",
            item_id="item-tartan-2",
        ),
    )
    monkeypatch.setattr(
        plaid_router,
        "get_accounts",
        lambda access_token: [
            PlaidAccountData(
                # A different provider_account_id too -- the whole
                # point of this test is that account_id alone can't be
                # used to detect the duplicate.
                provider_account_id="tartan-account-1-relinked",
                name="Plaid Checking",
                official_name=None,
                account_type="depository",
                account_subtype="checking",
                mask="0000",
                current_balance_cents=100000,
                available_balance_cents=100000,
                currency="USD",
            )
        ],
    )
    monkeypatch.setattr(
        plaid_router, "encrypt_token", lambda token: "ciphertext-2"
    )
    monkeypatch.setattr(
        plaid_router,
        "remove_item",
        lambda access_token: removed_tokens.append(access_token),
    )

    response = client.post(
        f"/users/{user_id}/plaid/exchange-token",
        headers=auth_headers,
        json={
            "public_token": "public-sandbox-token",
            "institution_id": "ins_tartan",
            "institution_name": "Tartan Bank",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "This bank account is already connected"
    )
    # The newly exchanged item's access token was revoked at Plaid so
    # no unused item/token is left behind there.
    assert removed_tokens == ["access-token-duplicate"]

    with TestingSessionLocal() as db:
        items = list(db.scalars(select(PlaidItem)).all())
        accounts = list(db.scalars(select(FinancialAccount)).all())

        assert len(items) == 1
        assert items[0].provider_item_id == "item-tartan-1"
        assert len(accounts) == 1
        assert accounts[0].provider_account_id == "tartan-account-1"


def test_exchange_token_allows_genuinely_different_connection(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    with TestingSessionLocal() as db:
        item = PlaidItem(
            user_id=user_id,
            provider_item_id="item-tartan-1",
            institution_id="ins_tartan",
            institution_name="Tartan Bank",
            access_token_ciphertext="ciphertext-1",
            status="active",
        )
        db.add(item)
        db.flush()

        db.add(
            FinancialAccount(
                plaid_item_id=item.id,
                provider_account_id="tartan-account-1",
                name="Plaid Checking",
                account_type="depository",
                account_subtype="checking",
                mask="0000",
                current_balance_cents=100000,
                currency="USD",
            )
        )
        db.commit()

    monkeypatch.setattr(
        plaid_router,
        "exchange_public_token",
        lambda public_token: PlaidExchangeResult(
            access_token="access-token-other-bank",
            item_id="item-other-bank",
        ),
    )
    monkeypatch.setattr(
        plaid_router,
        "get_accounts",
        lambda access_token: [
            PlaidAccountData(
                provider_account_id="other-bank-account-1",
                name="Savings",
                official_name=None,
                account_type="depository",
                account_subtype="savings",
                mask="9999",
                current_balance_cents=500000,
                available_balance_cents=500000,
                currency="USD",
            )
        ],
    )
    monkeypatch.setattr(
        plaid_router, "encrypt_token", lambda token: "ciphertext-other"
    )

    response = client.post(
        f"/users/{user_id}/plaid/exchange-token",
        headers=auth_headers,
        json={
            "public_token": "public-sandbox-token",
            "institution_id": "ins_other_bank",
            "institution_name": "Other Bank",
        },
    )

    assert response.status_code == 201

    with TestingSessionLocal() as db:
        items = list(db.scalars(select(PlaidItem)).all())
        assert len(items) == 2
        accounts = list(db.scalars(select(FinancialAccount)).all())
        assert len(accounts) == 2


def test_exchange_token_same_institution_name_different_accounts_succeeds(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    # Proves the dedup check is not keyed on institution_name: two
    # connections sharing a display name but with a different
    # institution_id and non-overlapping accounts must both succeed.
    with TestingSessionLocal() as db:
        item = PlaidItem(
            user_id=user_id,
            provider_item_id="item-bank-a",
            institution_id="ins_aaa",
            institution_name="Community Bank",
            access_token_ciphertext="ciphertext-1",
            status="active",
        )
        db.add(item)
        db.flush()

        db.add(
            FinancialAccount(
                plaid_item_id=item.id,
                provider_account_id="bank-a-account-1",
                name="Checking",
                account_type="depository",
                account_subtype="checking",
                mask="1234",
                current_balance_cents=100000,
                currency="USD",
            )
        )
        db.commit()

    monkeypatch.setattr(
        plaid_router,
        "exchange_public_token",
        lambda public_token: PlaidExchangeResult(
            access_token="access-token-bank-b",
            item_id="item-bank-b",
        ),
    )
    monkeypatch.setattr(
        plaid_router,
        "get_accounts",
        lambda access_token: [
            PlaidAccountData(
                provider_account_id="bank-b-account-1",
                name="Checking",
                official_name=None,
                account_type="depository",
                account_subtype="checking",
                mask="5678",
                current_balance_cents=200000,
                available_balance_cents=200000,
                currency="USD",
            )
        ],
    )
    monkeypatch.setattr(
        plaid_router, "encrypt_token", lambda token: "ciphertext-2"
    )

    response = client.post(
        f"/users/{user_id}/plaid/exchange-token",
        headers=auth_headers,
        json={
            "public_token": "public-sandbox-token",
            # Different institution_id, same display name.
            "institution_id": "ins_bbb",
            "institution_name": "Community Bank",
        },
    )

    assert response.status_code == 201

    with TestingSessionLocal() as db:
        assert len(list(db.scalars(select(PlaidItem)).all())) == 2
        assert (
            len(list(db.scalars(select(FinancialAccount)).all())) == 2
        )


def test_exchange_token_does_not_block_on_another_users_accounts(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    # A different user already has an account with the same
    # institution_id/mask/type/subtype fingerprint (plausible with
    # deterministic Sandbox test data). The dedup check must be scoped
    # to the authenticated user and must not block them.
    other_user_id = user_id + 1

    with TestingSessionLocal() as db:
        item = PlaidItem(
            user_id=other_user_id,
            provider_item_id="item-other-user",
            institution_id="ins_tartan",
            institution_name="Tartan Bank",
            access_token_ciphertext="ciphertext-other-user",
            status="active",
        )
        db.add(item)
        db.flush()

        db.add(
            FinancialAccount(
                plaid_item_id=item.id,
                provider_account_id="other-user-account-1",
                name="Plaid Checking",
                account_type="depository",
                account_subtype="checking",
                mask="0000",
                current_balance_cents=100000,
                currency="USD",
            )
        )
        db.commit()

    monkeypatch.setattr(
        plaid_router,
        "exchange_public_token",
        lambda public_token: PlaidExchangeResult(
            access_token="access-token-this-user",
            item_id="item-this-user",
        ),
    )
    monkeypatch.setattr(
        plaid_router,
        "get_accounts",
        lambda access_token: [
            PlaidAccountData(
                provider_account_id="this-user-account-1",
                name="Plaid Checking",
                official_name=None,
                account_type="depository",
                account_subtype="checking",
                mask="0000",
                current_balance_cents=100000,
                available_balance_cents=100000,
                currency="USD",
            )
        ],
    )
    monkeypatch.setattr(
        plaid_router, "encrypt_token", lambda token: "ciphertext-this-user"
    )

    response = client.post(
        f"/users/{user_id}/plaid/exchange-token",
        headers=auth_headers,
        json={
            "public_token": "public-sandbox-token",
            "institution_id": "ins_tartan",
            "institution_name": "Tartan Bank",
        },
    )

    assert response.status_code == 201

    with TestingSessionLocal() as db:
        this_user_item = db.scalar(
            select(PlaidItem).where(
                PlaidItem.provider_item_id == "item-this-user"
            )
        )
        assert this_user_item is not None
        assert this_user_item.user_id == user_id


def test_exchange_token_allows_cross_user_provider_account_id_collision(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    # FinancialAccount.provider_account_id used to be globally
    # unique=True, not scoped per item/user. Plaid does not guarantee
    # account_id is globally unique -- Sandbox in particular returns
    # identical account_id values for identical test credentials
    # connected by different users -- so a second, otherwise-legitimate
    # user connecting a different institution with the same account_id
    # used to collide at the database level and fail with a 500. The
    # uniqueness constraint is now scoped to (plaid_item_id,
    # provider_account_id), so this must succeed for both users.
    other_user_id = user_id + 1
    shared_account_id = "globally-shared-account-id"

    with TestingSessionLocal() as db:
        item = PlaidItem(
            user_id=other_user_id,
            provider_item_id="item-other-user",
            institution_id="ins_other_user_bank",
            institution_name="Other User's Bank",
            access_token_ciphertext="ciphertext-other-user",
            status="active",
        )
        db.add(item)
        db.flush()

        db.add(
            FinancialAccount(
                plaid_item_id=item.id,
                provider_account_id=shared_account_id,
                name="Checking",
                account_type="depository",
                account_subtype="checking",
                mask="4321",
                current_balance_cents=100000,
                currency="USD",
            )
        )
        db.commit()

    monkeypatch.setattr(
        plaid_router,
        "exchange_public_token",
        lambda public_token: PlaidExchangeResult(
            access_token="access-token-colliding",
            item_id="item-this-user-colliding",
        ),
    )
    monkeypatch.setattr(
        plaid_router,
        "get_accounts",
        lambda access_token: [
            PlaidAccountData(
                # Same account_id as another user's row -- a
                # genuinely different institution, so the
                # institution_id-scoped dedup check does not fire.
                provider_account_id=shared_account_id,
                name="Checking",
                official_name=None,
                account_type="depository",
                account_subtype="checking",
                mask="8765",
                current_balance_cents=250000,
                available_balance_cents=250000,
                currency="USD",
            )
        ],
    )
    monkeypatch.setattr(
        plaid_router, "encrypt_token", lambda token: "ciphertext-colliding"
    )

    response = client.post(
        f"/users/{user_id}/plaid/exchange-token",
        headers=auth_headers,
        json={
            "public_token": "public-sandbox-token",
            "institution_id": "ins_this_user_bank",
            "institution_name": "This User's Bank",
        },
    )

    assert response.status_code == 201

    with TestingSessionLocal() as db:
        this_user_item = db.scalar(
            select(PlaidItem).where(PlaidItem.user_id == user_id)
        )
        assert this_user_item is not None

        accounts_by_item = {
            account.plaid_item_id: account
            for account in db.scalars(
                select(FinancialAccount).where(
                    FinancialAccount.provider_account_id
                    == shared_account_id
                )
            ).all()
        }
        # Both users now have their own row sharing the same
        # provider_account_id, scoped by their own item.
        assert len(accounts_by_item) == 2
        assert this_user_item.id in accounts_by_item


def test_exchange_token_allows_partial_account_overlap(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    # Only one of two incoming accounts happens to share a (mask, type,
    # subtype) fingerprint with an existing connection -- Plaid does not
    # guarantee mask uniqueness, so a single-account coincidence must
    # not block the whole new item. Only an exact full-set match is
    # treated as a duplicate reconnect; a partial (or coincidental)
    # overlap proceeds normally.
    with TestingSessionLocal() as db:
        item = PlaidItem(
            user_id=user_id,
            provider_item_id="item-tartan-1",
            institution_id="ins_tartan",
            institution_name="Tartan Bank",
            access_token_ciphertext="ciphertext-1",
            status="active",
        )
        db.add(item)
        db.flush()

        db.add(
            FinancialAccount(
                plaid_item_id=item.id,
                provider_account_id="tartan-account-1",
                name="Plaid Checking",
                account_type="depository",
                account_subtype="checking",
                mask="0000",
                current_balance_cents=100000,
                currency="USD",
            )
        )
        db.commit()

    monkeypatch.setattr(
        plaid_router,
        "exchange_public_token",
        lambda public_token: PlaidExchangeResult(
            access_token="access-token-partial",
            item_id="item-tartan-2",
        ),
    )
    monkeypatch.setattr(
        plaid_router,
        "get_accounts",
        lambda access_token: [
            PlaidAccountData(
                provider_account_id="tartan-account-1-relinked",
                name="Plaid Checking",
                official_name=None,
                account_type="depository",
                account_subtype="checking",
                mask="0000",
                current_balance_cents=100000,
                available_balance_cents=100000,
                currency="USD",
            ),
            PlaidAccountData(
                provider_account_id="tartan-account-2-new",
                name="Plaid Savings",
                official_name=None,
                account_type="depository",
                account_subtype="savings",
                mask="1111",
                current_balance_cents=300000,
                available_balance_cents=300000,
                currency="USD",
            ),
        ],
    )
    monkeypatch.setattr(
        plaid_router, "encrypt_token", lambda token: "ciphertext-2"
    )

    response = client.post(
        f"/users/{user_id}/plaid/exchange-token",
        headers=auth_headers,
        json={
            "public_token": "public-sandbox-token",
            "institution_id": "ins_tartan",
            "institution_name": "Tartan Bank",
        },
    )

    assert response.status_code == 201

    with TestingSessionLocal() as db:
        accounts = list(db.scalars(select(FinancialAccount)).all())
        assert len(accounts) == 3
        items = list(db.scalars(select(PlaidItem)).all())
        assert len(items) == 2


def test_exchange_token_duplicate_rejection_survives_cleanup_failure(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    with TestingSessionLocal() as db:
        item = PlaidItem(
            user_id=user_id,
            provider_item_id="item-tartan-1",
            institution_id="ins_tartan",
            institution_name="Tartan Bank",
            access_token_ciphertext="ciphertext-1",
            status="active",
        )
        db.add(item)
        db.flush()

        db.add(
            FinancialAccount(
                plaid_item_id=item.id,
                provider_account_id="tartan-account-1",
                name="Plaid Checking",
                account_type="depository",
                account_subtype="checking",
                mask="0000",
                current_balance_cents=100000,
                currency="USD",
            )
        )
        db.commit()

    monkeypatch.setattr(
        plaid_router,
        "exchange_public_token",
        lambda public_token: PlaidExchangeResult(
            access_token="access-token-duplicate",
            item_id="item-tartan-2",
        ),
    )
    monkeypatch.setattr(
        plaid_router,
        "get_accounts",
        lambda access_token: [
            PlaidAccountData(
                provider_account_id="tartan-account-1-relinked",
                name="Plaid Checking",
                official_name=None,
                account_type="depository",
                account_subtype="checking",
                mask="0000",
                current_balance_cents=100000,
                available_balance_cents=100000,
                currency="USD",
            )
        ],
    )
    monkeypatch.setattr(
        plaid_router, "encrypt_token", lambda token: "ciphertext-2"
    )

    def raise_on_remove(access_token: str) -> None:
        raise PlaidServiceError("Unable to disconnect Plaid institution")

    monkeypatch.setattr(
        plaid_router, "remove_item", raise_on_remove
    )

    response = client.post(
        f"/users/{user_id}/plaid/exchange-token",
        headers=auth_headers,
        json={
            "public_token": "public-sandbox-token",
            "institution_id": "ins_tartan",
            "institution_name": "Tartan Bank",
        },
    )

    # The user still gets a clean 409, not a 500 -- cleanup failing at
    # Plaid must not surface as, or be conflated with, an unrelated
    # server error, and must never leak the access token.
    assert response.status_code == 409
    assert response.json()["detail"] == (
        "This bank account is already connected"
    )
    assert "access-token-duplicate" not in response.text

    with TestingSessionLocal() as db:
        items = list(db.scalars(select(PlaidItem)).all())
        assert len(items) == 1
        assert items[0].provider_item_id == "item-tartan-1"


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

def test_disconnect_plaid_item_deletes_its_plaid_transactions(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    # Regression test for a production data-integrity bug: disconnecting
    # a Plaid item used to delete the item's FinancialAccount rows (via
    # the PlaidItem.accounts delete-orphan cascade) but leave that
    # account's Plaid-imported transactions behind with
    # financial_account_id set to NULL -- they'd resurface in the UI as
    # stale, unlinked-looking "duplicate" transactions. Disconnecting
    # must delete those Plaid transactions outright, not just orphan
    # them.
    with TestingSessionLocal() as db:
        item = PlaidItem(
            user_id=user_id,
            provider_item_id="item-disconnect-1",
            institution_name="Sandbox Bank",
            access_token_ciphertext="encrypted-token",
            status="active",
        )
        db.add(item)
        db.flush()

        account = FinancialAccount(
            plaid_item_id=item.id,
            provider_account_id="account-disconnect-1",
            name="Checking",
            account_type="depository",
            account_subtype="checking",
            currency="USD",
        )
        db.add(account)
        db.flush()

        transaction = Transaction(
            user_id=user_id,
            financial_account_id=account.id,
            provider_transaction_id="transaction-disconnect-1",
            posted_on=date(2026, 8, 1),
            description="Plaid transaction on disconnected account",
            amount_cents=-2500,
            category="Food",
            source="plaid",
            pending=False,
        )
        db.add(transaction)
        db.commit()

        item_id = item.id
        account_id = account.id
        transaction_id = transaction.id

    removed_tokens: list[str] = []

    monkeypatch.setattr(
        plaid_router,
        "decrypt_token",
        lambda ciphertext: "plaintext-access-token",
    )
    monkeypatch.setattr(
        plaid_router,
        "remove_item",
        lambda access_token: removed_tokens.append(access_token),
    )

    response = client.delete(
        f"/users/{user_id}/plaid/items/{item_id}",
        headers=auth_headers,
    )

    assert response.status_code == 204
    assert removed_tokens == ["plaintext-access-token"]

    with TestingSessionLocal() as db:
        # D: the PlaidItem and its FinancialAccount rows are removed.
        assert db.get(PlaidItem, item_id) is None
        assert db.get(FinancialAccount, account_id) is None

        # A: the item's Plaid transaction is deleted outright, not
        # merely orphaned with financial_account_id set to NULL.
        assert db.get(Transaction, transaction_id) is None


def test_disconnect_plaid_item_preserves_other_items_plaid_transactions(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    with TestingSessionLocal() as db:
        item_a = PlaidItem(
            user_id=user_id,
            provider_item_id="item-disconnect-a",
            institution_name="Bank A",
            access_token_ciphertext="encrypted-token-a",
            status="active",
        )
        item_b = PlaidItem(
            user_id=user_id,
            provider_item_id="item-disconnect-b",
            institution_name="Bank B",
            access_token_ciphertext="encrypted-token-b",
            status="active",
        )
        db.add_all([item_a, item_b])
        db.flush()

        account_a = FinancialAccount(
            plaid_item_id=item_a.id,
            provider_account_id="account-disconnect-a",
            name="Checking A",
            account_type="depository",
            account_subtype="checking",
            currency="USD",
        )
        account_b = FinancialAccount(
            plaid_item_id=item_b.id,
            provider_account_id="account-disconnect-b",
            name="Checking B",
            account_type="depository",
            account_subtype="checking",
            currency="USD",
        )
        db.add_all([account_a, account_b])
        db.flush()

        transaction_a = Transaction(
            user_id=user_id,
            financial_account_id=account_a.id,
            provider_transaction_id="transaction-disconnect-a",
            posted_on=date(2026, 8, 1),
            description="Item A transaction",
            amount_cents=-1000,
            category="Food",
            source="plaid",
            pending=False,
        )
        transaction_b = Transaction(
            user_id=user_id,
            financial_account_id=account_b.id,
            provider_transaction_id="transaction-disconnect-b",
            posted_on=date(2026, 8, 1),
            description="Item B transaction",
            amount_cents=-2000,
            category="Food",
            source="plaid",
            pending=False,
        )
        db.add_all([transaction_a, transaction_b])
        db.commit()

        item_a_id = item_a.id
        item_b_id = item_b.id
        account_b_id = account_b.id
        transaction_a_id = transaction_a.id
        transaction_b_id = transaction_b.id

    monkeypatch.setattr(
        plaid_router,
        "decrypt_token",
        lambda ciphertext: "plaintext-access-token",
    )
    monkeypatch.setattr(
        plaid_router,
        "remove_item",
        lambda access_token: None,
    )

    response = client.delete(
        f"/users/{user_id}/plaid/items/{item_a_id}",
        headers=auth_headers,
    )

    assert response.status_code == 204

    with TestingSessionLocal() as db:
        # Item A's transaction is gone.
        assert db.get(Transaction, transaction_a_id) is None

        # B: item B (a different, untouched connection) and its Plaid
        # transaction are completely unaffected.
        assert db.get(PlaidItem, item_b_id) is not None
        assert db.get(FinancialAccount, account_b_id) is not None
        transaction_b = db.get(Transaction, transaction_b_id)
        assert transaction_b is not None
        assert transaction_b.financial_account_id == account_b_id
        assert transaction_b.description == "Item B transaction"


def test_disconnect_plaid_item_preserves_manual_and_csv_transactions(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    with TestingSessionLocal() as db:
        item = PlaidItem(
            user_id=user_id,
            provider_item_id="item-disconnect-manual",
            institution_name="Sandbox Bank",
            access_token_ciphertext="encrypted-token",
            status="active",
        )
        db.add(item)
        db.flush()

        account = FinancialAccount(
            plaid_item_id=item.id,
            provider_account_id="account-disconnect-manual",
            name="Checking",
            account_type="depository",
            account_subtype="checking",
            currency="USD",
        )
        db.add(account)
        db.flush()

        plaid_transaction = Transaction(
            user_id=user_id,
            financial_account_id=account.id,
            provider_transaction_id="transaction-disconnect-manual-plaid",
            posted_on=date(2026, 8, 1),
            description="Plaid transaction",
            amount_cents=-500,
            category="Food",
            source="plaid",
            pending=False,
        )
        # C: a CSV/manual transaction that happens to be attached to the
        # same account being disconnected -- and an unrelated manual
        # transaction with no account at all -- must both survive.
        csv_transaction_on_account = Transaction(
            user_id=user_id,
            financial_account_id=account.id,
            posted_on=date(2026, 8, 2),
            description="Manually tagged to this account",
            amount_cents=-750,
            category="Food",
            source="csv",
            pending=False,
        )
        unrelated_manual_transaction = Transaction(
            user_id=user_id,
            financial_account_id=None,
            posted_on=date(2026, 8, 3),
            description="Unrelated manual transaction",
            amount_cents=-300,
            category="Food",
            source="csv",
            pending=False,
        )
        db.add_all(
            [
                plaid_transaction,
                csv_transaction_on_account,
                unrelated_manual_transaction,
            ]
        )
        db.commit()

        item_id = item.id
        plaid_transaction_id = plaid_transaction.id
        csv_transaction_id = csv_transaction_on_account.id
        unrelated_transaction_id = unrelated_manual_transaction.id

    monkeypatch.setattr(
        plaid_router,
        "decrypt_token",
        lambda ciphertext: "plaintext-access-token",
    )
    monkeypatch.setattr(
        plaid_router,
        "remove_item",
        lambda access_token: None,
    )

    response = client.delete(
        f"/users/{user_id}/plaid/items/{item_id}",
        headers=auth_headers,
    )

    assert response.status_code == 204

    with TestingSessionLocal() as db:
        assert db.get(Transaction, plaid_transaction_id) is None

        csv_transaction = db.get(Transaction, csv_transaction_id)
        assert csv_transaction is not None
        assert csv_transaction.description == "Manually tagged to this account"
        # The account it referenced is gone, so (like any other
        # non-Plaid transaction) it falls back to NULL rather than being
        # deleted -- disconnecting a bank must never delete manual/CSV
        # data.
        assert csv_transaction.financial_account_id is None

        unrelated_transaction = db.get(Transaction, unrelated_transaction_id)
        assert unrelated_transaction is not None
        assert unrelated_transaction.description == "Unrelated manual transaction"


def test_disconnect_plaid_item_returns_not_found(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    response = client.delete(
        f"/users/{user_id}/plaid/items/999999",
        headers=auth_headers,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == (
        "Plaid connection not found"
    )


def test_disconnect_plaid_item_requires_authentication(
    client: TestClient,
    user_id: int,
) -> None:
    response = client.delete(
        f"/users/{user_id}/plaid/items/1"
    )

    assert response.status_code == 401


def test_disconnect_plaid_item_rejects_cross_user_access(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
) -> None:
    response = client.delete(
        f"/users/{user_id + 1}/plaid/items/1",
        headers=auth_headers,
    )

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "you cannot access another user's data"
    )


def test_disconnect_plaid_item_keeps_local_data_when_plaid_fails(
    client: TestClient,
    user_id: int,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    with TestingSessionLocal() as db:
        item = PlaidItem(
            user_id=user_id,
            provider_item_id="item-disconnect-failure",
            institution_name="Sandbox Bank",
            access_token_ciphertext="encrypted-token",
            status="active",
        )
        db.add(item)
        db.commit()
        item_id = item.id

    monkeypatch.setattr(
        plaid_router,
        "decrypt_token",
        lambda ciphertext: "plaintext-access-token",
    )

    def raise_error(access_token: str) -> None:
        raise PlaidServiceError(
            "Unable to disconnect Plaid institution"
        )

    monkeypatch.setattr(
        plaid_router,
        "remove_item",
        raise_error,
    )

    response = client.delete(
        f"/users/{user_id}/plaid/items/{item_id}",
        headers=auth_headers,
    )

    assert response.status_code == 502
    assert response.json()["detail"] == (
        "Unable to disconnect Plaid institution"
    )

    with TestingSessionLocal() as db:
        assert db.get(PlaidItem, item_id) is not None
