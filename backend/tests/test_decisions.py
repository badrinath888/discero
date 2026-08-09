from datetime import date
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import FinancialAccount, PlaidItem, User
from app.schemas import SaveDecisionRequest
from app.services import decision_history_service
from tests.conftest import TestingSessionLocal


TEST_DATE = date(2026, 8, 8)


def create_user(db: Session) -> User:
    user = User(
        email=f"decisions-{uuid4().hex}@example.com",
        password_hash="test-password-hash",
        email_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_account(
    db: Session, user: User, *, available_balance_cents: int = 5_000_000
) -> None:
    item = PlaidItem(
        user_id=user.id,
        provider_item_id=f"item-{uuid4().hex}",
        institution_name="Test Bank",
        access_token_ciphertext="encrypted-test-token",
        status="active",
    )
    db.add(item)
    db.flush()

    account = FinancialAccount(
        plaid_item_id=item.id,
        provider_account_id=f"account-{uuid4().hex}",
        name="Checking",
        account_type="depository",
        current_balance_cents=available_balance_cents,
        available_balance_cents=available_balance_cents,
        currency="USD",
    )
    db.add(account)
    db.commit()


def register_and_login(client: TestClient, prefix: str) -> tuple[int, dict]:
    email = f"{prefix}-{uuid4().hex}@example.com"
    password = "TestPassword123!"

    create_response = client.post(
        "/users", json={"email": email, "password": password}
    )
    assert create_response.status_code == 201

    login_response = client.post(
        "/users/login", json={"email": email, "password": password}
    )
    assert login_response.status_code == 200

    return create_response.json()["id"], {
        "Authorization": f"Bearer {login_response.json()['access_token']}"
    }


def _major_purchase_input() -> dict:
    return {
        "purchase_name": "Laptop",
        "purchase_amount_cents": 150_000,
        "purchase_date": TEST_DATE.isoformat(),
    }


def _stress_test_input() -> dict:
    return {
        "scenario_type": "emergency_expense",
        "scenario_name": "Car repair",
        "stress_amount_cents": 100_000,
        "event_date": TEST_DATE.isoformat(),
    }


def _scenario_comparison_input() -> dict:
    return {
        "option_a": _major_purchase_input(),
        "option_b": {
            "purchase_name": "Better Laptop",
            "purchase_amount_cents": 300_000,
            "purchase_date": TEST_DATE.isoformat(),
        },
    }


def test_save_major_purchase_decision_stores_real_result() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)

        request = SaveDecisionRequest(
            decision_type="major_purchase",
            title="Laptop Purchase",
            input=_major_purchase_input(),
        )

        decision = decision_history_service.save_decision(
            db, user.id, request, as_of=TEST_DATE
        )

        assert decision.title == "Laptop Purchase"
        assert decision.decision_type == "major_purchase"
        assert decision.input_snapshot["purchase_amount_cents"] == 150_000
        assert decision.result_snapshot["affordability_status"] in (
            "affordable",
            "caution",
            "not_affordable",
        )
        assert "safe_to_spend_after_purchase_cents" in decision.result_snapshot


def test_save_scenario_comparison_decision() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)

        request = SaveDecisionRequest(
            decision_type="scenario_comparison",
            title="Laptop A vs B",
            input=_scenario_comparison_input(),
        )

        decision = decision_history_service.save_decision(
            db, user.id, request, as_of=TEST_DATE
        )

        assert decision.result_snapshot["recommended_option"] in (
            "option_a",
            "option_b",
            "tie",
        )


def test_save_stress_test_decision() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)

        request = SaveDecisionRequest(
            decision_type="stress_test",
            title="Car Repair Stress Test",
            input=_stress_test_input(),
        )

        decision = decision_history_service.save_decision(
            db, user.id, request, as_of=TEST_DATE
        )

        assert decision.result_snapshot["risk_level"] in (
            "resilient",
            "strained",
            "critical",
        )


def test_save_decision_with_malformed_input_raises() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)

        request = SaveDecisionRequest(
            decision_type="major_purchase",
            title="Bad Input",
            input={"purchase_name": "Laptop"},  # missing required fields
        )

        try:
            decision_history_service.save_decision(
                db, user.id, request, as_of=TEST_DATE
            )
            assert False, "expected ValueError"
        except ValueError:
            pass


def test_list_decisions_orders_newest_first() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)

        first = decision_history_service.save_decision(
            db,
            user.id,
            SaveDecisionRequest(
                decision_type="major_purchase",
                title="First",
                input=_major_purchase_input(),
            ),
            as_of=TEST_DATE,
        )
        second = decision_history_service.save_decision(
            db,
            user.id,
            SaveDecisionRequest(
                decision_type="major_purchase",
                title="Second",
                input=_major_purchase_input(),
            ),
            as_of=TEST_DATE,
        )

        results = decision_history_service.list_decisions(db, user.id)

        assert [d.id for d in results] == [second.id, first.id]


def test_get_and_delete_decision() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)

        decision = decision_history_service.save_decision(
            db,
            user.id,
            SaveDecisionRequest(
                decision_type="major_purchase",
                title="Laptop",
                input=_major_purchase_input(),
            ),
            as_of=TEST_DATE,
        )

        fetched = decision_history_service.get_decision(
            db, user.id, decision.id
        )
        assert fetched is not None
        assert fetched.id == decision.id

        deleted = decision_history_service.delete_decision(
            db, user.id, decision.id
        )
        assert deleted is True

        assert (
            decision_history_service.get_decision(db, user.id, decision.id)
            is None
        )
        assert decision_history_service.delete_decision(
            db, user.id, decision.id
        ) is False


def test_decisions_are_scoped_to_owner() -> None:
    with TestingSessionLocal() as db:
        owner = create_user(db)
        other = create_user(db)
        create_account(db, owner)

        decision = decision_history_service.save_decision(
            db,
            owner.id,
            SaveDecisionRequest(
                decision_type="major_purchase",
                title="Laptop",
                input=_major_purchase_input(),
            ),
            as_of=TEST_DATE,
        )

        assert (
            decision_history_service.get_decision(db, other.id, decision.id)
            is None
        )
        assert (
            decision_history_service.delete_decision(
                db, other.id, decision.id
            )
            is False
        )
        assert decision_history_service.list_decisions(db, other.id) == []


def test_rerun_reflects_current_data_without_mutating_saved_snapshot() -> (
    None
):
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=5_000_000)

        decision = decision_history_service.save_decision(
            db,
            user.id,
            SaveDecisionRequest(
                decision_type="major_purchase",
                title="Laptop",
                input=_major_purchase_input(),
            ),
            as_of=TEST_DATE,
        )
        original_snapshot = dict(decision.result_snapshot)
        original_safe_before = original_snapshot[
            "safe_to_spend_before_purchase_cents"
        ]

        # The user's real liquid balance changes after saving --
        # "run again" must reflect that, while the saved snapshot must
        # stay exactly as it was "then".
        create_account(db, user, available_balance_cents=9_000_000)

        outcome = decision_history_service.rerun_decision(
            db, user.id, decision.id, as_of=TEST_DATE
        )

        assert outcome is not None
        unchanged_decision, evaluated_at, fresh_result = outcome

        assert evaluated_at == TEST_DATE
        assert unchanged_decision.result_snapshot == original_snapshot
        assert fresh_result["purchase_amount_cents"] == 150_000
        assert (
            fresh_result["safe_to_spend_before_purchase_cents"]
            > original_safe_before
        )

        # Re-fetching from the DB confirms nothing was persisted/mutated.
        refetched = decision_history_service.get_decision(
            db, user.id, decision.id
        )
        assert refetched.result_snapshot == original_snapshot


def test_rerun_missing_decision_returns_none() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)

        outcome = decision_history_service.rerun_decision(
            db, user.id, 999_999
        )

        assert outcome is None


# --- Router-level HTTP tests -----------------------------------------


def test_decisions_endpoint_requires_authentication(
    client: TestClient,
) -> None:
    response = client.get("/users/9999/decisions")
    assert response.status_code == 401


def test_decisions_endpoint_blocks_other_user(client: TestClient) -> None:
    user_id, headers = register_and_login(client, "decisions-owner")

    response = client.get(
        f"/users/{user_id + 1}/decisions", headers=headers
    )

    assert response.status_code == 403


def test_decisions_full_http_lifecycle(client: TestClient) -> None:
    user_id, headers = register_and_login(client, "decisions-http")

    save_response = client.post(
        f"/users/{user_id}/decisions",
        headers=headers,
        json={
            "decision_type": "major_purchase",
            "title": "Laptop",
            "input": {
                "purchase_name": "Laptop",
                "purchase_amount_cents": 150_000,
                "purchase_date": date.today().isoformat(),
            },
        },
    )
    assert save_response.status_code == 201
    decision_id = save_response.json()["id"]

    list_response = client.get(
        f"/users/{user_id}/decisions", headers=headers
    )
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    get_response = client.get(
        f"/users/{user_id}/decisions/{decision_id}", headers=headers
    )
    assert get_response.status_code == 200

    rerun_response = client.post(
        f"/users/{user_id}/decisions/{decision_id}/rerun",
        headers=headers,
    )
    assert rerun_response.status_code == 200
    assert rerun_response.json()["decision_id"] == decision_id

    delete_response = client.delete(
        f"/users/{user_id}/decisions/{decision_id}", headers=headers
    )
    assert delete_response.status_code == 204

    missing_response = client.get(
        f"/users/{user_id}/decisions/{decision_id}", headers=headers
    )
    assert missing_response.status_code == 404


def test_save_decision_endpoint_rejects_malformed_input(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "decisions-bad-input")

    response = client.post(
        f"/users/{user_id}/decisions",
        headers=headers,
        json={
            "decision_type": "major_purchase",
            "title": "Bad",
            "input": {"purchase_name": "Laptop"},
        },
    )

    assert response.status_code == 422


def test_save_decision_endpoint_rejects_unknown_decision_type(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "decisions-bad-type")

    response = client.post(
        f"/users/{user_id}/decisions",
        headers=headers,
        json={
            "decision_type": "not_a_real_type",
            "title": "Bad",
            "input": {},
        },
    )

    assert response.status_code == 422
