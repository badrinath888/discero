"""Copilot-level regression: temporary_income_loss stress-test turns
that omit stress_amount_cents must derive it from real income history
instead of asking the user for a dollar amount -- see
financial_stress_test_service._derive_temporary_income_loss_cents.

DECIDE/NARRATE orchestration and tool dispatch are unchanged and
already covered elsewhere; these tests target only the specific
production bug (poor clarification UX for a clearly-stated temporary
full income loss) across both providers.
"""

from datetime import date

from sqlalchemy import select

from app.models import CopilotAuditEvent, Transaction
from app.services.copilot_groq_client import GroqCopilotClient
from app.services.copilot_service import CopilotClient, run_copilot_turn
from tests.conftest import TestingSessionLocal
from tests.test_copilot_service import (
    _response,
    _tool_use_block,
    _user_message,
    create_account,
    create_user,
)

TEST_DATE = date(2026, 8, 8)


def seed_income(db, user) -> None:
    for month in (5, 6, 7):
        db.add(
            Transaction(
                user_id=user.id,
                posted_on=date(2026, month, 1),
                description="Paycheck",
                amount_cents=300_000,
                category="Income",
            )
        )
    db.commit()


def _income_loss_tool_input() -> dict:
    return {
        "scenario_type": "temporary_income_loss",
        "scenario_name": "No income for two months",
        "event_date": "2026-08-10",
        "duration_days": 60,
    }


def test_groq_income_loss_without_amount_succeeds_without_clarification() -> (
    None
):
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=1_000_000)
        seed_income(db, user)

        client = GroqCopilotClient(api_key="fake-groq-key")
        calls = {"n": 0}

        def fake_call(**kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return _response(
                    _tool_use_block(
                        "t1", "run_stress_test", _income_loss_tool_input()
                    )
                )
            return _response(
                _tool_use_block(
                    "t2",
                    "present_financial_answer",
                    {"answer": "Here's how that would hold up."},
                )
            )

        client.call = fake_call  # type: ignore[method-assign]

        result = run_copilot_turn(
            db,
            user.id,
            user,
            _user_message(
                "If I suddenly had no income coming in for around two "
                "months, how long could my finances hold up and what "
                "would get hit first?"
            ),
            client,
            as_of=TEST_DATE,
        )

        assert result.kind == "answer"
        assert result.tool_used == "Financial Stress Test"
        # Real derived-from-income result, not a request for more info.
        assert calls["n"] == 2


def test_anthropic_income_loss_without_amount_succeeds_without_clarification() -> (
    None
):
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=1_000_000)
        seed_income(db, user)

        client = CopilotClient(api_key="fake-key")
        calls = {"n": 0}

        def fake_call(**kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return _response(
                    _tool_use_block(
                        "t1", "run_stress_test", _income_loss_tool_input()
                    )
                )
            return _response(
                _tool_use_block(
                    "t2",
                    "present_financial_answer",
                    {"answer": "Here's how that would hold up."},
                )
            )

        client.call = fake_call  # type: ignore[method-assign]

        result = run_copilot_turn(
            db,
            user.id,
            user,
            _user_message(
                "If I suddenly had no income for around two months, "
                "how long could my finances hold up?"
            ),
            client,
            as_of=TEST_DATE,
        )

        assert result.kind == "answer"
        assert result.tool_used == "Financial Stress Test"
        assert calls["n"] == 2


def test_income_loss_with_no_income_history_returns_human_readable_clarification() -> (
    None
):
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=1_000_000)
        # No income transactions -- nothing to derive from.

        client = GroqCopilotClient(api_key="fake-groq-key")

        def fake_call(**kwargs):
            return _response(
                _tool_use_block(
                    "t1", "run_stress_test", _income_loss_tool_input()
                )
            )

        client.call = fake_call  # type: ignore[method-assign]

        result = run_copilot_turn(
            db,
            user.id,
            user,
            _user_message(
                "If I suddenly had no income for around two months, "
                "how long could my finances hold up?"
            ),
            client,
            as_of=TEST_DATE,
        )

        assert result.kind == "clarifying_question"
        # Never leaks the internal field name to the user.
        assert "stress_amount_cents" not in result.clarifying_question


def test_income_loss_derivation_audit_row_has_no_income_or_amount_payload() -> (
    None
):
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=1_000_000)
        seed_income(db, user)

        client = GroqCopilotClient(api_key="fake-groq-key")
        calls = {"n": 0}

        def fake_call(**kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return _response(
                    _tool_use_block(
                        "t1", "run_stress_test", _income_loss_tool_input()
                    )
                )
            return _response(
                _tool_use_block(
                    "t2",
                    "present_financial_answer",
                    {"answer": "Here's how that would hold up."},
                )
            )

        client.call = fake_call  # type: ignore[method-assign]

        run_copilot_turn(
            db,
            user.id,
            user,
            _user_message(
                "If I suddenly had no income for around two months, "
                "how long could my finances hold up?"
            ),
            client,
            as_of=TEST_DATE,
        )

        events = list(
            db.scalars(
                select(CopilotAuditEvent).order_by(CopilotAuditEvent.id)
            ).all()
        )
        assert len(events) == 1
        assert events[0].tool_name == "run_stress_test"
        assert events[0].success is True
        # No derived amount, income figure, or raw payload persisted --
        # only the bounded routing-outcome kind.
        assert events[0].event_metadata == {"route_kind": "tool"}
