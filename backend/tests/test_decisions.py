from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.models import (
    DecisionOutcome,
    FinancialAccount,
    PlaidItem,
    SavedDecision,
    User,
)
from app.schemas import (
    DecisionCalibrationMetricGroupOut,
    DecisionCalibrationOut,
    SaveDecisionRequest,
)
from app.routers import decisions as decisions_router
from app.services import (
    decision_adaptive_intelligence_service,
    decision_calibration_service,
    decision_change_explanation_service,
    decision_dashboard_intelligence_service,
    decision_history_service,
    decision_outcome_service,
    decision_review_service,
    decision_timeline_service,
)
from tests.conftest import TestingSessionLocal, test_engine


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


# --- Decision calibration ------------------------------------------------


def _numeric_metric(path: str, before: float, current: float) -> dict:
    return {
        "path": path,
        "before": before,
        "current": current,
        "delta": current - before,
        "change_type": "numeric",
    }


def _acted_on_decision(
    db: Session,
    user: User,
    *,
    decision_type: str = "major_purchase",
    title: str = "Laptop",
) -> SavedDecision:
    payload = (
        _major_purchase_input()
        if decision_type == "major_purchase"
        else _stress_test_input()
    )
    decision = decision_history_service.save_decision(
        db,
        user.id,
        SaveDecisionRequest(
            decision_type=decision_type,
            title=title,
            input=payload,
        ),
        as_of=TEST_DATE,
    )
    decision_history_service.update_decision_status(
        db, user.id, decision.id, "acted_on"
    )
    return decision


def _persist_outcome(
    db: Session,
    user: User,
    decision: SavedDecision,
    metrics: list[dict],
    *,
    evaluated_at: datetime | None = None,
) -> DecisionOutcome:
    metrics_changed = sum(
        1 for metric in metrics if metric["before"] != metric["current"]
    )
    comparison_snapshot = {
        "changed": metrics_changed > 0,
        "metrics": metrics,
        "summary": {
            "metrics_compared": len(metrics),
            "metrics_changed": metrics_changed,
        },
    }
    outcome = DecisionOutcome(
        decision_id=decision.id,
        user_id=user.id,
        evaluated_at=evaluated_at or datetime.now(timezone.utc),
        current_result_snapshot=decision.result_snapshot,
        comparison_snapshot=comparison_snapshot,
    )
    db.add(outcome)
    db.commit()
    db.refresh(outcome)
    return outcome


def test_calibration_with_no_outcomes_is_insufficient_data() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)

        calibration = decision_calibration_service.get_decision_calibration(
            db, user.id
        )

        assert calibration.tracked_decisions == 0
        assert calibration.outcome_checks == 0
        assert calibration.numeric_metrics_compared == 0
        assert calibration.changed_numeric_metrics == 0
        assert calibration.directional_metrics_compared == 0
        assert calibration.favorable_count == 0
        assert calibration.unfavorable_count == 0
        assert calibration.unchanged_count == 0
        assert calibration.favorable_rate is None
        assert calibration.unfavorable_rate is None
        assert calibration.calibration_label == "insufficient_data"
        assert calibration.metric_groups == []
        assert calibration.decision_types == []


def test_calibration_one_decision_one_outcome_is_insufficient_data() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)
        decision = _acted_on_decision(db, user)
        _persist_outcome(
            db,
            user,
            decision,
            [_numeric_metric("safe_to_spend_after_purchase_cents", 100_000, 150_000)],
        )

        calibration = decision_calibration_service.get_decision_calibration(
            db, user.id
        )

        assert calibration.tracked_decisions == 1
        assert calibration.outcome_checks == 1
        assert calibration.directional_metrics_compared == 1
        assert calibration.favorable_count == 1
        assert calibration.calibration_label == "insufficient_data"


def test_calibration_higher_is_better_favorable_delta() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)
        decision = _acted_on_decision(db, user)
        _persist_outcome(
            db,
            user,
            decision,
            [_numeric_metric("safe_to_spend_after_purchase_cents", 100_000, 150_000)],
        )

        calibration = decision_calibration_service.get_decision_calibration(
            db, user.id
        )

        assert calibration.favorable_count == 1
        assert calibration.unfavorable_count == 0
        assert calibration.unchanged_count == 0
        group = calibration.metric_groups[0]
        assert group.path == "safe_to_spend_after_purchase_cents"
        assert group.direction == "higher_is_better"
        assert group.unit == "currency"
        assert group.favorable_count == 1
        assert group.mean_signed_delta == 50_000
        assert group.latest_delta == 50_000


def test_calibration_higher_is_better_unfavorable_delta() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)
        decision = _acted_on_decision(db, user)
        _persist_outcome(
            db,
            user,
            decision,
            [_numeric_metric("confidence_score", 80, 60)],
        )

        calibration = decision_calibration_service.get_decision_calibration(
            db, user.id
        )

        assert calibration.favorable_count == 0
        assert calibration.unfavorable_count == 1
        group = calibration.metric_groups[0]
        assert group.direction == "higher_is_better"
        assert group.unit == "score"
        assert group.unfavorable_count == 1


def test_calibration_lower_is_better_logic() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)

        favorable_decision = _acted_on_decision(db, user, title="Decrease")
        _persist_outcome(
            db,
            user,
            favorable_decision,
            [_numeric_metric("shortfall_cents", 50_000, 20_000)],
        )

        unfavorable_decision = _acted_on_decision(db, user, title="Increase")
        _persist_outcome(
            db,
            user,
            unfavorable_decision,
            [_numeric_metric("shortfall_cents", 20_000, 60_000)],
        )

        calibration = decision_calibration_service.get_decision_calibration(
            db, user.id
        )

        assert calibration.favorable_count == 1
        assert calibration.unfavorable_count == 1
        group = calibration.metric_groups[0]
        assert group.path == "shortfall_cents"
        assert group.direction == "lower_is_better"
        assert group.favorable_count == 1
        assert group.unfavorable_count == 1


def test_calibration_unknown_metric_does_not_affect_label_or_directional_counts() -> (
    None
):
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)
        decision = _acted_on_decision(db, user)
        _persist_outcome(
            db,
            user,
            decision,
            [_numeric_metric("purchase_amount_cents", 100_000, 200_000)],
        )

        calibration = decision_calibration_service.get_decision_calibration(
            db, user.id
        )

        assert calibration.numeric_metrics_compared == 1
        assert calibration.changed_numeric_metrics == 1
        assert calibration.directional_metrics_compared == 0
        assert calibration.favorable_count == 0
        assert calibration.unfavorable_count == 0
        assert calibration.calibration_label == "insufficient_data"
        assert calibration.metric_groups[0].direction == "unknown"


def test_calibration_unchanged_observation() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)
        decision = _acted_on_decision(db, user)
        _persist_outcome(
            db,
            user,
            decision,
            [_numeric_metric("buffer_difference_cents", 500, 500)],
        )

        calibration = decision_calibration_service.get_decision_calibration(
            db, user.id
        )

        assert calibration.unchanged_count == 1
        assert calibration.favorable_count == 0
        assert calibration.unfavorable_count == 0
        assert calibration.changed_numeric_metrics == 0


def test_calibration_mostly_conservative_at_65_percent_threshold() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)

        decision_a = _acted_on_decision(db, user, title="A")
        _persist_outcome(
            db,
            user,
            decision_a,
            [
                _numeric_metric("safe_to_spend_after_purchase_cents", 100_000, 150_000),
                _numeric_metric("confidence_score", 60, 70),
            ],
        )

        decision_b = _acted_on_decision(
            db, user, decision_type="stress_test", title="B"
        )
        _persist_outcome(
            db,
            user,
            decision_b,
            [
                _numeric_metric("resilience_score", 40, 55),
                _numeric_metric("shortfall_cents", 10_000, 30_000),
            ],
        )

        calibration = decision_calibration_service.get_decision_calibration(
            db, user.id
        )

        assert calibration.tracked_decisions == 2
        assert calibration.directional_metrics_compared == 4
        assert calibration.favorable_count == 3
        assert calibration.unfavorable_count == 1
        assert calibration.favorable_rate == 0.75
        assert calibration.calibration_label == "mostly_conservative"


def test_calibration_mostly_optimistic_at_65_percent_threshold() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)

        decision_a = _acted_on_decision(db, user, title="A")
        _persist_outcome(
            db,
            user,
            decision_a,
            [
                _numeric_metric("safe_to_spend_after_purchase_cents", 150_000, 100_000),
                _numeric_metric("confidence_score", 70, 60),
            ],
        )

        decision_b = _acted_on_decision(
            db, user, decision_type="stress_test", title="B"
        )
        _persist_outcome(
            db,
            user,
            decision_b,
            [
                _numeric_metric("resilience_score", 55, 40),
                _numeric_metric("shortfall_cents", 10_000, 5_000),
            ],
        )

        calibration = decision_calibration_service.get_decision_calibration(
            db, user.id
        )

        assert calibration.tracked_decisions == 2
        assert calibration.directional_metrics_compared == 4
        assert calibration.unfavorable_count == 3
        assert calibration.favorable_count == 1
        assert calibration.unfavorable_rate == 0.75
        assert calibration.calibration_label == "mostly_optimistic"


def test_calibration_balanced_case() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)

        decision_a = _acted_on_decision(db, user, title="A")
        _persist_outcome(
            db,
            user,
            decision_a,
            [
                _numeric_metric("safe_to_spend_after_purchase_cents", 100_000, 150_000),
                _numeric_metric("confidence_score", 70, 60),
            ],
        )

        decision_b = _acted_on_decision(
            db, user, decision_type="stress_test", title="B"
        )
        _persist_outcome(
            db,
            user,
            decision_b,
            [
                _numeric_metric("resilience_score", 40, 55),
                _numeric_metric("shortfall_cents", 10_000, 30_000),
            ],
        )

        calibration = decision_calibration_service.get_decision_calibration(
            db, user.id
        )

        assert calibration.tracked_decisions == 2
        assert calibration.directional_metrics_compared == 4
        assert calibration.favorable_count == 2
        assert calibration.unfavorable_count == 2
        assert calibration.favorable_rate == 0.5
        assert calibration.calibration_label == "balanced"


def test_calibration_per_decision_type_aggregation() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)

        purchase_decision = _acted_on_decision(db, user, title="Purchase")
        _persist_outcome(
            db,
            user,
            purchase_decision,
            [_numeric_metric("safe_to_spend_after_purchase_cents", 100_000, 150_000)],
        )

        stress_decision = _acted_on_decision(
            db, user, decision_type="stress_test", title="Stress"
        )
        _persist_outcome(
            db,
            user,
            stress_decision,
            [_numeric_metric("shortfall_cents", 10_000, 30_000)],
        )

        calibration = decision_calibration_service.get_decision_calibration(
            db, user.id
        )

        by_type = {
            breakdown.decision_type: breakdown
            for breakdown in calibration.decision_types
        }
        assert set(by_type.keys()) == {"major_purchase", "stress_test"}

        purchase_breakdown = by_type["major_purchase"]
        assert purchase_breakdown.tracked_decisions == 1
        assert purchase_breakdown.outcome_checks == 1
        assert purchase_breakdown.directional_observations == 1
        assert purchase_breakdown.favorable_count == 1
        assert purchase_breakdown.unfavorable_count == 0
        assert purchase_breakdown.favorable_rate == 1.0

        stress_breakdown = by_type["stress_test"]
        assert stress_breakdown.tracked_decisions == 1
        assert stress_breakdown.outcome_checks == 1
        assert stress_breakdown.directional_observations == 1
        assert stress_breakdown.favorable_count == 0
        assert stress_breakdown.unfavorable_count == 1
        assert stress_breakdown.favorable_rate == 0.0
        # Only one tracked decision of each type -- still insufficient
        # even though the single observation happens to be favorable.
        assert purchase_breakdown.calibration_label == "insufficient_data"
        assert stress_breakdown.calibration_label == "insufficient_data"


def test_calibration_metric_grouping_and_deterministic_ordering() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)
        decision = _acted_on_decision(db, user)

        # "frequent_metric" observed across three separate outcome
        # checks; "rare_metric" observed once.
        _persist_outcome(
            db, user, decision, [_numeric_metric("frequent_metric", 10, 20)]
        )
        _persist_outcome(
            db, user, decision, [_numeric_metric("frequent_metric", 20, 25)]
        )
        _persist_outcome(
            db,
            user,
            decision,
            [
                _numeric_metric("frequent_metric", 25, 15),
                _numeric_metric("rare_metric", 5, 5),
            ],
        )

        calibration = decision_calibration_service.get_decision_calibration(
            db, user.id
        )

        assert [group.path for group in calibration.metric_groups] == [
            "frequent_metric",
            "rare_metric",
        ]
        frequent = calibration.metric_groups[0]
        assert frequent.observations == 3
        assert frequent.mean_signed_delta == (10 + 5 + -10) / 3
        assert frequent.mean_absolute_delta == (10 + 5 + 10) / 3
        # Rows are considered newest-evaluated first, and the last
        # `_persist_outcome` call (delta -10) is the most recent.
        assert frequent.latest_delta == -10


def test_calibration_metric_groups_are_capped_and_path_ordered() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)
        decision = _acted_on_decision(db, user)

        metrics = [
            _numeric_metric(f"metric_{index:02d}", 0, 1)
            for index in range(25)
        ]
        _persist_outcome(db, user, decision, metrics)

        calibration = decision_calibration_service.get_decision_calibration(
            db, user.id
        )

        assert len(calibration.metric_groups) == 20
        paths = [group.path for group in calibration.metric_groups]
        assert paths == sorted(paths)
        assert paths[0] == "metric_00"
        assert paths[-1] == "metric_19"


def test_calibration_cross_user_isolation() -> None:
    with TestingSessionLocal() as db:
        owner = create_user(db)
        other = create_user(db)
        create_account(db, owner)
        create_account(db, other)

        owner_decision = _acted_on_decision(db, owner, title="Owner")
        _persist_outcome(
            db,
            owner,
            owner_decision,
            [_numeric_metric("safe_to_spend_after_purchase_cents", 100_000, 150_000)],
        )

        other_decision = _acted_on_decision(db, other, title="Other")
        _persist_outcome(
            db,
            other,
            other_decision,
            [_numeric_metric("safe_to_spend_after_purchase_cents", 100_000, 400_000)],
        )

        owner_calibration = decision_calibration_service.get_decision_calibration(
            db, owner.id
        )

        assert owner_calibration.tracked_decisions == 1
        assert owner_calibration.outcome_checks == 1
        assert owner_calibration.metric_groups[0].mean_signed_delta == 50_000


def test_calibration_duplicate_outcome_checks_counted_correctly() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)
        decision = _acted_on_decision(db, user)

        _persist_outcome(
            db,
            user,
            decision,
            [_numeric_metric("safe_to_spend_after_purchase_cents", 100_000, 120_000)],
        )
        _persist_outcome(
            db,
            user,
            decision,
            [_numeric_metric("safe_to_spend_after_purchase_cents", 120_000, 140_000)],
        )

        calibration = decision_calibration_service.get_decision_calibration(
            db, user.id
        )

        assert calibration.tracked_decisions == 1
        assert calibration.outcome_checks == 2
        assert calibration.metric_groups[0].observations == 2


def test_calibration_unique_tracked_decision_count() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)

        tracked_a = _acted_on_decision(db, user, title="Tracked A")
        _persist_outcome(
            db,
            user,
            tracked_a,
            [_numeric_metric("safe_to_spend_after_purchase_cents", 100_000, 120_000)],
        )
        _persist_outcome(
            db,
            user,
            tracked_a,
            [_numeric_metric("safe_to_spend_after_purchase_cents", 120_000, 140_000)],
        )

        tracked_b = _acted_on_decision(db, user, title="Tracked B")
        _persist_outcome(
            db,
            user,
            tracked_b,
            [_numeric_metric("safe_to_spend_after_purchase_cents", 100_000, 90_000)],
        )

        # Acted on but never checked -- must not count as tracked.
        _acted_on_decision(db, user, title="Untracked")

        calibration = decision_calibration_service.get_decision_calibration(
            db, user.id
        )

        assert calibration.tracked_decisions == 2
        assert calibration.outcome_checks == 3


def test_decision_calibration_endpoint_requires_authentication(
    client: TestClient,
) -> None:
    response = client.get("/users/9999/decisions/calibration")
    assert response.status_code == 401


def test_decision_calibration_endpoint_blocks_other_user(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "calibration-owner")

    response = client.get(
        f"/users/{user_id + 1}/decisions/calibration", headers=headers
    )

    assert response.status_code == 403


def test_decision_calibration_endpoint_returns_empty_state(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "calibration-empty")

    response = client.get(
        f"/users/{user_id}/decisions/calibration", headers=headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tracked_decisions"] == 0
    assert body["outcome_checks"] == 0
    assert body["calibration_label"] == "insufficient_data"
    assert body["favorable_rate"] is None
    assert body["metric_groups"] == []
    assert body["decision_types"] == []


def test_decision_calibration_endpoint_reflects_persisted_outcomes(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "calibration-http")

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
    outcome_response = client.post(
        f"/users/{user_id}/decisions/{decision_id}/outcomes",
        headers=headers,
    )
    assert outcome_response.status_code == 201

    response = client.get(
        f"/users/{user_id}/decisions/calibration", headers=headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tracked_decisions"] == 1
    assert body["outcome_checks"] == 1


# --- Decision review queue -----------------------------------------------

REVIEW_NOW = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)


def _saved_decision_aged(
    db: Session, user: User, age_days: int, *, title: str = "Laptop"
) -> SavedDecision:
    decision = decision_history_service.save_decision(
        db,
        user.id,
        SaveDecisionRequest(
            decision_type="major_purchase",
            title=title,
            input=_major_purchase_input(),
        ),
        as_of=TEST_DATE,
    )
    decision.created_at = REVIEW_NOW - timedelta(days=age_days)
    db.commit()
    db.refresh(decision)
    return decision


def _acted_on_decision_aged(
    db: Session, user: User, acted_on_age_days: int, *, title: str = "Laptop"
) -> SavedDecision:
    decision = decision_history_service.save_decision(
        db,
        user.id,
        SaveDecisionRequest(
            decision_type="major_purchase",
            title=title,
            input=_major_purchase_input(),
        ),
        as_of=TEST_DATE,
    )
    updated = decision_history_service.update_decision_status(
        db, user.id, decision.id, "acted_on"
    )
    assert updated is not None
    updated.acted_on_at = REVIEW_NOW - timedelta(days=acted_on_age_days)
    db.commit()
    db.refresh(updated)
    return updated


def test_review_queue_excludes_saved_decision_younger_than_7_days() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        _saved_decision_aged(db, user, 6)

        queue = decision_review_service.build_review_queue(
            db, user.id, now=REVIEW_NOW
        )

        assert queue == []


def test_review_queue_includes_saved_decision_at_least_7_days_old() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        decision = _saved_decision_aged(db, user, 8)

        queue = decision_review_service.build_review_queue(
            db, user.id, now=REVIEW_NOW
        )

        assert len(queue) == 1
        item = queue[0]
        assert item.decision_id == decision.id
        assert item.review_reason == "saved_unresolved"
        assert item.recommended_action == "mark_acted_or_dismiss"
        assert item.age_days == 8
        assert item.review_reason_text == (
            "Saved 8 days ago. Tell Discero whether you acted on this "
            "decision."
        )


def test_review_queue_excludes_dismissed_decision() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        decision = _saved_decision_aged(db, user, 30)
        decision_history_service.update_decision_status(
            db, user.id, decision.id, "dismissed"
        )

        queue = decision_review_service.build_review_queue(
            db, user.id, now=REVIEW_NOW
        )

        assert queue == []


def test_review_queue_excludes_acted_on_younger_than_7_days_with_no_outcomes() -> (
    None
):
    with TestingSessionLocal() as db:
        user = create_user(db)
        _acted_on_decision_aged(db, user, 6)

        queue = decision_review_service.build_review_queue(
            db, user.id, now=REVIEW_NOW
        )

        assert queue == []


def test_review_queue_includes_acted_on_at_least_7_days_with_no_outcomes() -> (
    None
):
    with TestingSessionLocal() as db:
        user = create_user(db)
        decision = _acted_on_decision_aged(db, user, 9)

        queue = decision_review_service.build_review_queue(
            db, user.id, now=REVIEW_NOW
        )

        assert len(queue) == 1
        item = queue[0]
        assert item.decision_id == decision.id
        assert item.review_reason == "acted_on_never_checked"
        assert item.recommended_action == "check_outcome"
        assert item.age_days == 9


def test_review_queue_excludes_acted_on_with_recent_outcome() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        decision = _acted_on_decision_aged(db, user, 40)
        _persist_outcome(
            db,
            user,
            decision,
            [],
            evaluated_at=REVIEW_NOW - timedelta(days=5),
        )

        queue = decision_review_service.build_review_queue(
            db, user.id, now=REVIEW_NOW
        )

        assert queue == []


def test_review_queue_includes_acted_on_with_outcome_at_least_30_days_old() -> (
    None
):
    with TestingSessionLocal() as db:
        user = create_user(db)
        decision = _acted_on_decision_aged(db, user, 60)
        _persist_outcome(
            db,
            user,
            decision,
            [],
            evaluated_at=REVIEW_NOW - timedelta(days=34),
        )

        queue = decision_review_service.build_review_queue(
            db, user.id, now=REVIEW_NOW
        )

        assert len(queue) == 1
        item = queue[0]
        assert item.decision_id == decision.id
        assert item.review_reason == "acted_on_recheck_due"
        assert item.recommended_action == "recheck_outcome"
        assert item.age_days == 34


def test_review_queue_uses_latest_outcome_timestamp_with_multiple_outcomes() -> (
    None
):
    with TestingSessionLocal() as db:
        user = create_user(db)
        decision = _acted_on_decision_aged(db, user, 90)
        _persist_outcome(
            db,
            user,
            decision,
            [],
            evaluated_at=REVIEW_NOW - timedelta(days=80),
        )
        _persist_outcome(
            db,
            user,
            decision,
            [],
            evaluated_at=REVIEW_NOW - timedelta(days=31),
        )

        queue = decision_review_service.build_review_queue(
            db, user.id, now=REVIEW_NOW
        )

        assert len(queue) == 1
        assert queue[0].age_days == 31


def test_review_queue_sorting_priority() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        saved = _saved_decision_aged(db, user, 10, title="Saved unresolved")
        never_checked = _acted_on_decision_aged(
            db, user, 10, title="Never checked"
        )
        recheck_due = _acted_on_decision_aged(
            db, user, 90, title="Recheck due"
        )
        _persist_outcome(
            db,
            user,
            recheck_due,
            [],
            evaluated_at=REVIEW_NOW - timedelta(days=31),
        )

        queue = decision_review_service.build_review_queue(
            db, user.id, now=REVIEW_NOW
        )

        assert [item.decision_id for item in queue] == [
            never_checked.id,
            recheck_due.id,
            saved.id,
        ]


def test_review_queue_same_priority_sorting_is_deterministic() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        older = _saved_decision_aged(db, user, 10, title="Older")
        newer = _saved_decision_aged(db, user, 8, title="Newer")

        queue = decision_review_service.build_review_queue(
            db, user.id, now=REVIEW_NOW
        )

        # Oldest relevant event (largest age) first within the same
        # reason.
        assert [item.decision_id for item in queue] == [older.id, newer.id]


def test_review_queue_tie_breaks_by_decision_id() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        same_created_at = REVIEW_NOW - timedelta(days=10)
        first = _saved_decision_aged(db, user, 10, title="First")
        first.created_at = same_created_at
        second = _saved_decision_aged(db, user, 10, title="Second")
        second.created_at = same_created_at
        db.commit()

        queue = decision_review_service.build_review_queue(
            db, user.id, now=REVIEW_NOW
        )

        assert [item.decision_id for item in queue] == [first.id, second.id]


def test_review_queue_user_isolation() -> None:
    with TestingSessionLocal() as db:
        owner = create_user(db)
        other = create_user(db)
        _saved_decision_aged(db, owner, 10)
        _saved_decision_aged(db, other, 10)

        owner_queue = decision_review_service.build_review_queue(
            db, owner.id, now=REVIEW_NOW
        )
        other_queue = decision_review_service.build_review_queue(
            db, other.id, now=REVIEW_NOW
        )

        assert len(owner_queue) == 1
        assert len(other_queue) == 1
        assert owner_queue[0].decision_id != other_queue[0].decision_id


def test_review_queue_boundary_exactly_7_days() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        decision = _saved_decision_aged(db, user, 7)

        queue = decision_review_service.build_review_queue(
            db, user.id, now=REVIEW_NOW
        )

        assert len(queue) == 1
        assert queue[0].decision_id == decision.id
        assert queue[0].age_days == 7


def test_review_queue_boundary_exactly_30_days() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        decision = _acted_on_decision_aged(db, user, 60)
        _persist_outcome(
            db,
            user,
            decision,
            [],
            evaluated_at=REVIEW_NOW - timedelta(days=30),
        )

        queue = decision_review_service.build_review_queue(
            db, user.id, now=REVIEW_NOW
        )

        assert len(queue) == 1
        assert queue[0].decision_id == decision.id
        assert queue[0].age_days == 30


def test_review_queue_no_n_plus_one_query_growth() -> None:
    def _count_queries(decision_count: int) -> int:
        with TestingSessionLocal() as db:
            user = create_user(db)
            for i in range(decision_count):
                _saved_decision_aged(db, user, 10, title=f"D{i}")

            statements: list[str] = []

            def _capture(conn, cursor, statement, *args) -> None:
                statements.append(statement)

            event.listen(test_engine, "before_cursor_execute", _capture)
            try:
                decision_review_service.build_review_queue(
                    db, user.id, now=REVIEW_NOW
                )
            finally:
                event.remove(test_engine, "before_cursor_execute", _capture)

            return len(statements)

    small = _count_queries(2)
    large = _count_queries(10)

    # The query count must stay flat as decision count grows -- one
    # query for the decisions and one grouped aggregate query for
    # outcome metadata, never one query per decision.
    assert small == large


def test_review_queue_endpoint_returns_items_and_total_count(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "review-queue-http")

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

    with TestingSessionLocal() as db:
        decision = db.get(SavedDecision, decision_id)
        assert decision is not None
        decision.created_at = datetime.now(timezone.utc) - timedelta(
            days=10
        )
        db.commit()

    response = client.get(
        f"/users/{user_id}/decisions/review-queue", headers=headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_count"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["decision_id"] == decision_id
    assert body["items"][0]["review_reason"] == "saved_unresolved"


def test_review_queue_endpoint_route_precedes_decision_id_route(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "review-queue-route")

    response = client.get(
        f"/users/{user_id}/decisions/review-queue", headers=headers
    )

    # If FastAPI matched "/{decision_id}" first, "review-queue" would be
    # parsed as a decision ID and 404 with "saved decision not found".
    assert response.status_code == 200


def test_review_queue_endpoint_blocks_other_user(client: TestClient) -> None:
    owner_id, _owner_headers = register_and_login(
        client, "review-queue-owner"
    )
    _other_id, other_headers = register_and_login(
        client, "review-queue-other"
    )

    response = client.get(
        f"/users/{owner_id}/decisions/review-queue", headers=other_headers
    )

    assert response.status_code == 403


def _calibration_fixture(
    *,
    calibration_label: str = "insufficient_data",
    tracked_decisions: int = 0,
    outcome_checks: int = 0,
    favorable_rate: float | None = None,
    unfavorable_rate: float | None = None,
    metric_groups: list[DecisionCalibrationMetricGroupOut] | None = None,
) -> DecisionCalibrationOut:
    return DecisionCalibrationOut(
        tracked_decisions=tracked_decisions,
        outcome_checks=outcome_checks,
        numeric_metrics_compared=0,
        changed_numeric_metrics=0,
        directional_metrics_compared=0,
        favorable_count=0,
        unfavorable_count=0,
        unchanged_count=0,
        favorable_rate=favorable_rate,
        unfavorable_rate=unfavorable_rate,
        calibration_label=calibration_label,
        metric_groups=metric_groups or [],
        decision_types=[],
    )


def _metric_group(
    path: str, observations: int
) -> DecisionCalibrationMetricGroupOut:
    return DecisionCalibrationMetricGroupOut(
        path=path,
        unit="currency",
        direction="higher_is_better",
        observations=observations,
        mean_signed_delta=100.0,
        mean_absolute_delta=100.0,
        latest_delta=100.0,
        favorable_count=observations,
        unfavorable_count=0,
        unchanged_count=0,
    )


def test_adaptive_intelligence_insufficient_data() -> None:
    calibration = _calibration_fixture(calibration_label="insufficient_data")

    result = (
        decision_adaptive_intelligence_service.build_adaptive_intelligence(
            calibration
        )
    )

    assert result.status == "insufficient_data"
    assert "more tracked outcomes" in result.narrative.lower()
    assert result.metric_patterns == []


def test_adaptive_intelligence_mostly_conservative_narrative() -> None:
    calibration = _calibration_fixture(
        calibration_label="mostly_conservative",
        tracked_decisions=3,
        outcome_checks=4,
        favorable_rate=0.8,
    )

    result = (
        decision_adaptive_intelligence_service.build_adaptive_intelligence(
            calibration
        )
    )

    assert result.status == "available"
    assert result.narrative == (
        "Your tracked outcomes have generally been more favorable than "
        "the original estimates."
    )


def test_adaptive_intelligence_mostly_optimistic_narrative() -> None:
    calibration = _calibration_fixture(
        calibration_label="mostly_optimistic",
        tracked_decisions=3,
        outcome_checks=4,
    )

    result = (
        decision_adaptive_intelligence_service.build_adaptive_intelligence(
            calibration
        )
    )

    assert result.status == "available"
    assert result.narrative == (
        "Your tracked outcomes have generally been less favorable than "
        "the original estimates."
    )


def test_adaptive_intelligence_balanced_narrative() -> None:
    calibration = _calibration_fixture(
        calibration_label="balanced", tracked_decisions=3, outcome_checks=4
    )

    result = (
        decision_adaptive_intelligence_service.build_adaptive_intelligence(
            calibration
        )
    )

    assert result.status == "available"
    assert result.narrative == (
        "Your tracked outcomes have been mixed relative to the original "
        "estimates."
    )


def test_adaptive_intelligence_metric_evidence_threshold() -> None:
    calibration = _calibration_fixture(
        calibration_label="balanced",
        tracked_decisions=3,
        outcome_checks=4,
        metric_groups=[
            _metric_group("safe_to_spend_after_purchase_cents", 2),
            _metric_group("confidence_score", 1),
        ],
    )

    result = (
        decision_adaptive_intelligence_service.build_adaptive_intelligence(
            calibration
        )
    )

    paths = [pattern.path for pattern in result.metric_patterns]
    assert paths == ["safe_to_spend_after_purchase_cents"]


def test_adaptive_intelligence_metric_patterns_capped_at_five() -> None:
    calibration = _calibration_fixture(
        calibration_label="balanced",
        tracked_decisions=3,
        outcome_checks=4,
        metric_groups=[_metric_group(f"metric_{i}", 2) for i in range(8)],
    )

    result = (
        decision_adaptive_intelligence_service.build_adaptive_intelligence(
            calibration
        )
    )

    assert len(result.metric_patterns) == 5


def test_adaptive_intelligence_endpoint_reflects_insufficient_data(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "adaptive-http")

    response = client.get(
        f"/users/{user_id}/decisions/adaptive-intelligence", headers=headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "insufficient_data"
    assert body["tracked_decisions"] == 0


def test_adaptive_intelligence_endpoint_available_state(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "adaptive-available")

    http_stress_test_input = {
        "scenario_type": "emergency_expense",
        "scenario_name": "Car repair",
        "stress_amount_cents": 100_000,
        "event_date": date.today().isoformat(),
    }

    for decision_type, payload_input in (
        ("major_purchase", _http_major_purchase_input()),
        ("stress_test", http_stress_test_input),
    ):
        save_response = client.post(
            f"/users/{user_id}/decisions",
            headers=headers,
            json={
                "decision_type": decision_type,
                "title": decision_type,
                "input": payload_input,
            },
        )
        decision_id = save_response.json()["id"]
        client.patch(
            f"/users/{user_id}/decisions/{decision_id}/status",
            headers=headers,
            json={"status": "acted_on"},
        )
        outcome_response = client.post(
            f"/users/{user_id}/decisions/{decision_id}/outcomes",
            headers=headers,
        )
        assert outcome_response.status_code == 201

    response = client.get(
        f"/users/{user_id}/decisions/adaptive-intelligence", headers=headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "available"
    assert body["tracked_decisions"] == 2


def test_adaptive_intelligence_does_not_alter_saved_decision_result(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "adaptive-no-mutate")

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
    before = client.get(
        f"/users/{user_id}/decisions/{decision_id}", headers=headers
    ).json()

    client.get(
        f"/users/{user_id}/decisions/adaptive-intelligence", headers=headers
    )

    after = client.get(
        f"/users/{user_id}/decisions/{decision_id}", headers=headers
    ).json()

    assert before["result_snapshot"] == after["result_snapshot"]


def test_adaptive_intelligence_endpoint_route_precedes_decision_id_route(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client, "adaptive-route"
    )

    response = client.get(
        f"/users/{user_id}/decisions/adaptive-intelligence", headers=headers
    )

    assert response.status_code == 200


def test_adaptive_intelligence_endpoint_blocks_other_user(
    client: TestClient,
) -> None:
    owner_id, _owner_headers = register_and_login(
        client, "adaptive-owner"
    )
    _other_id, other_headers = register_and_login(
        client, "adaptive-other"
    )

    response = client.get(
        f"/users/{owner_id}/decisions/adaptive-intelligence",
        headers=other_headers,
    )

    assert response.status_code == 403


def test_change_explanation_numeric_currency_delta() -> None:
    explanation = decision_change_explanation_service.build_change_explanation(
        {"safe_to_spend_after_purchase_cents": 100_000},
        {"safe_to_spend_after_purchase_cents": 150_000},
    )

    assert explanation.total_changed_metric_count == 1
    metric = explanation.changed_metrics[0]
    assert metric.path == "safe_to_spend_after_purchase_cents"
    assert metric.change_type == "numeric"
    assert metric.delta == 50_000
    assert metric.unit == "currency"
    assert metric.direction == "higher_is_better"


def test_change_explanation_score_delta() -> None:
    explanation = decision_change_explanation_service.build_change_explanation(
        {"confidence_score": 70}, {"confidence_score": 62}
    )

    metric = explanation.changed_metrics[0]
    assert metric.unit == "score"
    assert metric.delta == -8
    assert metric.direction == "higher_is_better"


def test_change_explanation_text_status_change_has_no_direction_or_unit() -> (
    None
):
    explanation = decision_change_explanation_service.build_change_explanation(
        {"affordability_status": "affordable"},
        {"affordability_status": "caution"},
    )

    metric = explanation.changed_metrics[0]
    assert metric.change_type == "text"
    assert metric.delta is None
    assert metric.unit is None
    assert metric.direction is None


def test_change_explanation_unknown_directionality_is_not_labeled_good_or_bad() -> (
    None
):
    explanation = decision_change_explanation_service.build_change_explanation(
        {"purchase_amount_cents": 100_000},
        {"purchase_amount_cents": 120_000},
    )

    metric = explanation.changed_metrics[0]
    assert metric.direction == "unknown"


def test_change_explanation_unchanged_fields_are_excluded_but_counted() -> (
    None
):
    explanation = decision_change_explanation_service.build_change_explanation(
        {"confidence_score": 70, "purchase_amount_cents": 150_000},
        {"confidence_score": 62, "purchase_amount_cents": 150_000},
    )

    assert explanation.total_changed_metric_count == 1
    assert explanation.unchanged_metric_count == 1
    assert [m.path for m in explanation.changed_metrics] == [
        "confidence_score"
    ]


def test_change_explanation_never_performs_arithmetic_on_non_numeric() -> (
    None
):
    explanation = decision_change_explanation_service.build_change_explanation(
        {"acted": False, "as_of": "2026-08-01"},
        {"acted": True, "as_of": "2026-08-20"},
    )

    by_path = {m.path: m for m in explanation.changed_metrics}
    assert by_path["acted"].change_type == "boolean"
    assert by_path["acted"].delta is None
    assert by_path["as_of"].change_type == "date"
    assert by_path["as_of"].delta is None


def test_change_explanation_malformed_legacy_snapshot_is_safe() -> None:
    explanation = decision_change_explanation_service.build_change_explanation(
        {"safe_to_spend_cents": {"unexpected": "shape"}},
        {"safe_to_spend_cents": 100_000},
    )

    assert explanation.changed_metrics == []
    assert explanation.total_changed_metric_count == 0


def test_change_explanation_known_metric_priority_ordering() -> None:
    explanation = decision_change_explanation_service.build_change_explanation(
        {
            "unrelated_field": 1,
            "confidence_score": 70,
            "safe_to_spend_after_purchase_cents": 100_000,
        },
        {
            "unrelated_field": 2,
            "confidence_score": 62,
            "safe_to_spend_after_purchase_cents": 150_000,
        },
    )

    assert [m.path for m in explanation.changed_metrics] == [
        "safe_to_spend_after_purchase_cents",
        "confidence_score",
        "unrelated_field",
    ]


def test_rerun_endpoint_includes_change_explanation_for_real_change(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "rerun-explain")

    with TestingSessionLocal() as db:
        user = db.get(User, user_id)
        create_account(db, user, available_balance_cents=1_000_000)

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

    with TestingSessionLocal() as db:
        user = db.get(User, user_id)
        create_account(db, user, available_balance_cents=5_000_000)

    rerun_response = client.post(
        f"/users/{user_id}/decisions/{decision_id}/rerun", headers=headers
    )

    assert rerun_response.status_code == 200
    body = rerun_response.json()
    explanation = body["change_explanation"]
    assert explanation is not None
    assert explanation["total_changed_metric_count"] > 0

    by_path = {m["path"]: m for m in explanation["changed_metrics"]}
    balance_metric = by_path["safe_to_spend_before_purchase_cents"]
    assert balance_metric["unit"] == "currency"
    assert balance_metric["direction"] == "higher_is_better"
    assert balance_metric["delta"] > 0

    # Run Again is ephemeral -- it must never persist a DecisionOutcome.
    outcomes_response = client.get(
        f"/users/{user_id}/decisions/{decision_id}/outcomes", headers=headers
    )
    assert outcomes_response.json() == []


def test_rerun_endpoint_stays_successful_when_explanation_fails(
    client: TestClient, monkeypatch
) -> None:
    user_id, headers = register_and_login(client, "rerun-explain-fail")

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

    def _raise(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        decisions_router.decision_change_explanation_service,
        "build_change_explanation",
        _raise,
    )

    rerun_response = client.post(
        f"/users/{user_id}/decisions/{decision_id}/rerun", headers=headers
    )

    assert rerun_response.status_code == 200
    body = rerun_response.json()
    assert body["change_explanation"] is None
    assert body["result_snapshot"]["purchase_amount_cents"] == 150_000


def test_rerun_endpoint_propagates_deterministic_rerun_failure(
    client: TestClient, monkeypatch
) -> None:
    """A failure in the rerun itself (not the optional explanation)
    must never be swallowed into a 200 with change_explanation=None --
    only the additive explanation step may degrade silently.
    """
    user_id, headers = register_and_login(client, "rerun-failure")

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

    def _raise(*_args, **_kwargs):
        raise RuntimeError("deterministic rerun boom")

    monkeypatch.setattr(
        decisions_router.decision_history_service,
        "rerun_decision",
        _raise,
    )

    with pytest.raises(RuntimeError, match="deterministic rerun boom"):
        client.post(
            f"/users/{user_id}/decisions/{decision_id}/rerun",
            headers=headers,
        )


def test_rerun_endpoint_change_explanation_blocked_for_other_user(
    client: TestClient,
) -> None:
    owner_id, owner_headers = register_and_login(client, "rerun-explain-owner")
    _other_id, other_headers = register_and_login(
        client, "rerun-explain-other"
    )

    save_response = client.post(
        f"/users/{owner_id}/decisions",
        headers=owner_headers,
        json={
            "decision_type": "major_purchase",
            "title": "Laptop",
            "input": _http_major_purchase_input(),
        },
    )
    decision_id = save_response.json()["id"]

    response = client.post(
        f"/users/{owner_id}/decisions/{decision_id}/rerun",
        headers=other_headers,
    )

    assert response.status_code == 403


def test_dashboard_intelligence_no_decisions() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)

        result = decision_dashboard_intelligence_service.build_dashboard_intelligence(
            db, user.id
        )

        assert result.review_queue.count == 0
        assert result.review_queue.highest_priority is None
        assert result.calibration.label == "insufficient_data"
        assert result.calibration.tracked_decisions == 0
        assert result.recent_decision is None


def test_dashboard_intelligence_review_queue_count_and_highest_priority() -> (
    None
):
    # build_dashboard_intelligence uses the review queue's own
    # wall-clock default (no injectable `now`), so the fixture ages a
    # decision against real time directly rather than reusing
    # REVIEW_NOW.
    with TestingSessionLocal() as db:
        user = create_user(db)
        saved = decision_history_service.save_decision(
            db,
            user.id,
            SaveDecisionRequest(
                decision_type="major_purchase",
                title="Old saved",
                input=_major_purchase_input(),
            ),
            as_of=TEST_DATE,
        )
        saved.created_at = datetime.now(timezone.utc) - timedelta(days=10)
        db.commit()

        result = (
            decision_dashboard_intelligence_service.build_dashboard_intelligence(
                db, user.id
            )
        )

        assert result.review_queue.count == 1
        assert result.review_queue.highest_priority is not None
        assert result.review_queue.highest_priority.decision_id == saved.id
        assert result.review_queue.highest_priority.review_reason == (
            "saved_unresolved"
        )


def test_dashboard_intelligence_calibration_summary_reflects_outcomes() -> (
    None
):
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)
        decision = _acted_on_decision(db, user)
        _persist_outcome(
            db,
            user,
            decision,
            [_numeric_metric("confidence_score", 60, 70)],
        )

        result = (
            decision_dashboard_intelligence_service.build_dashboard_intelligence(
                db, user.id
            )
        )

        assert result.calibration.tracked_decisions == 1
        assert result.calibration.outcome_checks == 1


def test_dashboard_intelligence_recent_decision_is_newest() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        decision_history_service.save_decision(
            db,
            user.id,
            SaveDecisionRequest(
                decision_type="major_purchase",
                title="Older",
                input=_major_purchase_input(),
            ),
            as_of=TEST_DATE,
        )
        newer = decision_history_service.save_decision(
            db,
            user.id,
            SaveDecisionRequest(
                decision_type="major_purchase",
                title="Newer",
                input=_major_purchase_input(),
            ),
            as_of=TEST_DATE,
        )

        result = (
            decision_dashboard_intelligence_service.build_dashboard_intelligence(
                db, user.id
            )
        )

        assert result.recent_decision is not None
        assert result.recent_decision.decision_id == newer.id
        assert result.recent_decision.title == "Newer"


def test_dashboard_intelligence_does_not_create_outcomes_or_mutate_decisions() -> (
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
        original_snapshot = dict(decision.result_snapshot)

        decision_dashboard_intelligence_service.build_dashboard_intelligence(
            db, user.id
        )

        refetched = decision_history_service.get_decision(
            db, user.id, decision.id
        )
        assert refetched.result_snapshot == original_snapshot
        assert (
            db.execute(select(DecisionOutcome)).scalars().all() == []
        )


def test_dashboard_intelligence_user_isolation() -> None:
    with TestingSessionLocal() as db:
        owner = create_user(db)
        other = create_user(db)
        _saved_decision_aged(db, owner, 10)

        owner_result = decision_dashboard_intelligence_service.build_dashboard_intelligence(
            db, owner.id
        )
        other_result = decision_dashboard_intelligence_service.build_dashboard_intelligence(
            db, other.id
        )

        assert owner_result.review_queue.count == 1
        assert other_result.review_queue.count == 0
        assert other_result.recent_decision is None


def test_dashboard_intelligence_endpoint_returns_expected_shape(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "dashboard-intel-http")

    save_response = client.post(
        f"/users/{user_id}/decisions",
        headers=headers,
        json={
            "decision_type": "major_purchase",
            "title": "Laptop",
            "input": _http_major_purchase_input(),
        },
    )
    assert save_response.status_code == 201

    response = client.get(
        f"/users/{user_id}/decisions/dashboard-intelligence", headers=headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["review_queue"]["count"] == 0
    assert body["calibration"]["label"] == "insufficient_data"
    assert body["recent_decision"]["title"] == "Laptop"


def test_dashboard_intelligence_endpoint_route_precedes_decision_id_route(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "dashboard-intel-route")

    response = client.get(
        f"/users/{user_id}/decisions/dashboard-intelligence", headers=headers
    )

    # If FastAPI matched "/{decision_id}" first, "dashboard-intelligence"
    # would be parsed as a decision ID and 404 with "saved decision not
    # found".
    assert response.status_code == 200


def test_dashboard_intelligence_endpoint_blocks_other_user(
    client: TestClient,
) -> None:
    owner_id, _owner_headers = register_and_login(
        client, "dashboard-intel-owner"
    )
    _other_id, other_headers = register_and_login(
        client, "dashboard-intel-other"
    )

    response = client.get(
        f"/users/{owner_id}/decisions/dashboard-intelligence",
        headers=other_headers,
    )

    assert response.status_code == 403


def test_timeline_saved_only_has_single_decision_saved_event() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
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

        timeline = decision_timeline_service.build_decision_timeline(
            db, user.id, decision.id
        )

        assert timeline is not None
        assert timeline.decision_id == decision.id
        assert timeline.current_status == "saved"
        assert len(timeline.events) == 1
        assert timeline.events[0].event_type == "decision_saved"
        assert timeline.events[0].occurred_at == decision.created_at


def test_timeline_includes_acted_on_event_when_acted_on_at_set() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
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
        decision = decision_history_service.update_decision_status(
            db, user.id, decision.id, "acted_on"
        )
        assert decision is not None and decision.acted_on_at is not None

        timeline = decision_timeline_service.build_decision_timeline(
            db, user.id, decision.id
        )

        assert timeline is not None
        assert [event.event_type for event in timeline.events] == [
            "decision_saved",
            "decision_acted_on",
        ]
        assert timeline.events[1].occurred_at == decision.acted_on_at


def test_timeline_omits_acted_on_event_when_acted_on_at_missing() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        decision = _saved_decision_aged(db, user, 5)

        timeline = decision_timeline_service.build_decision_timeline(
            db, user.id, decision.id
        )

        assert timeline is not None
        assert [event.event_type for event in timeline.events] == [
            "decision_saved"
        ]


def test_timeline_one_event_per_persisted_outcome_in_chronological_order() -> (
    None
):
    with TestingSessionLocal() as db:
        user = create_user(db)
        decision = _acted_on_decision_aged(db, user, 40)
        older = _persist_outcome(
            db,
            user,
            decision,
            [{"path": "x", "before": 1, "current": 2}],
            evaluated_at=REVIEW_NOW - timedelta(days=20),
        )
        newer = _persist_outcome(
            db,
            user,
            decision,
            [],
            evaluated_at=REVIEW_NOW - timedelta(days=5),
        )

        timeline = decision_timeline_service.build_decision_timeline(
            db, user.id, decision.id
        )

        assert timeline is not None
        outcome_events = [
            event
            for event in timeline.events
            if event.event_type == "outcome_checked"
        ]
        assert [event.outcome_id for event in outcome_events] == [
            older.id,
            newer.id,
        ]
        assert outcome_events[0].changed is True
        assert outcome_events[1].changed is False
        assert [event.occurred_at for event in timeline.events] == sorted(
            event.occurred_at for event in timeline.events
        )


def test_timeline_dismissed_decision_has_no_dismissed_event() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        decision = _saved_decision_aged(db, user, 10)
        decision_history_service.update_decision_status(
            db, user.id, decision.id, "dismissed"
        )

        timeline = decision_timeline_service.build_decision_timeline(
            db, user.id, decision.id
        )

        assert timeline is not None
        assert timeline.current_status == "dismissed"
        assert all(
            event.event_type != "dismissed" for event in timeline.events
        )
        assert [event.event_type for event in timeline.events] == [
            "decision_saved"
        ]


def test_timeline_missing_decision_returns_none() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)

        timeline = decision_timeline_service.build_decision_timeline(
            db, user.id, 999_999
        )

        assert timeline is None


def test_timeline_user_isolation() -> None:
    with TestingSessionLocal() as db:
        owner = create_user(db)
        other = create_user(db)
        decision = _saved_decision_aged(db, owner, 5)

        timeline = decision_timeline_service.build_decision_timeline(
            db, other.id, decision.id
        )

        assert timeline is None


def test_timeline_endpoint_returns_events(client: TestClient) -> None:
    user_id, headers = register_and_login(client, "timeline-http")

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

    response = client.get(
        f"/users/{user_id}/decisions/{decision_id}/timeline",
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["decision_id"] == decision_id
    assert body["current_status"] == "saved"
    assert len(body["events"]) == 1
    assert body["events"][0]["event_type"] == "decision_saved"


def test_timeline_endpoint_missing_decision_returns_404(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "timeline-missing")

    response = client.get(
        f"/users/{user_id}/decisions/999999/timeline", headers=headers
    )

    assert response.status_code == 404


def test_timeline_endpoint_blocks_other_user(client: TestClient) -> None:
    owner_id, owner_headers = register_and_login(
        client, "timeline-owner"
    )
    _other_id, other_headers = register_and_login(
        client, "timeline-other"
    )

    save_response = client.post(
        f"/users/{owner_id}/decisions",
        headers=owner_headers,
        json={
            "decision_type": "major_purchase",
            "title": "Laptop",
            "input": _http_major_purchase_input(),
        },
    )
    decision_id = save_response.json()["id"]

    response = client.get(
        f"/users/{owner_id}/decisions/{decision_id}/timeline",
        headers=other_headers,
    )

    assert response.status_code == 403
