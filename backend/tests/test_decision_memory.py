from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.schemas import SaveDecisionRequest
from app.services import decision_history_service, decision_memory_service
from tests.conftest import TestingSessionLocal, test_engine
from tests.test_decisions import (
    TEST_DATE,
    _http_major_purchase_input,
    _major_purchase_input,
    _stress_test_input,
    create_account,
    create_user,
    register_and_login,
)


def test_decision_memory_empty_history_returns_no_history_status() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)

        memory = decision_memory_service.get_decision_memory(db, user.id)

        assert memory.status == "no_history"
        assert memory.summary.total_saved_decisions == 0
        assert memory.decision_types == []
        assert memory.recent_patterns == []
        assert memory.needs_follow_up_count == 0


def test_decision_memory_one_saved_decision() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)

        decision_history_service.save_decision(
            db,
            user.id,
            SaveDecisionRequest(
                decision_type="major_purchase",
                title="Laptop",
                input=_major_purchase_input(),
            ),
            as_of=TEST_DATE,
        )

        memory = decision_memory_service.get_decision_memory(db, user.id)

        assert memory.status == "available"
        assert memory.summary.total_saved_decisions == 1
        assert memory.summary.unresolved_count == 1
        assert memory.summary.acted_on_count == 0
        assert memory.summary.most_used_decision_types == ["major_purchase"]


def test_decision_memory_acted_on_and_dismissed_counts() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)

        acted = decision_history_service.save_decision(
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
            db, user.id, acted.id, "acted_on"
        )

        dismissed = decision_history_service.save_decision(
            db,
            user.id,
            SaveDecisionRequest(
                decision_type="major_purchase",
                title="Bike",
                input=_major_purchase_input(),
            ),
            as_of=TEST_DATE,
        )
        decision_history_service.update_decision_status(
            db, user.id, dismissed.id, "dismissed"
        )

        memory = decision_memory_service.get_decision_memory(db, user.id)

        assert memory.summary.acted_on_count == 1
        assert memory.summary.dismissed_count == 1
        assert memory.summary.unresolved_count == 0
        assert memory.follow_through.eligible_decisions == 2
        assert memory.follow_through.acted_on_count == 1
        assert memory.follow_through.follow_through_rate == 0.5


def test_decision_memory_unresolved_count() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)

        for i in range(2):
            decision_history_service.save_decision(
                db,
                user.id,
                SaveDecisionRequest(
                    decision_type="major_purchase",
                    title=f"Item {i}",
                    input=_major_purchase_input(),
                ),
                as_of=TEST_DATE,
            )

        memory = decision_memory_service.get_decision_memory(db, user.id)

        assert memory.summary.unresolved_count == 2


def test_decision_memory_outcome_tracked_count_and_directional_reuse() -> None:
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

        from app.services import decision_outcome_service

        outcome = decision_outcome_service.evaluate_decision_outcome(
            db, user.id, decision.id, as_of=TEST_DATE
        )
        assert outcome is not None

        memory = decision_memory_service.get_decision_memory(db, user.id)

        assert memory.follow_through.outcome_tracked_decisions == 1
        assert memory.follow_through.outcome_eligible_decisions == 1
        assert memory.follow_through.outcome_tracking_rate == 1.0
        assert memory.outcomes.total_outcome_checks == 1


def test_decision_memory_multiple_outcomes_on_same_decision() -> None:
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

        from app.services import decision_outcome_service

        decision_outcome_service.evaluate_decision_outcome(
            db, user.id, decision.id, as_of=TEST_DATE
        )
        decision_outcome_service.evaluate_decision_outcome(
            db, user.id, decision.id, as_of=TEST_DATE
        )

        memory = decision_memory_service.get_decision_memory(db, user.id)

        # Both outcome checks count, but they're still ONE tracked
        # decision -- calibration's tracked_decisions is a decision
        # count, not an outcome-row count.
        assert memory.outcomes.total_outcome_checks == 2
        assert memory.follow_through.outcome_tracked_decisions == 1


def test_decision_memory_insufficient_calibration_stays_insufficient() -> None:
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

        from app.services import decision_outcome_service

        decision_outcome_service.evaluate_decision_outcome(
            db, user.id, decision.id, as_of=TEST_DATE
        )

        memory = decision_memory_service.get_decision_memory(db, user.id)

        breakdown = memory.decision_types[0]
        assert breakdown.decision_type == "major_purchase"
        assert breakdown.calibration_label == "insufficient_data"


def test_decision_memory_breakdown_by_decision_type() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)

        decision_history_service.save_decision(
            db,
            user.id,
            SaveDecisionRequest(
                decision_type="major_purchase",
                title="Laptop",
                input=_major_purchase_input(),
            ),
            as_of=TEST_DATE,
        )
        decision_history_service.save_decision(
            db,
            user.id,
            SaveDecisionRequest(
                decision_type="stress_test",
                title="Job loss",
                input=_stress_test_input(),
            ),
            as_of=TEST_DATE,
        )

        memory = decision_memory_service.get_decision_memory(db, user.id)

        types = {entry.decision_type for entry in memory.decision_types}
        assert types == {"major_purchase", "stress_test"}
        for entry in memory.decision_types:
            assert entry.saved_count == 1


def test_decision_memory_repeated_type_produces_recent_pattern() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)

        for i in range(3):
            decision_history_service.save_decision(
                db,
                user.id,
                SaveDecisionRequest(
                    decision_type="major_purchase",
                    title=f"Item {i}",
                    input=_major_purchase_input(),
                ),
                as_of=TEST_DATE,
            )

        memory = decision_memory_service.get_decision_memory(db, user.id)

        assert any(
            pattern.decision_type == "major_purchase"
            for pattern in memory.recent_patterns
        )


RECENT_PATTERN_NOW = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)


def _save_major_purchase(db, user, title, age_days) -> None:
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
    decision.created_at = RECENT_PATTERN_NOW - timedelta(days=age_days)
    db.commit()


def test_decision_memory_recent_window_produces_pattern() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)

        for i in range(3):
            _save_major_purchase(db, user, f"Item {i}", age_days=10)

        memory = decision_memory_service.get_decision_memory(
            db, user.id, now=RECENT_PATTERN_NOW
        )

        pattern = next(
            p
            for p in memory.recent_patterns
            if p.decision_type == "major_purchase"
        )
        assert pattern.count == 3
        assert "last 90 days" in pattern.text


def test_decision_memory_outside_recent_window_no_pattern() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)

        for i in range(3):
            _save_major_purchase(db, user, f"Item {i}", age_days=100)

        memory = decision_memory_service.get_decision_memory(
            db, user.id, now=RECENT_PATTERN_NOW
        )

        assert not any(
            p.decision_type == "major_purchase"
            for p in memory.recent_patterns
        )


def test_decision_memory_mixed_old_and_recent_counts_only_recent() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)

        _save_major_purchase(db, user, "Old 1", age_days=200)
        _save_major_purchase(db, user, "Old 2", age_days=150)
        _save_major_purchase(db, user, "Recent 1", age_days=10)
        _save_major_purchase(db, user, "Recent 2", age_days=5)

        memory = decision_memory_service.get_decision_memory(
            db, user.id, now=RECENT_PATTERN_NOW
        )

        # 5 total, but only 2 within the recent window -- below the
        # repeated-type pattern threshold of 3, so no pattern fires.
        assert memory.summary.total_saved_decisions == 4
        assert not any(
            p.decision_type == "major_purchase"
            for p in memory.recent_patterns
        )


def test_decision_memory_recent_window_boundary_is_deterministic() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)

        # Exactly at the 90-day cutoff (inclusive: created_at >= cutoff).
        for i in range(3):
            _save_major_purchase(db, user, f"Boundary {i}", age_days=90)

        memory = decision_memory_service.get_decision_memory(
            db, user.id, now=RECENT_PATTERN_NOW
        )

        assert any(
            p.decision_type == "major_purchase"
            for p in memory.recent_patterns
        )


def test_decision_memory_recent_window_no_query_growth() -> None:
    def _count_queries(decision_count: int) -> int:
        with TestingSessionLocal() as db:
            user = create_user(db)
            create_account(db, user)
            for i in range(decision_count):
                _save_major_purchase(db, user, f"Item {i}", age_days=10)

            statements: list[str] = []

            def _capture(conn, cursor, statement, *args) -> None:
                statements.append(statement)

            event.listen(test_engine, "before_cursor_execute", _capture)
            try:
                decision_memory_service.get_decision_memory(
                    db, user.id, now=RECENT_PATTERN_NOW
                )
            finally:
                event.remove(test_engine, "before_cursor_execute", _capture)

            return len(statements)

    small = _count_queries(2)
    large = _count_queries(10)

    assert small == large


def test_decision_memory_no_fuzzy_title_deduplication() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)

        for title in ("New Laptop", "Laptop", "MacBook"):
            decision_history_service.save_decision(
                db,
                user.id,
                SaveDecisionRequest(
                    decision_type="major_purchase",
                    title=title,
                    input=_major_purchase_input(),
                ),
                as_of=TEST_DATE,
            )

        memory = decision_memory_service.get_decision_memory(db, user.id)

        # All three are distinct real-world decisions in the model --
        # memory never clusters by title similarity, so the count is
        # exactly 3, not deduplicated down.
        assert memory.summary.total_saved_decisions == 3
        assert memory.decision_types[0].saved_count == 3


def test_decision_memory_bounded_history_and_deterministic_repeat() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)

        for i in range(5):
            decision_history_service.save_decision(
                db,
                user.id,
                SaveDecisionRequest(
                    decision_type="major_purchase",
                    title=f"Item {i}",
                    input=_major_purchase_input(),
                ),
                as_of=TEST_DATE,
            )

        first = decision_memory_service.get_decision_memory(db, user.id)
        second = decision_memory_service.get_decision_memory(db, user.id)

        assert first.model_dump() == second.model_dump()
        assert first.summary.total_saved_decisions == 5


def test_decision_memory_no_result_mutation() -> None:
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

        decision_memory_service.get_decision_memory(db, user.id)

        db.refresh(decision)
        assert decision.result_snapshot == original_snapshot


def test_decision_memory_no_query_growth_with_more_decisions() -> None:
    def _count_queries(decision_count: int) -> int:
        with TestingSessionLocal() as db:
            user = create_user(db)
            create_account(db, user)
            for i in range(decision_count):
                decision_history_service.save_decision(
                    db,
                    user.id,
                    SaveDecisionRequest(
                        decision_type="major_purchase",
                        title=f"Item {i}",
                        input=_major_purchase_input(),
                    ),
                    as_of=TEST_DATE,
                )

            statements: list[str] = []

            def _capture(conn, cursor, statement, *args) -> None:
                statements.append(statement)

            event.listen(test_engine, "before_cursor_execute", _capture)
            try:
                decision_memory_service.get_decision_memory(db, user.id)
            finally:
                event.remove(test_engine, "before_cursor_execute", _capture)

            return len(statements)

    small = _count_queries(2)
    large = _count_queries(10)

    assert small == large


def test_decision_memory_review_follow_up_count() -> None:
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
        decision.created_at = decision.created_at - timedelta(days=10)
        db.commit()

        memory = decision_memory_service.get_decision_memory(db, user.id)

        assert memory.needs_follow_up_count == 1


def test_decision_memory_cross_user_isolation() -> None:
    with TestingSessionLocal() as db:
        user_a = create_user(db)
        user_b = create_user(db)
        create_account(db, user_a)

        decision_history_service.save_decision(
            db,
            user_a.id,
            SaveDecisionRequest(
                decision_type="major_purchase",
                title="Laptop",
                input=_major_purchase_input(),
            ),
            as_of=TEST_DATE,
        )

        memory_a = decision_memory_service.get_decision_memory(db, user_a.id)
        memory_b = decision_memory_service.get_decision_memory(db, user_b.id)

        assert memory_a.summary.total_saved_decisions == 1
        assert memory_b.status == "no_history"
        assert memory_b.summary.total_saved_decisions == 0


# --- HTTP endpoint -------------------------------------------------------


def test_decision_memory_endpoint_requires_authentication(
    client: TestClient,
) -> None:
    response = client.get("/users/9999/decisions/memory")
    assert response.status_code == 401


def test_decision_memory_endpoint_blocks_other_user(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "memory-owner")

    response = client.get(
        f"/users/{user_id + 1}/decisions/memory", headers=headers
    )

    assert response.status_code == 403


def test_decision_memory_endpoint_returns_populated_summary(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "memory-http")

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
        f"/users/{user_id}/decisions/memory", headers=headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "available"
    assert body["summary"]["total_saved_decisions"] == 1
