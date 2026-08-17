from datetime import date, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DecisionOutcome, FinancialAccount, PlaidItem, User
from app.schemas import SaveDecisionRequest
from app.services import decision_history_service, decision_outcome_service
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


def _what_if_input() -> dict:
    return {
        "scenario_type": "one_time_expense",
        "scenario_name": "New laptop",
        "amount_cents": 200_000,
        "effective_date": (TEST_DATE + timedelta(days=5)).isoformat(),
    }


def test_save_what_if_decision_stores_real_result() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)

        request = SaveDecisionRequest(
            decision_type="what_if",
            title="What if I buy a laptop?",
            input=_what_if_input(),
        )

        decision = decision_history_service.save_decision(
            db, user.id, request, as_of=TEST_DATE
        )

        assert decision.decision_type == "what_if"
        assert "baseline" in decision.result_snapshot
        assert "scenario" in decision.result_snapshot
        assert "impact" in decision.result_snapshot


def test_rerun_what_if_decision() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)

        decision = decision_history_service.save_decision(
            db,
            user.id,
            SaveDecisionRequest(
                decision_type="what_if",
                title="What if I buy a laptop?",
                input=_what_if_input(),
            ),
            as_of=TEST_DATE,
        )

        outcome = decision_history_service.rerun_decision(
            db, user.id, decision.id, as_of=TEST_DATE
        )

        assert outcome is not None
        _, _, result_snapshot = outcome
        assert "baseline" in result_snapshot


def _buy_now_vs_wait_input() -> dict:
    return {
        "purchase_name": "Laptop",
        "purchase_amount_cents": 150_000,
        "buy_now_date": TEST_DATE.isoformat(),
        "wait_until_date": date(2026, 9, 8).isoformat(),
    }


def test_save_buy_now_vs_wait_decision_stores_real_result() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)

        request = SaveDecisionRequest(
            decision_type="buy_now_vs_wait",
            title="Laptop: now or wait?",
            input=_buy_now_vs_wait_input(),
        )

        decision = decision_history_service.save_decision(
            db, user.id, request, as_of=TEST_DATE
        )

        assert decision.decision_type == "buy_now_vs_wait"
        assert decision.result_snapshot["recommended_timing"] in (
            "buy_now",
            "wait",
            "either",
            "neither",
        )
        assert "now" in decision.result_snapshot
        assert "wait" in decision.result_snapshot


def test_rerun_buy_now_vs_wait_decision() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=5_000_000)

        decision = decision_history_service.save_decision(
            db,
            user.id,
            SaveDecisionRequest(
                decision_type="buy_now_vs_wait",
                title="Laptop: now or wait?",
                input=_buy_now_vs_wait_input(),
            ),
            as_of=TEST_DATE,
        )

        outcome = decision_history_service.rerun_decision(
            db, user.id, decision.id, as_of=TEST_DATE
        )

        assert outcome is not None
        _unchanged_decision, evaluated_at, fresh_result = outcome
        assert evaluated_at == TEST_DATE
        assert fresh_result["purchase_amount_cents"] == 150_000
        assert "recommended_timing" in fresh_result


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


def test_decisions_http_lifecycle_for_buy_now_vs_wait(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "decisions-bnw-http")

    save_response = client.post(
        f"/users/{user_id}/decisions",
        headers=headers,
        json={
            "decision_type": "buy_now_vs_wait",
            "title": "Laptop: now or wait?",
            "input": {
                "purchase_name": "Laptop",
                "purchase_amount_cents": 150_000,
                "buy_now_date": date.today().isoformat(),
                "wait_until_date": date(
                    date.today().year, 12, 28
                ).isoformat(),
            },
        },
    )
    assert save_response.status_code == 201
    decision_id = save_response.json()["id"]
    assert save_response.json()["decision_type"] == "buy_now_vs_wait"

    rerun_response = client.post(
        f"/users/{user_id}/decisions/{decision_id}/rerun",
        headers=headers,
    )
    assert rerun_response.status_code == 200
    assert "recommended_timing" in rerun_response.json()["result_snapshot"]


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


# --- Lifecycle -----------------------------------------------------


def test_new_saved_decision_defaults_to_status_saved() -> None:
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

        assert decision.status == "saved"
        assert decision.acted_on_at is None


def test_marking_acted_on_sets_acted_on_at() -> None:
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

        updated = decision_history_service.update_decision_status(
            db, user.id, decision.id, "acted_on"
        )

        assert updated is not None
        assert updated.status == "acted_on"
        assert updated.acted_on_at is not None


def test_dismissing_after_acted_on_preserves_acted_on_at() -> None:
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

        acted_on = decision_history_service.update_decision_status(
            db, user.id, decision.id, "acted_on"
        )
        assert acted_on is not None
        original_acted_on_at = acted_on.acted_on_at

        dismissed = decision_history_service.update_decision_status(
            db, user.id, decision.id, "dismissed"
        )

        assert dismissed is not None
        assert dismissed.status == "dismissed"
        # Audit evidence of when the user first acted must survive a
        # later status change -- never silently erased.
        assert dismissed.acted_on_at == original_acted_on_at


def test_dismissed_directly_from_saved_works() -> None:
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

        dismissed = decision_history_service.update_decision_status(
            db, user.id, decision.id, "dismissed"
        )

        assert dismissed is not None
        assert dismissed.status == "dismissed"
        assert dismissed.acted_on_at is None


def test_update_status_scoped_to_owner() -> None:
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

        result = decision_history_service.update_decision_status(
            db, other.id, decision.id, "acted_on"
        )

        assert result is None

        # Confirm nothing was mutated for the real owner.
        refetched = decision_history_service.get_decision(
            db, owner.id, decision.id
        )
        assert refetched.status == "saved"


def test_update_status_endpoint_full_lifecycle(client: TestClient) -> None:
    user_id, headers = register_and_login(client, "decisions-lifecycle")

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
    assert save_response.json()["status"] == "saved"
    assert save_response.json()["acted_on_at"] is None

    patch_response = client.patch(
        f"/users/{user_id}/decisions/{decision_id}/status",
        headers=headers,
        json={"status": "acted_on"},
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["status"] == "acted_on"
    assert patch_response.json()["acted_on_at"] is not None


def test_update_status_endpoint_rejects_invalid_status(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "decisions-bad-status")

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
    decision_id = save_response.json()["id"]

    response = client.patch(
        f"/users/{user_id}/decisions/{decision_id}/status",
        headers=headers,
        json={"status": "not_a_real_status"},
    )

    assert response.status_code == 422


def test_update_status_endpoint_blocks_other_user(
    client: TestClient,
) -> None:
    owner_id, owner_headers = register_and_login(
        client, "decisions-status-owner"
    )
    _other_id, other_headers = register_and_login(
        client, "decisions-status-other"
    )

    save_response = client.post(
        f"/users/{owner_id}/decisions",
        headers=owner_headers,
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
    decision_id = save_response.json()["id"]

    response = client.patch(
        f"/users/{owner_id}/decisions/{decision_id}/status",
        headers=other_headers,
        json={"status": "acted_on"},
    )

    assert response.status_code == 403


# --- Outcomes --------------------------------------------------------


def test_cannot_evaluate_outcome_for_saved_decision() -> None:
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

        try:
            decision_outcome_service.evaluate_decision_outcome(
                db, user.id, decision.id, as_of=TEST_DATE
            )
            assert False, "expected ValueError"
        except ValueError:
            pass

        assert (
            db.scalar(
                select(DecisionOutcome).where(
                    DecisionOutcome.decision_id == decision.id
                )
            )
            is None
        )


def test_acted_on_decision_can_be_evaluated_and_snapshot_preserved() -> None:
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
        original_result_snapshot = dict(decision.result_snapshot)
        original_safe_after = original_result_snapshot[
            "safe_to_spend_after_purchase_cents"
        ]

        decision_history_service.update_decision_status(
            db, user.id, decision.id, "acted_on"
        )

        # Real liquid balance changes after the decision was saved --
        # the outcome's "current" figure must reflect that.
        create_account(db, user, available_balance_cents=9_000_000)

        outcome = decision_outcome_service.evaluate_decision_outcome(
            db, user.id, decision.id, as_of=TEST_DATE
        )

        assert outcome is not None
        assert outcome.decision_id == decision.id
        assert (
            outcome.current_result_snapshot[
                "safe_to_spend_after_purchase_cents"
            ]
            > original_safe_after
        )

        # The original saved result_snapshot must never be mutated.
        refetched_decision = decision_history_service.get_decision(
            db, user.id, decision.id
        )
        assert refetched_decision.result_snapshot == original_result_snapshot


def test_outcome_comparison_numeric_delta_and_unchanged_metric() -> None:
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
        before_safe_after = decision.result_snapshot[
            "safe_to_spend_after_purchase_cents"
        ]

        decision_history_service.update_decision_status(
            db, user.id, decision.id, "acted_on"
        )
        create_account(db, user, available_balance_cents=9_000_000)

        outcome = decision_outcome_service.evaluate_decision_outcome(
            db, user.id, decision.id, as_of=TEST_DATE
        )
        assert outcome is not None

        comparison = outcome.comparison_snapshot
        metrics_by_path = {m["path"]: m for m in comparison["metrics"]}

        safe_after_metric = metrics_by_path[
            "safe_to_spend_after_purchase_cents"
        ]
        assert safe_after_metric["change_type"] == "numeric"
        assert safe_after_metric["before"] == before_safe_after
        assert (
            safe_after_metric["delta"]
            == safe_after_metric["current"] - safe_after_metric["before"]
        )
        assert safe_after_metric["delta"] > 0

        # purchase_amount_cents is identical between the two runs --
        # it must still be reported (present in both), but as an
        # unchanged metric with a zero delta.
        amount_metric = metrics_by_path["purchase_amount_cents"]
        assert amount_metric["before"] == amount_metric["current"]
        assert amount_metric["delta"] == 0

        assert comparison["summary"]["metrics_compared"] == len(
            comparison["metrics"]
        )
        assert comparison["summary"]["metrics_changed"] <= comparison[
            "summary"
        ]["metrics_compared"]
        assert comparison["changed"] is True


def test_outcome_history_newest_first() -> None:
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
        decision_history_service.update_decision_status(
            db, user.id, decision.id, "acted_on"
        )

        first = decision_outcome_service.evaluate_decision_outcome(
            db, user.id, decision.id, as_of=TEST_DATE
        )
        second = decision_outcome_service.evaluate_decision_outcome(
            db, user.id, decision.id, as_of=TEST_DATE
        )

        assert first is not None and second is not None
        assert first.id != second.id

        history = decision_outcome_service.list_decision_outcomes(
            db, user.id, decision.id
        )

        assert [o.id for o in history] == [second.id, first.id]


def test_delete_saved_decision_cascades_outcomes() -> None:
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
        decision_history_service.update_decision_status(
            db, user.id, decision.id, "acted_on"
        )
        outcome = decision_outcome_service.evaluate_decision_outcome(
            db, user.id, decision.id, as_of=TEST_DATE
        )
        assert outcome is not None
        outcome_id = outcome.id

        deleted = decision_history_service.delete_decision(
            db, user.id, decision.id
        )
        assert deleted is True

        assert (
            db.scalar(
                select(DecisionOutcome).where(
                    DecisionOutcome.id == outcome_id
                )
            )
            is None
        )


def test_outcomes_are_scoped_to_owner() -> None:
    with TestingSessionLocal() as db:
        owner = create_user(db)
        other = create_user(db)
        create_account(db, owner, available_balance_cents=5_000_000)

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
        decision_history_service.update_decision_status(
            db, owner.id, decision.id, "acted_on"
        )
        decision_outcome_service.evaluate_decision_outcome(
            db, owner.id, decision.id, as_of=TEST_DATE
        )

        assert (
            decision_outcome_service.evaluate_decision_outcome(
                db, other.id, decision.id, as_of=TEST_DATE
            )
            is None
        )
        assert (
            decision_outcome_service.list_decision_outcomes(
                db, other.id, decision.id
            )
            is None
        )


def test_corrupt_persisted_input_fails_safely_without_creating_outcome() -> (
    None
):
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
        decision_history_service.update_decision_status(
            db, user.id, decision.id, "acted_on"
        )

        # Simulate a corrupted/legacy input_snapshot that no longer
        # matches the request schema for this decision type.
        decision.input_snapshot = {"purchase_name": "Laptop"}
        db.commit()

        try:
            decision_outcome_service.evaluate_decision_outcome(
                db, user.id, decision.id, as_of=TEST_DATE
            )
            assert False, "expected ValueError"
        except ValueError:
            pass

        assert (
            db.scalar(
                select(DecisionOutcome).where(
                    DecisionOutcome.decision_id == decision.id
                )
            )
            is None
        )


def test_outcome_http_lifecycle(client: TestClient) -> None:
    user_id, headers = register_and_login(client, "decisions-outcome-http")

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
    decision_id = save_response.json()["id"]

    # Not acted on yet -- evaluating must fail.
    blocked_response = client.post(
        f"/users/{user_id}/decisions/{decision_id}/outcomes",
        headers=headers,
    )
    assert blocked_response.status_code == 422

    client.patch(
        f"/users/{user_id}/decisions/{decision_id}/status",
        headers=headers,
        json={"status": "acted_on"},
    )

    evaluate_response = client.post(
        f"/users/{user_id}/decisions/{decision_id}/outcomes",
        headers=headers,
    )
    assert evaluate_response.status_code == 201
    body = evaluate_response.json()
    assert body["decision_id"] == decision_id
    assert "comparison_snapshot" in body
    assert "current_result_snapshot" in body

    history_response = client.get(
        f"/users/{user_id}/decisions/{decision_id}/outcomes",
        headers=headers,
    )
    assert history_response.status_code == 200
    assert len(history_response.json()) == 1

    other_user_id, other_headers = register_and_login(
        client, "decisions-outcome-other"
    )
    cross_user_response = client.get(
        f"/users/{other_user_id}/decisions/{decision_id}/outcomes",
        headers=other_headers,
    )
    assert cross_user_response.status_code == 404


def _http_major_purchase_input() -> dict:
    return {
        "purchase_name": "Laptop",
        "purchase_amount_cents": 150_000,
        "purchase_date": date.today().isoformat(),
    }


def test_list_decisions_includes_outcome_metadata_defaults(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client, "decisions-outcome-meta-def"
    )

    client.post(
        f"/users/{user_id}/decisions",
        headers=headers,
        json={
            "decision_type": "major_purchase",
            "title": "Laptop",
            "input": _http_major_purchase_input(),
        },
    )

    list_response = client.get(f"/users/{user_id}/decisions", headers=headers)
    assert list_response.status_code == 200

    body = list_response.json()
    assert len(body) == 1
    assert body[0]["outcome_count"] == 0
    assert body[0]["latest_outcome_at"] is None


def test_list_and_detail_reflect_persisted_outcome_metadata(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client, "decisions-outcome-meta-pst"
    )

    save_response = client.post(
        f"/users/{user_id}/decisions",
        headers=headers,
        json={
            "decision_type": "major_purchase",
            "title": "Laptop",
            "input": _http_major_purchase_input(),
        },
    )
    decision_id = save_response.json()["id"]

    client.patch(
        f"/users/{user_id}/decisions/{decision_id}/status",
        headers=headers,
        json={"status": "acted_on"},
    )

    first_outcome = client.post(
        f"/users/{user_id}/decisions/{decision_id}/outcomes",
        headers=headers,
    ).json()

    list_body = client.get(
        f"/users/{user_id}/decisions", headers=headers
    ).json()
    assert list_body[0]["outcome_count"] == 1
    assert list_body[0]["latest_outcome_at"] == first_outcome["evaluated_at"]

    second_outcome = client.post(
        f"/users/{user_id}/decisions/{decision_id}/outcomes",
        headers=headers,
    ).json()

    list_body = client.get(
        f"/users/{user_id}/decisions", headers=headers
    ).json()
    assert list_body[0]["outcome_count"] == 2
    assert list_body[0]["latest_outcome_at"] == second_outcome["evaluated_at"]

    detail_body = client.get(
        f"/users/{user_id}/decisions/{decision_id}", headers=headers
    ).json()
    assert detail_body["outcome_count"] == 2
    assert detail_body["latest_outcome_at"] == second_outcome["evaluated_at"]


def test_outcome_metadata_counts_correctly_across_multiple_decisions(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client, "decisions-outcome-meta-mlt"
    )

    decision_ids = []
    for index in range(2):
        save_response = client.post(
            f"/users/{user_id}/decisions",
            headers=headers,
            json={
                "decision_type": "major_purchase",
                "title": f"Laptop {index}",
                "input": _http_major_purchase_input(),
            },
        )
        decision_id = save_response.json()["id"]
        decision_ids.append(decision_id)

        client.patch(
            f"/users/{user_id}/decisions/{decision_id}/status",
            headers=headers,
            json={"status": "acted_on"},
        )

    # Only the first decision gets outcomes evaluated, twice.
    client.post(
        f"/users/{user_id}/decisions/{decision_ids[0]}/outcomes",
        headers=headers,
    )
    client.post(
        f"/users/{user_id}/decisions/{decision_ids[0]}/outcomes",
        headers=headers,
    )

    list_body = {
        item["id"]: item
        for item in client.get(
            f"/users/{user_id}/decisions", headers=headers
        ).json()
    }
    assert list_body[decision_ids[0]]["outcome_count"] == 2
    assert list_body[decision_ids[1]]["outcome_count"] == 0
    assert list_body[decision_ids[1]]["latest_outcome_at"] is None


def test_list_decisions_outcome_metadata_scoped_to_owner() -> None:
    with TestingSessionLocal() as db:
        owner = create_user(db)
        other = create_user(db)
        create_account(db, owner)
        create_account(db, other)

        owner_decision = decision_history_service.save_decision(
            db,
            owner.id,
            SaveDecisionRequest(
                decision_type="major_purchase",
                title="Owner Laptop",
                input=_major_purchase_input(),
            ),
            as_of=TEST_DATE,
        )
        decision_history_service.update_decision_status(
            db, owner.id, owner_decision.id, "acted_on"
        )
        decision_outcome_service.evaluate_decision_outcome(
            db, owner.id, owner_decision.id, as_of=TEST_DATE
        )

        other_decision = decision_history_service.save_decision(
            db,
            other.id,
            SaveDecisionRequest(
                decision_type="major_purchase",
                title="Other Laptop",
                input=_major_purchase_input(),
            ),
            as_of=TEST_DATE,
        )

        owner_listed = decision_history_service.list_decisions(db, owner.id)
        assert len(owner_listed) == 1
        assert owner_listed[0].outcome_count == 1
        assert owner_listed[0].latest_outcome_at is not None

        other_listed = decision_history_service.list_decisions(db, other.id)
        assert len(other_listed) == 1
        assert other_listed[0].id == other_decision.id
        assert other_listed[0].outcome_count == 0
        assert other_listed[0].latest_outcome_at is None
