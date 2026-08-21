"""AI Evals + Observability 1.0 -- trace, timing, token usage, and cost.

Covers: successful no-tool/single-tool turns, tool failure, provider
failure, token metadata present/absent, configured/unconfigured cost,
latency fields, request-id existence, and audit-metadata privacy for
the new observability fields. See app/services/copilot_observability.py
and the token/cost plumbing in app/services/copilot_service.py.
"""

from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.config import settings
from app.models import CopilotAuditEvent
from app.services import copilot_observability as obs
from app.services.copilot_service import CopilotClient, run_copilot_turn
from tests.test_copilot_service import (
    _response,
    _tool_use_block,
    _user_message,
    create_account,
    create_user,
)
from tests.conftest import TestingSessionLocal

TEST_DATE = date(2026, 8, 8)


def _events(db) -> list[CopilotAuditEvent]:
    return list(
        db.scalars(
            select(CopilotAuditEvent).order_by(CopilotAuditEvent.id)
        ).all()
    )


def _anthropic_usage(input_tokens: int, output_tokens: int) -> SimpleNamespace:
    return SimpleNamespace(
        input_tokens=input_tokens, output_tokens=output_tokens
    )


def _openai_usage(prompt_tokens: int, completion_tokens: int) -> SimpleNamespace:
    return SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
    )


# --- extract_token_usage / estimate_cost (pure unit tests) --------------


def test_extract_token_usage_reads_anthropic_shape() -> None:
    response = SimpleNamespace(usage=_anthropic_usage(120, 40))
    usage = obs.extract_token_usage(response)
    assert usage == obs.TokenUsage(
        input_tokens=120, output_tokens=40, total_tokens=160
    )


def test_extract_token_usage_reads_openai_shape() -> None:
    response = SimpleNamespace(usage=_openai_usage(200, 50))
    usage = obs.extract_token_usage(response)
    assert usage == obs.TokenUsage(
        input_tokens=200, output_tokens=50, total_tokens=250
    )


def test_extract_token_usage_missing_is_none() -> None:
    assert obs.extract_token_usage(SimpleNamespace()) is None
    assert obs.extract_token_usage(SimpleNamespace(usage=None)) is None


def test_estimate_cost_requires_both_rates_configured() -> None:
    usage = obs.TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000, total_tokens=2_000_000)
    assert obs.estimate_cost(usage, None, None) is None
    assert obs.estimate_cost(usage, 3.0, None) is None
    assert obs.estimate_cost(usage, None, 15.0) is None


def test_estimate_cost_computes_from_real_usage_only() -> None:
    usage = obs.TokenUsage(
        input_tokens=1_000_000, output_tokens=500_000, total_tokens=1_500_000
    )
    cost = obs.estimate_cost(usage, input_rate_per_million=3.0, output_rate_per_million=15.0)
    assert cost == pytest.approx(3.0 + 7.5)


def test_estimate_cost_none_usage_is_null() -> None:
    assert obs.estimate_cost(None, 3.0, 15.0) is None


# --- Groq client attaches real usage, never fabricates it ---------------


def test_groq_response_conversion_preserves_usage() -> None:
    from app.services.copilot_groq_client import _from_groq_response

    fake_choice = SimpleNamespace(
        message=SimpleNamespace(content="hi", tool_calls=None)
    )
    fake_response = SimpleNamespace(
        choices=[fake_choice], usage=_openai_usage(10, 5)
    )

    converted = _from_groq_response(fake_response)
    usage = obs.extract_token_usage(converted)
    assert usage == obs.TokenUsage(
        input_tokens=10, output_tokens=5, total_tokens=15
    )


# --- End-to-end: token usage/cost flow into the audit trail -------------


def test_ai_mode_tool_success_records_token_usage_when_provider_supplies_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "copilot_input_cost_per_million_tokens", 3.0)
    monkeypatch.setattr(
        settings, "copilot_output_cost_per_million_tokens", 15.0
    )

    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=500_000)
        client = CopilotClient(api_key="fake-key")

        def fake_call(**kwargs):
            response = _response(
                _tool_use_block(
                    "t1",
                    "present_financial_answer",
                    {"answer": "You have room."},
                )
            )
            response.usage = _anthropic_usage(1000, 200)
            return response

        client.call = fake_call  # type: ignore[method-assign]

        run_copilot_turn(
            db,
            user.id,
            user,
            _user_message("What's my safe to spend?"),
            client,
            as_of=TEST_DATE,
        )

        event = _events(db)[0]
        assert event.event_metadata["input_tokens"] == 1000
        assert event.event_metadata["output_tokens"] == 200
        assert event.event_metadata["total_tokens"] == 1200
        # (1000 * 3 + 200 * 15) / 1_000_000
        assert event.event_metadata["estimated_cost"] == pytest.approx(0.006)


def test_ai_mode_tool_success_has_no_cost_when_rates_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "copilot_input_cost_per_million_tokens", None)
    monkeypatch.setattr(
        settings, "copilot_output_cost_per_million_tokens", None
    )

    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=500_000)
        client = CopilotClient(api_key="fake-key")

        def fake_call(**kwargs):
            response = _response(
                _tool_use_block(
                    "t1",
                    "present_financial_answer",
                    {"answer": "You have room."},
                )
            )
            response.usage = _anthropic_usage(1000, 200)
            return response

        client.call = fake_call  # type: ignore[method-assign]

        run_copilot_turn(
            db,
            user.id,
            user,
            _user_message("What's my safe to spend?"),
            client,
            as_of=TEST_DATE,
        )

        event = _events(db)[0]
        assert event.event_metadata["input_tokens"] == 1000
        assert "estimated_cost" not in event.event_metadata


def test_free_mode_turn_has_no_token_usage_no_provider_was_called() -> None:
    # No API key -- the deterministic router answers directly. There is
    # no provider call to have token usage from, so none must appear.
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=500_000)
        client = CopilotClient(api_key=None)

        run_copilot_turn(
            db,
            user.id,
            user,
            _user_message("What's my safe to spend?"),
            client,
            as_of=TEST_DATE,
        )

        event = _events(db)[0]
        assert "input_tokens" not in event.event_metadata
        assert "estimated_cost" not in (event.event_metadata or {})


def test_ai_mode_narrate_failure_still_has_no_fabricated_token_usage() -> None:
    # Provider call raised -- no response, so no usage object exists to
    # read from. copilot_audit metadata must not invent one.
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=500_000)
        client = CopilotClient(api_key="fake-key")

        def fake_call(**kwargs):
            raise TimeoutError("boom")

        client.call = fake_call  # type: ignore[method-assign]

        result = run_copilot_turn(
            db,
            user.id,
            user,
            _user_message("What's my safe to spend?"),
            client,
            as_of=TEST_DATE,
        )

        # Narrate failure still returns the real deterministic result.
        assert result.kind == "answer"
        assert result.tool_used == "Safe-to-Spend"

        failure_event = next(
            e for e in _events(db) if e.event_type == "provider_failure"
        )
        assert "input_tokens" not in (failure_event.event_metadata or {})


# --- Latency fields: present, non-negative, internally consistent -------


def test_latency_fields_are_non_negative_and_consistent() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=500_000)
        client = CopilotClient(api_key=None)

        run_copilot_turn(
            db,
            user.id,
            user,
            _user_message("What's my safe to spend?"),
            client,
            as_of=TEST_DATE,
        )

        event = _events(db)[0]
        assert event.latency_ms is not None
        assert event.latency_ms >= 0
        total_latency_ms = event.event_metadata["total_latency_ms"]
        assert total_latency_ms >= event.latency_ms


def test_request_id_present_on_every_audit_row() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=500_000)
        client = CopilotClient(api_key=None)

        run_copilot_turn(
            db,
            user.id,
            user,
            _user_message("What's my safe to spend?"),
            client,
            as_of=TEST_DATE,
        )

        event = _events(db)[0]
        assert event.request_id
        assert len(event.request_id) > 0


# --- CopilotTrace: the typed, testable execution-trace object -----------


def test_copilot_trace_fields_success() -> None:
    trace = obs.CopilotTrace(
        request_id="abc123",
        tool="get_safe_to_spend",
        tool_calls=1,
        tool_duration_ms=8,
        provider_duration_ms=420,
        total_duration_ms=435,
        input_tokens=650,
        output_tokens=120,
        total_tokens=770,
        estimated_cost=0.0037,
        success=True,
    )
    assert trace.success is True
    assert trace.failure_stage is None
    assert trace.total_duration_ms >= (trace.tool_duration_ms or 0)


def test_copilot_trace_failure_stage() -> None:
    trace = obs.CopilotTrace(
        request_id="abc123",
        tool=None,
        tool_calls=0,
        tool_duration_ms=None,
        provider_duration_ms=15000,
        total_duration_ms=15000,
        input_tokens=None,
        output_tokens=None,
        total_tokens=None,
        estimated_cost=None,
        success=False,
        failure_stage="provider",
    )
    assert trace.success is False
    assert trace.failure_stage == "provider"


def test_log_turn_completed_success_logs_info(
    caplog: pytest.LogCaptureFixture,
) -> None:
    trace = obs.CopilotTrace(
        request_id="req-1",
        tool="get_safe_to_spend",
        tool_calls=1,
        tool_duration_ms=5,
        provider_duration_ms=100,
        total_duration_ms=110,
        input_tokens=50,
        output_tokens=20,
        total_tokens=70,
        estimated_cost=None,
        success=True,
    )
    with caplog.at_level("INFO", logger="app.services.copilot_observability"):
        obs.log_turn_completed(trace)

    assert any(
        "copilot_turn_completed" in r.message for r in caplog.records
    )


def test_log_turn_completed_failure_logs_warning_with_failure_stage(
    caplog: pytest.LogCaptureFixture,
) -> None:
    trace = obs.CopilotTrace(
        request_id="req-2",
        tool=None,
        tool_calls=0,
        tool_duration_ms=None,
        provider_duration_ms=None,
        total_duration_ms=50,
        input_tokens=None,
        output_tokens=None,
        total_tokens=None,
        estimated_cost=None,
        success=False,
        failure_stage="provider",
    )
    with caplog.at_level("WARNING", logger="app.services.copilot_observability"):
        obs.log_turn_completed(trace)

    assert any(
        "copilot_turn_failed" in r.message
        and "failure_stage=provider" in r.message
        for r in caplog.records
    )


# --- No sensitive payload leaks into operational log output -------------


def test_operational_log_never_contains_prompt_or_dollar_amounts(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=500_000)
        client = CopilotClient(api_key=None)

        with caplog.at_level(
            "INFO", logger="app.services.copilot_observability"
        ):
            run_copilot_turn(
                db,
                user.id,
                user,
                _user_message(
                    "What's my safe to spend? My SSN is 123-45-6789."
                ),
                client,
                as_of=TEST_DATE,
            )

        completed_logs = [
            r.message
            for r in caplog.records
            if "copilot_turn_completed" in r.message
        ]
        assert completed_logs
        for message in completed_logs:
            assert "123-45-6789" not in message
            assert "$" not in message
