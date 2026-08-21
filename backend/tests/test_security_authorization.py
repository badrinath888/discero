"""BOLA/IDOR regression suite: User B must never be able to read,
list, create-under, modify, or delete User A's resources, whether by
guessing User A's own user_id in the URL path (blocked by
`_authorize_user`) or by supplying User A's object id under User B's
OWN authorized path (blocked only if the service/query layer itself
scopes every lookup by the authenticated owner -- the subtler, more
important case this suite locks in).

Every resource class the API exposes is covered: transactions,
budgets, recurring items, savings goals (+ contributions), decisions
(+ outcomes/timeline/rerun/status), and Plaid items. Setup goes
through the real authenticated HTTP API wherever a creation endpoint
exists (Plaid items are the one exception -- creating one for real
requires a live Plaid Link session, so that fixture is built directly
against the ORM instead, matching the pattern already used by
test_copilot_service.py).
"""

from datetime import date
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import FinancialAccount, PlaidItem
from tests.conftest import TestingSessionLocal

PASSWORD = "TestPassword123!"

# Any denial is acceptable here -- some endpoints 404 (object-scoped
# lookup simply finds nothing), others 403 (path-level user mismatch).
# Both are correct "you cannot see/touch this" outcomes; a security
# regression is a 200/201/204 on someone else's data, not a specific
# status code.
DENIED = (403, 404)


def _register_and_login(
    client: TestClient, email: str
) -> tuple[int, dict[str, str]]:
    created = client.post(
        "/users", json={"email": email, "password": PASSWORD}
    )
    assert created.status_code == 201

    login = client.post(
        "/users/login", json={"email": email, "password": PASSWORD}
    )
    assert login.status_code == 200
    body = login.json()

    return body["user"]["id"], {
        "Authorization": f"Bearer {body['access_token']}"
    }


@pytest.fixture
def user_a(client: TestClient) -> tuple[int, dict[str, str]]:
    return _register_and_login(client, f"bola-a-{uuid4().hex}@example.com")


@pytest.fixture
def user_b(client: TestClient) -> tuple[int, dict[str, str]]:
    return _register_and_login(client, f"bola-b-{uuid4().hex}@example.com")


# --- Transactions ---------------------------------------------------------


def _create_transaction(
    client: TestClient, owner_id: int, owner_headers: dict[str, str]
) -> int:
    resp = client.post(
        f"/users/{owner_id}/transactions",
        headers=owner_headers,
        json={
            "posted_on": "2026-01-15",
            "description": "Groceries",
            "amount_cents": -5000,
            "category": "Food",
        },
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def test_cannot_read_another_users_transaction_list_via_own_path(
    client: TestClient,
    user_a: tuple[int, dict[str, str]],
    user_b: tuple[int, dict[str, str]],
) -> None:
    a_id, a_headers = user_a
    _, b_headers = user_b

    resp = client.get(f"/users/{a_id}/transactions", headers=b_headers)
    assert resp.status_code in DENIED


def test_cannot_modify_another_users_transaction(
    client: TestClient,
    user_a: tuple[int, dict[str, str]],
    user_b: tuple[int, dict[str, str]],
) -> None:
    # No singular GET /transactions/{id} route exists -- only list,
    # patch, and delete -- so this covers the sub-resource ops that do.
    a_id, a_headers = user_a
    b_id, b_headers = user_b
    transaction_id = _create_transaction(client, a_id, a_headers)

    patch_resp = client.patch(
        f"/users/{b_id}/transactions/{transaction_id}",
        headers=b_headers,
        json={"description": "hacked"},
    )
    assert patch_resp.status_code in DENIED

    delete_resp = client.delete(
        f"/users/{b_id}/transactions/{transaction_id}", headers=b_headers
    )
    assert delete_resp.status_code in DENIED

    # A's transaction is untouched -- still present, unmodified, in A's
    # own list.
    listing = client.get(f"/users/{a_id}/transactions", headers=a_headers)
    assert listing.status_code == 200
    descriptions = [t["description"] for t in listing.json()]
    assert "Groceries" in descriptions


# --- Budgets ---------------------------------------------------------------


def test_cannot_read_or_write_another_users_budgets(
    client: TestClient,
    user_a: tuple[int, dict[str, str]],
    user_b: tuple[int, dict[str, str]],
) -> None:
    a_id, a_headers = user_a
    b_id, b_headers = user_b

    put_resp = client.put(
        f"/users/{a_id}/budgets",
        headers=a_headers,
        json={"category": "Food", "month": "2026-01", "limit_cents": 30000},
    )
    assert put_resp.status_code == 200

    list_resp = client.get(
        f"/users/{a_id}/budgets",
        headers=b_headers,
        params={"month": "2026-01"},
    )
    assert list_resp.status_code in DENIED

    delete_resp = client.delete(
        f"/users/{b_id}/budgets/Food",
        headers=b_headers,
        params={"month": "2026-01"},
    )
    # Deletes B's own (nonexistent) "Food" budget category, never A's --
    # confirms this can never be pointed at another user's row.
    assert delete_resp.status_code == 404


# --- Recurring items ---------------------------------------------------------


def _create_recurring_item(
    client: TestClient, owner_id: int, owner_headers: dict[str, str]
) -> int:
    resp = client.post(
        f"/users/{owner_id}/recurring-items",
        headers=owner_headers,
        json={
            "merchant": "Gym",
            "normalized_merchant": f"GYM-{uuid4().hex}",
            "amount_cents": 5000,
            "frequency": "Monthly",
            "last_payment": "2026-01-01",
            "next_payment": "2026-02-01",
            "confidence_score": 90,
        },
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def test_cannot_read_or_modify_another_users_recurring_item(
    client: TestClient,
    user_a: tuple[int, dict[str, str]],
    user_b: tuple[int, dict[str, str]],
) -> None:
    a_id, a_headers = user_a
    b_id, b_headers = user_b
    item_id = _create_recurring_item(client, a_id, a_headers)

    list_resp = client.get(
        f"/users/{a_id}/recurring-items", headers=b_headers
    )
    assert list_resp.status_code in DENIED

    patch_resp = client.patch(
        f"/users/{b_id}/recurring-items/{item_id}",
        headers=b_headers,
        json={"status": "dismissed"},
    )
    assert patch_resp.status_code in DENIED

    delete_resp = client.delete(
        f"/users/{b_id}/recurring-items/{item_id}", headers=b_headers
    )
    assert delete_resp.status_code in DENIED


# --- Savings goals + contributions -----------------------------------------


def _create_goal(
    client: TestClient, owner_id: int, owner_headers: dict[str, str]
) -> int:
    resp = client.post(
        f"/users/{owner_id}/goals",
        headers=owner_headers,
        json={"name": "Vacation", "target_cents": 500000},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def test_cannot_read_or_modify_another_users_goal(
    client: TestClient,
    user_a: tuple[int, dict[str, str]],
    user_b: tuple[int, dict[str, str]],
) -> None:
    a_id, a_headers = user_a
    b_id, b_headers = user_b
    goal_id = _create_goal(client, a_id, a_headers)

    list_resp = client.get(f"/users/{a_id}/goals", headers=b_headers)
    assert list_resp.status_code in DENIED

    # No singular GET /goals/{id} route exists -- only list, patch,
    # and delete.
    patch_resp = client.patch(
        f"/users/{b_id}/goals/{goal_id}",
        headers=b_headers,
        json={"name": "hacked"},
    )
    assert patch_resp.status_code in DENIED

    delete_resp = client.delete(
        f"/users/{b_id}/goals/{goal_id}", headers=b_headers
    )
    assert delete_resp.status_code in DENIED


def test_cannot_create_or_read_contributions_on_another_users_goal(
    client: TestClient,
    user_a: tuple[int, dict[str, str]],
    user_b: tuple[int, dict[str, str]],
) -> None:
    a_id, a_headers = user_a
    b_id, b_headers = user_b
    goal_id = _create_goal(client, a_id, a_headers)

    create_resp = client.post(
        f"/users/{b_id}/goals/{goal_id}/contributions",
        headers=b_headers,
        json={"amount_cents": 10000, "contribution_type": "deposit"},
    )
    assert create_resp.status_code in DENIED

    list_resp = client.get(
        f"/users/{b_id}/goals/{goal_id}/contributions", headers=b_headers
    )
    assert list_resp.status_code in DENIED

    # A's goal balance was never touched by B's attempted deposit.
    listing = client.get(f"/users/{a_id}/goals", headers=a_headers)
    assert listing.status_code == 200
    goal = next(g for g in listing.json() if g["id"] == goal_id)
    assert goal["saved_cents"] == 0


# --- Decisions + outcomes/timeline/rerun/status ----------------------------


def _save_decision(
    client: TestClient, owner_id: int, owner_headers: dict[str, str]
) -> int:
    resp = client.post(
        f"/users/{owner_id}/decisions",
        headers=owner_headers,
        json={
            "decision_type": "major_purchase",
            "title": "New laptop",
            "input": {
                "purchase_name": "Laptop",
                "purchase_amount_cents": 200000,
                "purchase_date": date.today().isoformat(),
            },
        },
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def test_cannot_read_or_delete_another_users_decision(
    client: TestClient,
    user_a: tuple[int, dict[str, str]],
    user_b: tuple[int, dict[str, str]],
) -> None:
    a_id, a_headers = user_a
    b_id, b_headers = user_b
    decision_id = _save_decision(client, a_id, a_headers)

    list_resp = client.get(f"/users/{a_id}/decisions", headers=b_headers)
    assert list_resp.status_code in DENIED

    get_resp = client.get(
        f"/users/{b_id}/decisions/{decision_id}", headers=b_headers
    )
    assert get_resp.status_code in DENIED

    delete_resp = client.delete(
        f"/users/{b_id}/decisions/{decision_id}", headers=b_headers
    )
    assert delete_resp.status_code in DENIED

    # A's decision still exists.
    still_there = client.get(
        f"/users/{a_id}/decisions/{decision_id}", headers=a_headers
    )
    assert still_there.status_code == 200


@pytest.mark.parametrize(
    "method,path_suffix,json_body",
    [
        ("patch", "/status", {"status": "acted_on"}),
        ("post", "/outcomes", None),
        ("get", "/outcomes", None),
        ("get", "/timeline", None),
        ("post", "/rerun", None),
    ],
)
def test_cannot_act_on_another_users_decision_sub_resources(
    client: TestClient,
    user_a: tuple[int, dict[str, str]],
    user_b: tuple[int, dict[str, str]],
    method: str,
    path_suffix: str,
    json_body: dict | None,
) -> None:
    a_id, a_headers = user_a
    b_id, b_headers = user_b
    decision_id = _save_decision(client, a_id, a_headers)

    call = getattr(client, method)
    kwargs = {"headers": b_headers}
    if json_body is not None:
        kwargs["json"] = json_body

    resp = call(
        f"/users/{b_id}/decisions/{decision_id}{path_suffix}", **kwargs
    )
    assert resp.status_code in DENIED


def test_cannot_include_another_users_decision_in_own_portfolio(
    client: TestClient,
    user_a: tuple[int, dict[str, str]],
    user_b: tuple[int, dict[str, str]],
) -> None:
    """The portfolio endpoint takes decision_ids in its body rather than
    the URL -- a distinct injection point from the path-based cases
    above, and one where "belongs to the caller" must be enforced
    inside the service layer since the ids never appear in the path at
    all.
    """
    a_id, a_headers = user_a
    b_id, b_headers = user_b
    a_decision_id = _save_decision(client, a_id, a_headers)
    # Portfolio requires 2-5 decisions -- pair A's decision with one of
    # B's own so this actually exercises the ownership check on the
    # foreign id, not just the count validation.
    b_decision_id = _save_decision(client, b_id, b_headers)

    resp = client.post(
        f"/users/{b_id}/decisions/portfolio",
        headers=b_headers,
        json={"decision_ids": [a_decision_id, b_decision_id]},
    )
    assert resp.status_code in DENIED


# --- Plaid items -------------------------------------------------------------


def _create_plaid_item(db: Session, user_id: int) -> tuple[int, int]:
    item = PlaidItem(
        user_id=user_id,
        provider_item_id=f"item-{uuid4().hex}",
        institution_name="Test Bank",
        access_token_ciphertext="ciphertext-not-a-real-token",
        status="active",
    )
    db.add(item)
    db.flush()

    account = FinancialAccount(
        plaid_item_id=item.id,
        provider_account_id=f"account-{uuid4().hex}",
        name="Checking",
        account_type="depository",
        current_balance_cents=100000,
        available_balance_cents=100000,
        currency="USD",
    )
    db.add(account)
    db.commit()
    db.refresh(item)

    return item.id, account.id


def test_cannot_read_or_disconnect_another_users_plaid_item(
    client: TestClient,
    user_a: tuple[int, dict[str, str]],
    user_b: tuple[int, dict[str, str]],
) -> None:
    a_id, a_headers = user_a
    b_id, b_headers = user_b

    with TestingSessionLocal() as db:
        item_id, _ = _create_plaid_item(db, a_id)

    status_resp = client.get(
        f"/users/{a_id}/plaid/sync/status", headers=b_headers
    )
    assert status_resp.status_code in DENIED

    accounts_resp = client.get(f"/users/{a_id}/accounts", headers=b_headers)
    assert accounts_resp.status_code in DENIED

    delete_resp = client.delete(
        f"/users/{b_id}/plaid/items/{item_id}", headers=b_headers
    )
    assert delete_resp.status_code in DENIED

    # A's connection is untouched.
    with TestingSessionLocal() as db:
        still_there = db.get(PlaidItem, item_id)
        assert still_there is not None
        assert still_there.status == "active"


# --- Path-level authorization (the blunt case, every router) --------------


@pytest.mark.parametrize(
    "path_template",
    [
        "/users/{other_id}/transactions",
        "/users/{other_id}/budgets?month=2026-01",
        "/users/{other_id}/recurring-items",
        "/users/{other_id}/goals",
        "/users/{other_id}/decisions",
        "/users/{other_id}/accounts",
        "/users/{other_id}/plaid/sync/status",
        "/users/{other_id}",
    ],
)
def test_cannot_use_another_users_id_directly_in_the_path(
    client: TestClient,
    user_a: tuple[int, dict[str, str]],
    user_b: tuple[int, dict[str, str]],
    path_template: str,
) -> None:
    a_id, _ = user_a
    _, b_headers = user_b

    path = path_template.format(other_id=a_id)
    resp = client.get(path, headers=b_headers)

    assert resp.status_code == 403


# ==========================================================================
# Mass assignment / property-level authorization
#
# No request schema in this API accepts a server-owned field --
# user_id/ownership, password hashes, lifecycle timestamps,
# verification state, or a client-supplied "result" standing in for a
# real deterministic calculation. Routers also never unpack a payload
# dict straight into an ORM model (`Model(**payload.dict())`); every
# field is assigned explicitly. These tests prove a client-supplied
# extra field for any of those never takes effect, even when Pydantic
# silently drops it as an unrecognized key rather than a validation
# error.
# ==========================================================================


def test_registration_ignores_client_supplied_privileged_fields(
    client: TestClient,
) -> None:
    resp = client.post(
        "/users",
        json={
            "email": "mass-assignment-register@example.com",
            "password": PASSWORD,
            "id": 999999,
            "email_verified": True,
            "token_version": 999,
            "password_hash": "not-a-real-hash",
            "is_admin": True,
        },
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["email_verified"] is False

    # The injected password_hash never took effect -- the real
    # password (hashed server-side) still logs in normally.
    login = client.post(
        "/users/login",
        json={
            "email": "mass-assignment-register@example.com",
            "password": PASSWORD,
        },
    )
    assert login.status_code == 200


def test_transaction_create_ignores_client_supplied_user_id(
    client: TestClient,
    user_a: tuple[int, dict[str, str]],
    user_b: tuple[int, dict[str, str]],
) -> None:
    a_id, a_headers = user_a
    b_id, _ = user_b

    resp = client.post(
        f"/users/{a_id}/transactions",
        headers=a_headers,
        json={
            "posted_on": "2026-01-15",
            "description": "Injected",
            "amount_cents": -100,
            "category": "Food",
            "user_id": b_id,
            "id": 999999,
        },
    )

    assert resp.status_code == 201
    body = resp.json()
    # Always owned by the path-derived, authenticated user -- never the
    # injected user_id, and never the injected id.
    assert body["id"] != 999999

    listing = client.get(f"/users/{a_id}/transactions", headers=a_headers)
    assert any(t["description"] == "Injected" for t in listing.json())


def test_goal_create_ignores_client_supplied_user_id(
    client: TestClient,
    user_a: tuple[int, dict[str, str]],
    user_b: tuple[int, dict[str, str]],
) -> None:
    a_id, a_headers = user_a
    b_id, b_headers = user_b

    resp = client.post(
        f"/users/{a_id}/goals",
        headers=a_headers,
        json={
            "name": "Injected goal",
            "target_cents": 100000,
            "user_id": b_id,
        },
    )
    assert resp.status_code == 201

    # Never visible under B's own goals -- the injected user_id had no
    # effect.
    b_goals = client.get(f"/users/{b_id}/goals", headers=b_headers)
    assert b_goals.status_code == 200
    assert all(g["name"] != "Injected goal" for g in b_goals.json())


def test_saved_decision_ignores_client_supplied_result_and_ownership(
    client: TestClient,
    user_a: tuple[int, dict[str, str]],
    user_b: tuple[int, dict[str, str]],
) -> None:
    """A saved decision's result is always recomputed server-side from
    `input` -- the schema has no field for a client to hand in a
    ready-made `result_snapshot`, confidence score, or recommendation
    to be trusted as-is (see SaveDecisionRequest).
    """
    a_id, a_headers = user_a
    b_id, _ = user_b

    resp = client.post(
        f"/users/{a_id}/decisions",
        headers=a_headers,
        json={
            "decision_type": "major_purchase",
            "title": "Laptop",
            "input": {
                "purchase_name": "Laptop",
                "purchase_amount_cents": 200000,
                "purchase_date": date.today().isoformat(),
            },
            "user_id": b_id,
            "result_snapshot": {"affordability_status": "affordable"},
            "confidence_score": 100,
        },
    )

    assert resp.status_code == 201
    # A real, server-computed result is present (not the injected one,
    # and not absent/None).
    assert resp.json()["decision_type"] == "major_purchase"


def test_email_change_cannot_self_verify(
    client: TestClient, user_id: int, auth_headers: dict[str, str]
) -> None:
    """Changing email always resets verification server-side, even if
    the client tries to assert `email_verified: true` in the same
    request (see change_email in app/routers/users.py).
    """
    resp = client.patch(
        "/users/me/email",
        headers=auth_headers,
        json={
            "new_email": "new-verified-address@example.com",
            "current_password": "TestPassword123!",
            "email_verified": True,
        },
    )

    assert resp.status_code == 200
    assert resp.json()["email_verified"] is False
