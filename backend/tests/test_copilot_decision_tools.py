from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models import User
from app.schemas import CopilotMessageIn, SaveDecisionRequest
from app.services import copilot_free_mode, copilot_service, decision_history_service
from app.services.copilot_service import CopilotClient, run_copilot_turn
from tests.conftest import TestingSessionLocal
from tests.test_decisions import _major_purchase_input, create_account, create_user

TEST_DATE = date(2026, 8, 8)


def _messages(*texts: str) -> list[CopilotMessageIn]:
    return [CopilotMessageIn(role="user", content=t) for t in texts]


def _free_client() -> CopilotClient:
    return CopilotClient(api_key=None)


def _save_decision(db: Session, user: User, title: str = "Laptop"):
    return decision_history_service.save_decision(
        db,
        user.id,
        SaveDecisionRequest(
            decision_type="major_purchase",
            title=title,
            input=_major_purchase_input(),
        ),
        as_of=TEST_DATE,
    )


def test_decision_tools_registered_in_tool_handlers_and_schema() -> None:
    names = {
        "get_decision_memory",
        "get_decision_calibration",
        "get_decisions_needing_review",
        "get_recent_decisions",
    }
    assert names.issubset(copilot_service._TOOL_HANDLERS.keys())
    assert names.issubset(copilot_free_mode._RENDERERS.keys())
    assert names == {tool["name"] for tool in copilot_service._TOOLS} & names


def test_recent_decisions_tool_returns_authorized_users_own_decisions() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)
        _save_decision(db, user, "Laptop")

        result = run_copilot_turn(
            db,
            user.id,
            user,
            _messages("What decisions have I analyzed recently?"),
            _free_client(),
            as_of=TEST_DATE,
        )

        assert result.kind == "answer"
        assert result.tool_used == "Recent Decisions"
        assert "Laptop" in (result.answer or "")


def test_recent_decisions_tool_cross_user_isolation() -> None:
    with TestingSessionLocal() as db:
        owner = create_user(db)
        other = create_user(db)
        create_account(db, owner)
        create_account(db, other)
        _save_decision(db, owner, "Owner Laptop")

        result, chips, _confidence, _warning = (
            copilot_service._handle_recent_decisions(
                db, other.id, {}, TEST_DATE, other
            )
        )

        assert result.total_count == 0
        assert all("Owner Laptop" not in str(chip) for chip in chips)


def test_decisions_needing_review_tool_retrieval() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)
        decision = _save_decision(db, user, "Laptop")
        decision.created_at = decision.created_at - timedelta(days=10)
        db.commit()

        result = run_copilot_turn(
            db,
            user.id,
            user,
            _messages("Which decisions need follow-up?"),
            _free_client(),
            as_of=TEST_DATE,
        )

        assert result.kind == "answer"
        assert result.tool_used == "Decisions Needing Review"
        assert "Laptop" in (result.answer or "")


def test_decision_calibration_tool_insufficient_data_response() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)

        result = run_copilot_turn(
            db,
            user.id,
            user,
            _messages("Do I have enough outcome history for calibration?"),
            _free_client(),
            as_of=TEST_DATE,
        )

        assert result.kind == "answer"
        assert result.tool_used == "Decision Calibration"
        assert "not enough" in (result.answer or "").lower() or (
            "insufficient" not in (result.answer or "").lower()
            and "reliable calibration pattern" in (result.answer or "")
        )


def test_decision_calibration_tool_payload_is_compact() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)

        result, _chips, _confidence, _warning = (
            copilot_service._handle_decision_calibration(
                db, user.id, {}, TEST_DATE, user
            )
        )

        # Deliberately compact: never the full metric_groups/decision_types
        # breakdown the Decision History page's own calibration payload
        # carries.
        dumped = result.model_dump()
        assert "metric_groups" not in dumped
        assert "decision_types" not in dumped


def test_decision_memory_tool_no_raw_result_snapshot_in_payload() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)
        _save_decision(db, user, "Laptop")

        result, chips, _confidence, _warning = (
            copilot_service._handle_decision_memory(
                db, user.id, {}, TEST_DATE, user
            )
        )

        dumped = str(result.model_dump())
        assert "affordability_status" not in dumped
        assert "safe_to_spend_after_purchase_cents" not in dumped
        for chip in chips:
            assert "affordability_status" not in str(chip)


def test_decision_tools_never_mutate_decision_state() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)
        decision = _save_decision(db, user, "Laptop")
        original_status = decision.status

        copilot_service._handle_decision_memory(
            db, user.id, {}, TEST_DATE, user
        )
        copilot_service._handle_decisions_needing_review(
            db, user.id, {}, TEST_DATE, user
        )
        copilot_service._handle_recent_decisions(
            db, user.id, {}, TEST_DATE, user
        )

        db.refresh(decision)
        assert decision.status == original_status


def test_narrate_system_prompt_has_decision_history_grounding_instruction() -> (
    None
):
    assert (
        "never generalize from too little history"
        in copilot_service._NARRATE_SYSTEM_PROMPT
    )


def test_existing_copilot_tool_still_works_after_new_tools_added() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=500_000)

        result = run_copilot_turn(
            db,
            user.id,
            user,
            _messages("What is my safe-to-spend?"),
            _free_client(),
            as_of=TEST_DATE,
        )

        assert result.kind == "answer"
        assert result.tool_used == "Safe-to-Spend"


def test_decision_tool_handlers_ignore_malformed_tool_input() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user)

        for handler in (
            copilot_service._handle_decision_memory,
            copilot_service._handle_decision_calibration,
            copilot_service._handle_decisions_needing_review,
            copilot_service._handle_recent_decisions,
        ):
            result, chips, confidence, warning = handler(
                db, user.id, {"unexpected": "garbage", "nested": [1, 2]},
                TEST_DATE, user,
            )
            assert result is not None
            assert isinstance(chips, list)
