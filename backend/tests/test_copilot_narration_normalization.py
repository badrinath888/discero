"""Provider-narration normalization, one-provider-call-per-turn budget,
and repeated-request consistency.

Covers the production symptoms this hardening pass fixes: malformed
narration ("$90,000.00 cents"), a goal-scoped figure narrated as if it
were the portfolio-wide figure (or vice versa), and up to two provider
calls per turn. See copilot_service.py's `_normalize_for_narration`,
`_goal_intelligence_narration_payload`, `_resolve_deterministic`, and
`run_copilot_turn` module docstring for the architecture this exercises.
"""

import json
from datetime import date

import anthropic
import groq
import httpx

from app.services.copilot_service import CopilotClient, run_copilot_turn
from app.services.goal_intelligence_service import evaluate_goal_intelligence
from app.services.major_purchase_service import _average_monthly_income_cents
from tests.conftest import TestingSessionLocal
from tests.test_copilot_free_mode import (
    create_account,
    create_goal,
    create_user,
    seed_income,
)
from tests.test_copilot_service import _response, _tool_use_block, _user_message

TEST_DATE = date(2026, 8, 8)


def _fake_response(status_code: int) -> httpx.Response:
    return httpx.Response(
        status_code, request=httpx.Request("POST", "https://example.com")
    )


def _budgeted_client(
    *, narrate_input: dict | None = None, raise_exc: Exception | None = None
) -> CopilotClient:
    """A CopilotClient that fails the test outright if the turn ever
    makes a second provider call -- the invariant PHASE 5/26 exist to
    protect. `calls` is exposed on the instance for inspecting exactly
    what a real provider would have been shown.
    """
    client = CopilotClient(api_key="fake-key")
    calls: list[dict] = []

    def fake_call(**kwargs):
        calls.append(kwargs)
        assert len(calls) <= 1, (
            "run_copilot_turn made a second provider call in one turn"
        )
        if raise_exc is not None:
            raise raise_exc
        return _response(
            _tool_use_block(
                "t1",
                "present_financial_answer",
                narrate_input or {"answer": "Here's the answer."},
            )
        )

    client.call = fake_call  # type: ignore[method-assign]
    client.calls = calls  # type: ignore[attr-defined]
    return client


def _narrate_tool_result_payload(client: CopilotClient) -> dict:
    followup_messages = client.calls[0]["messages"]  # type: ignore[attr-defined]
    tool_result_message = followup_messages[-1]
    content_block = tool_result_message["content"][0]
    return json.loads(content_block["content"])


# --- PHASE 27/28: currency normalization + goal/portfolio scoping -----


def test_goal_intelligence_narrate_payload_has_no_raw_cents_and_scopes_named_goal() -> (
    None
):
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=500_000)
        seed_income(db, user)
        create_goal(
            db,
            user,
            name="Emergency Fund",
            target_cents=600_000,
            saved_cents=300_000,
            target_date=date(2027, 6, 1),
        )
        create_goal(
            db,
            user,
            name="New Laptop",
            target_cents=200_000,
            saved_cents=0,
            target_date=date(2027, 6, 1),
        )

        client = _budgeted_client()

        result = run_copilot_turn(
            db,
            user.id,
            user,
            _user_message(
                "Will I reach my Emergency Fund by the target date?"
            ),
            client,
            as_of=TEST_DATE,
        )

        assert result.kind == "answer"
        assert len(client.calls) == 1  # type: ignore[attr-defined]

        payload = _narrate_tool_result_payload(client)
        raw = json.dumps(payload)

        # The exact production bug class: no *_cents field ever reaches
        # the provider, so it can never mis-divide or mislabel one.
        assert "_cents" not in raw

        # Scoped, not flattened: the goal-specific figure and the
        # portfolio-wide figure are never merged into one ambiguous
        # "required monthly".
        assert "selected_goal" in payload
        assert "goals" not in payload
        assert payload["selected_goal"]["name"] == "Emergency Fund"
        assert "New Laptop" not in raw
        assert "required_monthly" in payload["selected_goal"]
        assert "total_required" in payload["portfolio"]

        capacity_cents = _average_monthly_income_cents(
            db, user.id, TEST_DATE
        )
        expected = evaluate_goal_intelligence(
            db,
            user.id,
            monthly_capacity_cents=capacity_cents,
            as_of=TEST_DATE,
        )
        expected_goal = next(
            g for g in expected.goals if g.name == "Emergency Fund"
        )

        def currency(cents: int) -> str:
            sign = "-" if cents < 0 else ""
            return f"{sign}${abs(cents) / 100:,.2f}"

        assert payload["selected_goal"]["required_monthly"] == currency(
            expected_goal.required_monthly_cents
        )
        assert payload["portfolio"]["total_required"] == currency(
            expected.total_required_cents
        )

        # PHASE 20: the structured card (key_numbers), not just the
        # narration payload, must be scoped to the named goal -- the
        # production symptom was Emergency Fund questions still
        # dominated by portfolio-wide chips like "Most urgent: New
        # Laptop" or the portfolio's "Required monthly".
        chip_labels = [c.label for c in result.key_numbers]
        assert "Most urgent" not in chip_labels
        assert "Target date" in chip_labels
        assert "Allocated monthly" in chip_labels
        assert "Monthly gap" in chip_labels

        required_chip = next(
            c for c in result.key_numbers if c.label == "Required monthly"
        )
        assert required_chip.value_display == currency(
            expected_goal.required_monthly_cents
        )
        # Portfolio capacity/headroom appear only as clearly-labeled
        # secondary context, never under the same "Required monthly"
        # label the selected goal's own figure uses.
        assert any(c.label == "Portfolio capacity" for c in result.key_numbers)
        assert any(
            c.label == "Remaining headroom" for c in result.key_numbers
        )


def test_goal_intelligence_portfolio_query_keeps_portfolio_card() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=500_000)
        seed_income(db, user)
        create_goal(
            db,
            user,
            name="Emergency Fund",
            target_cents=600_000,
            saved_cents=300_000,
            target_date=date(2027, 6, 1),
        )
        create_goal(
            db,
            user,
            name="New Laptop",
            target_cents=200_000,
            saved_cents=0,
            target_date=date(2027, 6, 1),
        )

        client = _budgeted_client()

        result = run_copilot_turn(
            db,
            user.id,
            user,
            _user_message("Which goal is most urgent?"),
            client,
            as_of=TEST_DATE,
        )

        assert result.kind == "answer"
        chip_labels = [c.label for c in result.key_numbers]
        # A genuine portfolio question still gets the portfolio card --
        # scoping to a named goal must never apply when none was asked
        # about.
        assert "Most urgent" in chip_labels
        assert "Monthly capacity" in chip_labels
        assert "Remaining headroom" in chip_labels


def test_narrate_payload_normalizes_duration_and_currency_units() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=0)

        client = _budgeted_client()

        result = run_copilot_turn(
            db,
            user.id,
            user,
            _user_message("What's my safe to spend?"),
            client,
            as_of=TEST_DATE,
        )

        assert result.kind == "answer"
        payload = _narrate_tool_result_payload(client)

        # 0 cents -> "$0.00", never dropped or left as a bare int.
        assert payload["safe_to_spend"] == "$0.00"
        # horizon_days (an int) gets an explicit unit, never a bare
        # number the provider has to guess the meaning of.
        assert payload["horizon_days"].endswith(("day", "days"))
        assert "_cents" not in json.dumps(payload)


# --- PHASE 26: provider call budget -- never two calls in one turn ----


def test_deterministic_route_spends_at_most_one_provider_call() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=500_000)
        client = _budgeted_client()

        result = run_copilot_turn(
            db,
            user.id,
            user,
            _user_message("What's my safe to spend?"),
            client,
            as_of=TEST_DATE,
        )

        assert result.kind == "answer"
        assert result.provenance == "ai_enhanced"
        assert len(client.calls) == 1  # type: ignore[attr-defined]


def test_provider_decide_route_never_makes_a_second_call_for_narration() -> (
    None
):
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=500_000)
        client = _budgeted_client()
        # Overwrite the fixture's narrate-only mock: this message is
        # unclassifiable by the deterministic router, so the one
        # provider call is DECIDE, and it must never be followed by a
        # second (NARRATE) call.
        calls: list[dict] = []

        def fake_call(**kwargs):
            calls.append(kwargs)
            assert len(calls) <= 1, (
                "a tool picked by DECIDE must be narrated with the "
                "deterministic template, never a second provider call"
            )
            return _response(
                _tool_use_block("t1", "get_safe_to_spend", {})
            )

        client.call = fake_call  # type: ignore[method-assign]

        result = run_copilot_turn(
            db,
            user.id,
            user,
            _user_message(
                "Is tonight a good night for me to go out to eat?"
            ),
            client,
            as_of=TEST_DATE,
        )

        assert result.kind == "answer"
        assert result.provenance == "deterministic"
        assert result.tool_used == "Safe-to-Spend"
        assert len(calls) == 1


def test_deterministic_clarification_spends_zero_provider_calls() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        client = CopilotClient(api_key="fake-key")

        def fail_if_called(**kwargs):
            raise AssertionError(
                "provider called for a deterministically-resolved "
                "clarification"
            )

        client.call = fail_if_called  # type: ignore[method-assign]

        result = run_copilot_turn(
            db,
            user.id,
            user,
            _user_message("Can I afford it?"),
            client,
            as_of=TEST_DATE,
        )

        assert result.kind == "clarifying_question"
        assert result.provenance == "deterministic"


def test_decide_failure_never_triggers_a_second_provider_call() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=500_000)
        client = _budgeted_client(
            raise_exc=anthropic.APITimeoutError(request=None)
        )

        result = run_copilot_turn(
            db,
            user.id,
            user,
            _user_message(
                "Is tonight a good night for me to go out to eat?"
            ),
            client,
            as_of=TEST_DATE,
        )

        # DECIDE failed and the deterministic router had no safe
        # resolution to fall back to -- concise unsupported, never a
        # fabricated answer, and never a second provider attempt.
        assert result.kind == "out_of_scope"
        assert len(client.calls) == 1  # type: ignore[attr-defined]


# --- PHASE 15/31: NARRATE failure can never discard a successful tool -


def test_narrate_failures_of_every_kind_still_return_the_real_answer() -> (
    None
):
    failure_modes = [
        anthropic.APITimeoutError(request=None),
        anthropic.RateLimitError(
            message="rate limited",
            response=_fake_response(429),
            body=None,
        ),
        anthropic.APIConnectionError(request=None),
    ]

    for exc in failure_modes:
        with TestingSessionLocal() as db:
            user = create_user(db)
            create_account(db, user, available_balance_cents=500_000)
            client = _budgeted_client(raise_exc=exc)

            result = run_copilot_turn(
                db,
                user.id,
                user,
                _user_message("What's my safe to spend?"),
                client,
                as_of=TEST_DATE,
            )

            assert result.kind == "answer", exc
            assert result.provenance == "deterministic", exc
            assert result.tool_used == "Safe-to-Spend", exc
            safe_chip = next(
                c
                for c in result.key_numbers
                if c.label == "Safe to spend"
            )
            assert safe_chip.value_display == "$5,000.00", exc


def test_narrate_malformed_and_empty_responses_still_return_the_real_answer() -> (
    None
):
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=500_000)
        client = _budgeted_client()

        def fake_call(**kwargs):
            # Wrong tool name entirely -- not present_financial_answer.
            return _response(
                _tool_use_block("t1", "get_safe_to_spend", {})
            )

        client.call = fake_call  # type: ignore[method-assign]

        result = run_copilot_turn(
            db,
            user.id,
            user,
            _user_message("What's my safe to spend?"),
            client,
            as_of=TEST_DATE,
        )

        assert result.kind == "answer"
        assert result.provenance == "deterministic"

    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=500_000)
        client = _budgeted_client(narrate_input={"answer": ""})

        result = run_copilot_turn(
            db,
            user.id,
            user,
            _user_message("What's my safe to spend?"),
            client,
            as_of=TEST_DATE,
        )

        # Empty narration text is treated as a failure, not shown.
        assert result.kind == "answer"
        assert result.provenance == "deterministic"
        assert result.answer


# --- PHASE 18/29: repeated identical requests stay financially stable -


def test_repeated_identical_requests_produce_stable_financial_content() -> (
    None
):
    behaviors = [
        lambda: _budgeted_client(
            narrate_input={"answer": "You have plenty of room."}
        ),
        lambda: _budgeted_client(
            narrate_input={"answer": "Room to spend looks good here."}
        ),
        lambda: _budgeted_client(
            raise_exc=anthropic.APITimeoutError(request=None)
        ),
        lambda: _budgeted_client(
            raise_exc=groq.RateLimitError(
                message="rate limited",
                response=_fake_response(429),
                body=None,
            )
        ),
        lambda: _budgeted_client(narrate_input={"not_an_answer": True}),
    ]

    tool_used_seen = set()
    chip_seen = set()

    for make_client in behaviors:
        with TestingSessionLocal() as db:
            user = create_user(db)
            create_account(db, user, available_balance_cents=500_000)
            client = make_client()

            result = run_copilot_turn(
                db,
                user.id,
                user,
                _user_message("What's my safe to spend?"),
                client,
                as_of=TEST_DATE,
            )

            assert result.kind == "answer"
            assert "cents" not in (result.answer or "").lower()
            tool_used_seen.add(result.tool_used)
            safe_chip = next(
                c
                for c in result.key_numbers
                if c.label == "Safe to spend"
            )
            chip_seen.add(safe_chip.value_display)

    # Same tool, same deterministic dollar figure every time regardless
    # of provider wording/availability -- only prose is allowed to vary.
    assert tool_used_seen == {"Safe-to-Spend"}
    assert chip_seen == {"$5,000.00"}
