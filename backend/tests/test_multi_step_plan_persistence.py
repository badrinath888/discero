"""Persistent Decision Plans: multi_step_plan riding the EXISTING
generic SavedDecision lifecycle (decision_type/input_snapshot/
result_snapshot dispatch in decision_history_service) -- no new table,
no new lifecycle code. These tests exist to prove that generic
machinery (rerun, outcomes, calibration, memory, review queue,
timeline, cross-user authorization) actually works correctly for this
new decision_type, not just for the types it was originally written
against.
"""

from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.models import FinancialAccount, PlaidItem, User
from app.schemas import SaveDecisionRequest
from app.services import (
    decision_calibration_service,
    decision_history_service,
    decision_memory_service,
    decision_outcome_service,
    decision_review_service,
    decision_timeline_service,
)
from tests.conftest import TestingSessionLocal, test_engine
from tests.test_decisions import register_and_login

TEST_DATE = date(2026, 8, 8)


def create_user(db: Session, prefix: str = "plan-persist") -> User:
    user = User(
        email=f"{prefix}-{uuid4().hex}@example.com",
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

    db.add(
        FinancialAccount(
            plaid_item_id=item.id,
            provider_account_id=f"account-{uuid4().hex}",
            name="Checking",
            account_type="depository",
            current_balance_cents=available_balance_cents,
            available_balance_cents=available_balance_cents,
            currency="USD",
        )
    )
    db.commit()


def _plan_input(*, anchor: date = TEST_DATE, **overrides) -> dict:
    payload = {
        "name": "Laptop then rent increase",
        "horizon_days": 90,
        "steps": [
            {
                "step_type": "one_time_expense",
                "label": "Laptop",
                "effective_date": anchor.isoformat(),
                "amount_cents": 150_000,
            },
            {
                "step_type": "monthly_expense_increase",
                "label": "Rent increase",
                "effective_date": (anchor + timedelta(days=30)).isoformat(),
                "amount_cents": 25_000,
            },
        ],
    }
    payload.update(overrides)
    return payload


# --- Save / retrieve / ordered steps preserved ------------------------------


def test_save_multi_step_plan_stores_ordered_steps_and_real_result() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)

        decision = decision_history_service.save_decision(
            db,
            user.id,
            SaveDecisionRequest(
                decision_type="multi_step_plan",
                title="Laptop + rent plan",
                input=_plan_input(),
            ),
            as_of=TEST_DATE,
        )

        assert decision.decision_type == "multi_step_plan"
        assert [
            step["label"] for step in decision.input_snapshot["steps"]
        ] == ["Laptop", "Rent increase"]
        assert len(decision.result_snapshot["checkpoints"]) == 2
        assert (
            decision.result_snapshot["starting_safe_to_spend_cents"]
            == 5_000_000
        )
        assert decision.status == "saved"


def test_multi_step_plan_appears_in_decision_list_and_detail() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)

        saved = decision_history_service.save_decision(
            db,
            user.id,
            SaveDecisionRequest(
                decision_type="multi_step_plan",
                title="Plan A",
                input=_plan_input(),
            ),
            as_of=TEST_DATE,
        )

        listed = decision_history_service.list_decisions(db, user.id)
        assert [d.id for d in listed] == [saved.id]

        fetched = decision_history_service.get_decision_with_outcome_metadata(
            db, user.id, saved.id
        )
        assert fetched is not None
        assert fetched.outcome_count == 0


# --- Lifecycle ---------------------------------------------------------------


def test_multi_step_plan_lifecycle_saved_to_acted_on() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)

        decision = decision_history_service.save_decision(
            db,
            user.id,
            SaveDecisionRequest(
                decision_type="multi_step_plan",
                title="Plan",
                input=_plan_input(),
            ),
            as_of=TEST_DATE,
        )
        assert decision.acted_on_at is None

        updated = decision_history_service.update_decision_status(
            db, user.id, decision.id, "acted_on"
        )
        assert updated is not None
        assert updated.status == "acted_on"
        assert updated.acted_on_at is not None


# --- Rerun with current data / change comparison ----------------------------


def test_rerun_multi_step_plan_reflects_current_data() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=5_000_000)

        decision = decision_history_service.save_decision(
            db,
            user.id,
            SaveDecisionRequest(
                decision_type="multi_step_plan",
                title="Plan",
                input=_plan_input(),
            ),
            as_of=TEST_DATE,
        )
        original_final = decision.result_snapshot[
            "final_safe_to_spend_cents"
        ]

        create_account(db, user, available_balance_cents=9_000_000)

        rerun = decision_history_service.rerun_decision(
            db, user.id, decision.id, as_of=TEST_DATE
        )
        assert rerun is not None
        _, _, result_snapshot = rerun

        assert result_snapshot["final_safe_to_spend_cents"] != original_final
        # The original saved snapshot is never mutated by a rerun.
        db.refresh(decision)
        assert decision.result_snapshot["final_safe_to_spend_cents"] == (
            original_final
        )


def test_rerun_multi_step_plan_endpoint_includes_change_explanation(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "plan-rerun")

    with TestingSessionLocal() as db:
        user = db.get(User, user_id)
        create_account(db, user, available_balance_cents=5_000_000)

    # The endpoint has no as_of override, so it validates step dates
    # against the real date.today() -- anchor to that instead of the
    # fixed TEST_DATE so this stays valid across a calendar rollover
    # between test-process and server-process timezones.
    save_response = client.post(
        f"/users/{user_id}/decisions",
        headers=headers,
        json={
            "decision_type": "multi_step_plan",
            "title": "Plan",
            "input": _plan_input(anchor=date.today()),
        },
    )
    assert save_response.status_code == 201
    decision_id = save_response.json()["id"]

    with TestingSessionLocal() as db:
        user = db.get(User, user_id)
        create_account(db, user, available_balance_cents=9_000_000)

    rerun_response = client.post(
        f"/users/{user_id}/decisions/{decision_id}/rerun",
        headers=headers,
    )
    assert rerun_response.status_code == 200
    body = rerun_response.json()
    assert body["decision_type"] == "multi_step_plan"
    assert body["change_explanation"] is not None
    assert body["change_explanation"]["total_changed_metric_count"] > 0


# --- Outcome / calibration / memory / review queue / timeline --------------


def test_multi_step_plan_outcome_and_calibration_integration() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=5_000_000)

        decision = decision_history_service.save_decision(
            db,
            user.id,
            SaveDecisionRequest(
                decision_type="multi_step_plan",
                title="Plan",
                input=_plan_input(),
            ),
            as_of=TEST_DATE,
        )
        decision_history_service.update_decision_status(
            db, user.id, decision.id, "acted_on"
        )
        create_account(db, user, available_balance_cents=9_000_000)

        outcome = decision_outcome_service.evaluate_decision_outcome(
            db, user.id, decision.id, as_of=TEST_DATE
        )
        assert outcome is not None
        metrics_by_path = {
            m["path"]: m for m in outcome.comparison_snapshot["metrics"]
        }
        assert "final_safe_to_spend_cents" in metrics_by_path

        # Below the 3-directional-observation / 2-tracked-decision
        # minimums -- calibration must stay honestly "insufficient",
        # never fabricated as calibrated from a single outcome.
        calibration = decision_calibration_service.get_decision_calibration(
            db, user.id
        )
        assert calibration.calibration_label == "insufficient_data"


def test_multi_step_plan_appears_in_decision_memory() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)

        decision_history_service.save_decision(
            db,
            user.id,
            SaveDecisionRequest(
                decision_type="multi_step_plan",
                title="Plan",
                input=_plan_input(),
            ),
            as_of=TEST_DATE,
        )

        memory = decision_memory_service.get_decision_memory(db, user.id)
        types_by_name = {t.decision_type: t for t in memory.decision_types}
        assert "multi_step_plan" in types_by_name
        assert types_by_name["multi_step_plan"].saved_count == 1


def test_multi_step_plan_enters_review_queue_when_unresolved() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)

        decision_history_service.save_decision(
            db,
            user.id,
            SaveDecisionRequest(
                decision_type="multi_step_plan",
                title="Plan",
                input=_plan_input(),
            ),
            as_of=TEST_DATE,
        )

        far_future = datetime.now(timezone.utc) + timedelta(days=10)
        queue = decision_review_service.build_review_queue(
            db, user.id, now=far_future
        )
        assert len(queue) == 1
        assert queue[0].review_reason == "saved_unresolved"


def test_multi_step_plan_timeline_shows_persisted_events_only() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)

        decision = decision_history_service.save_decision(
            db,
            user.id,
            SaveDecisionRequest(
                decision_type="multi_step_plan",
                title="Plan",
                input=_plan_input(),
            ),
            as_of=TEST_DATE,
        )
        decision_history_service.update_decision_status(
            db, user.id, decision.id, "acted_on"
        )

        timeline = decision_timeline_service.build_decision_timeline(
            db, user.id, decision.id
        )
        assert timeline is not None
        event_types = [event.event_type for event in timeline.events]
        assert event_types == ["decision_saved", "decision_acted_on"]


# --- Cross-user authorization ------------------------------------------------


def test_multi_step_plan_cross_user_denied(client: TestClient) -> None:
    owner_id, owner_headers = register_and_login(client, "plan-owner")
    _other_id, other_headers = register_and_login(client, "plan-other")

    with TestingSessionLocal() as db:
        user = db.get(User, owner_id)
        create_account(db, user)

    save_response = client.post(
        f"/users/{owner_id}/decisions",
        headers=owner_headers,
        json={
            "decision_type": "multi_step_plan",
            "title": "Plan",
            "input": _plan_input(anchor=date.today()),
        },
    )
    decision_id = save_response.json()["id"]

    assert (
        client.get(
            f"/users/{owner_id}/decisions/{decision_id}",
            headers=other_headers,
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/users/{owner_id}/decisions/{decision_id}/rerun",
            headers=other_headers,
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"/users/{owner_id}/decisions/{decision_id}/status",
            headers=other_headers,
            json={"status": "acted_on"},
        ).status_code
        == 403
    )
    assert (
        client.delete(
            f"/users/{owner_id}/decisions/{decision_id}",
            headers=other_headers,
        ).status_code
        == 403
    )


# --- Bounded queries on listing ----------------------------------------------


def test_list_decisions_with_multi_step_plans_no_n_plus_one() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)

        for i in range(5):
            decision_history_service.save_decision(
                db,
                user.id,
                SaveDecisionRequest(
                    decision_type="multi_step_plan",
                    title=f"Plan {i}",
                    input=_plan_input(),
                ),
                as_of=TEST_DATE,
            )

        counter = {"n": 0}

        def _count(*args, **kwargs) -> None:
            counter["n"] += 1

        event.listen(test_engine, "before_cursor_execute", _count)
        try:
            decision_history_service.list_decisions(db, user.id)
        finally:
            event.remove(test_engine, "before_cursor_execute", _count)

        assert counter["n"] <= 3
