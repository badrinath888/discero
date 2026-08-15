from datetime import date, timedelta
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models import (
    FinancialAccount,
    PlaidItem,
    RecurringItem,
    SavingsGoal,
    Transaction,
    User,
)
from app.schemas import CopilotMessageIn
from app.services.copilot_service import CopilotClient, run_copilot_turn
from tests.conftest import TestingSessionLocal


TEST_DATE = date(2026, 8, 8)


def create_user(db: Session) -> User:
    user = User(
        email=f"copilot-{uuid4().hex}@example.com",
        password_hash="test-password-hash",
        email_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_account(
    db: Session, user: User, *, available_balance_cents: int = 500_000
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


def create_goal(
    db: Session,
    user: User,
    *,
    name: str = "Vacation",
    target_cents: int = 600_000,
    saved_cents: int = 0,
    target_date: date | None = date(2026, 12, 31),
) -> SavingsGoal:
    goal = SavingsGoal(
        user_id=user.id,
        name=name,
        target_cents=target_cents,
        saved_cents=saved_cents,
        target_date=target_date,
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return goal


def create_recurring_item(
    db: Session,
    user: User,
    *,
    merchant: str,
    amount_cents: int,
    next_payment: date,
    frequency: str = "Monthly",
    status: str = "active",
    confidence_score: float = 90.0,
    category: str = "Bills",
) -> RecurringItem:
    item = RecurringItem(
        user_id=user.id,
        merchant=merchant,
        normalized_merchant=f"{merchant.upper()}-{uuid4().hex}",
        category=category,
        amount_cents=amount_cents,
        frequency=frequency,
        last_payment=next_payment - timedelta(days=30),
        next_payment=next_payment,
        status=status,
        confidence_score=confidence_score,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def _text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def _tool_use_block(
    tool_id: str, name: str, tool_input: dict
) -> SimpleNamespace:
    return SimpleNamespace(
        type="tool_use", id=tool_id, name=name, input=tool_input
    )


def _response(*blocks: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(content=list(blocks))


def _user_message(content: str) -> list[CopilotMessageIn]:
    return [CopilotMessageIn(role="user", content=content)]


def test_free_mode_answers_without_api_key() -> None:
    # Free mode is the default fallback with no key configured -- a
    # supported question must never come back as "unavailable".
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=500_000)
        client = CopilotClient(api_key=None)

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
        assert result.tool_used == "Safe-to-Spend"
        safe_chip = next(
            c for c in result.key_numbers if c.label == "Safe to spend"
        )
        assert safe_chip.value_display == "$5,000.00"


def test_free_mode_safe_to_spend_reflects_corrected_multi_occurrence() -> (
    None
):
    # Regression test for the Safe-to-Spend recurrence-horizon fix: a
    # weekly bill recurs 5 times within the default 30-day horizon,
    # not once, so a deterministic (no API key) Safe-to-Spend question
    # must surface the corrected total -- no special Copilot math,
    # just the same calculate_safe_to_spend result other tests use.
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=500_000)
        create_recurring_item(
            db,
            user,
            merchant="Groceries",
            amount_cents=5_000,
            next_payment=date(2026, 8, 10),
            frequency="Weekly",
        )
        client = CopilotClient(api_key=None)

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
        assert result.tool_used == "Safe-to-Spend"
        safe_chip = next(
            c for c in result.key_numbers if c.label == "Safe to spend"
        )
        # 500_000 - (5 occurrences x 5_000) = 475_000 cents.
        assert safe_chip.value_display == "$4,750.00"


def test_safe_to_spend_tool_grounds_chips_in_real_calculation() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=500_000)

        client = CopilotClient(api_key="fake-key")
        calls = {"n": 0}

        def fake_call(**kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return _response(
                    _tool_use_block(
                        "tool_1", "get_safe_to_spend", {}
                    )
                )
            return _response(
                _tool_use_block(
                    "tool_2",
                    "present_financial_answer",
                    {
                        "answer": "You have plenty of room to spend.",
                        "why": "Your liquid balance comfortably covers obligations.",
                    },
                )
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
        assert result.tool_used == "Safe-to-Spend"
        assert result.answer == "You have plenty of room to spend."
        assert result.why is not None

        safe_chip = next(
            c for c in result.key_numbers if c.label == "Safe to spend"
        )
        # 500_000 cents available, no obligations/reserve configured.
        assert safe_chip.value_display == "$5,000.00"
        assert calls["n"] == 2


def test_major_purchase_tool_converts_dollars_to_cents_via_schema() -> (
    None
):
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=5_000_000)

        client = CopilotClient(api_key="fake-key")

        def fake_call(**kwargs):
            tools = kwargs.get("tools") or []
            if any(t.get("name") == "present_financial_answer" for t in tools):
                return _response(
                    _tool_use_block(
                        "tool_2",
                        "present_financial_answer",
                        {"answer": "Yes, that's affordable."},
                    )
                )
            return _response(
                _tool_use_block(
                    "tool_1",
                    "simulate_major_purchase",
                    {
                        "purchase_name": "Laptop",
                        "purchase_amount_cents": 150_000,
                        "purchase_date": "2026-08-15",
                    },
                )
            )

        client.call = fake_call  # type: ignore[method-assign]

        result = run_copilot_turn(
            db,
            user.id,
            user,
            _user_message("Can I afford a $1,500 laptop?"),
            client,
            as_of=TEST_DATE,
        )

        assert result.kind == "answer"
        assert result.tool_used == "Major Purchase Simulator"
        affordability_chip = next(
            c for c in result.key_numbers if c.label == "Affordability"
        )
        assert affordability_chip.value_display == "Affordable"


def test_what_if_tool_grounds_chips_in_real_calculation() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=500_000)

        client = CopilotClient(api_key="fake-key")

        def fake_call(**kwargs):
            tools = kwargs.get("tools") or []
            if any(
                t.get("name") == "present_financial_answer" for t in tools
            ):
                return _response(
                    _tool_use_block(
                        "tool_2",
                        "present_financial_answer",
                        {"answer": "Your safe-to-spend would drop."},
                    )
                )
            return _response(
                _tool_use_block(
                    "tool_1",
                    "run_what_if",
                    {
                        "scenario_type": "monthly_expense_change",
                        "scenario_name": "Rent increase",
                        "monthly_amount_change_cents": 40_000,
                    },
                )
            )

        client.call = fake_call  # type: ignore[method-assign]

        result = run_copilot_turn(
            db,
            user.id,
            user,
            _user_message(
                "What happens if my rent goes up by $400 a month?"
            ),
            client,
            as_of=TEST_DATE,
        )

        assert result.kind == "answer"
        assert result.tool_used == "What-If Simulator"
        before_chip = next(
            c
            for c in result.key_numbers
            if c.label == "Safe to spend before"
        )
        after_chip = next(
            c for c in result.key_numbers if c.label == "Safe to spend after"
        )
        # 500_000 liquid, no obligations -- a $400/month expense
        # increase reduces safe-to-spend by the same amount.
        assert before_chip.value_display == "$5,000.00"
        assert after_chip.value_display == "$4,600.00"


def test_what_if_tool_rejects_zero_amount_change() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=500_000)

        client = CopilotClient(api_key="fake-key")

        def fake_call(**kwargs):
            return _response(
                _tool_use_block(
                    "tool_1",
                    "run_what_if",
                    {
                        "scenario_type": "monthly_expense_change",
                        "scenario_name": "Rent increase",
                        "monthly_amount_change_cents": 0,
                    },
                )
            )

        client.call = fake_call  # type: ignore[method-assign]

        result = run_copilot_turn(
            db,
            user.id,
            user,
            _user_message("What if my rent changes?"),
            client,
            as_of=TEST_DATE,
        )

        assert result.kind == "clarifying_question"


def test_stress_test_chips_include_runway_and_key_driver() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=500_000)

        client = CopilotClient(api_key="fake-key")

        def fake_call(**kwargs):
            tools = kwargs.get("tools") or []
            if any(
                t.get("name") == "present_financial_answer" for t in tools
            ):
                return _response(
                    _tool_use_block(
                        "tool_2",
                        "present_financial_answer",
                        {"answer": "This would be manageable."},
                    )
                )
            return _response(
                _tool_use_block(
                    "tool_1",
                    "run_stress_test",
                    {
                        "scenario_type": "emergency_expense",
                        "scenario_name": "Car repair",
                        "stress_amount_cents": 100_000,
                        "event_date": "2026-08-10",
                    },
                )
            )

        client.call = fake_call  # type: ignore[method-assign]

        result = run_copilot_turn(
            db,
            user.id,
            user,
            _user_message("What if I have a $1,000 car repair?"),
            client,
            as_of=TEST_DATE,
        )

        assert result.kind == "answer"
        assert result.tool_used == "Financial Stress Test"
        runway_chip = next(
            c for c in result.key_numbers if c.label == "Runway"
        )
        pressure_chip = next(
            c for c in result.key_numbers if c.label == "Biggest pressure"
        )
        assert runway_chip.value_display == "Not exhausted"
        assert pressure_chip.value_display == "One-time emergency expense"


def test_request_clarification_short_circuits_without_narration() -> (
    None
):
    with TestingSessionLocal() as db:
        user = create_user(db)
        client = CopilotClient(api_key="fake-key")
        calls = {"n": 0}

        def fake_call(**kwargs):
            calls["n"] += 1
            return _response(
                _tool_use_block(
                    "tool_1",
                    "request_clarification",
                    {
                        "question": "What amount are you considering?",
                        "options": ["$1,000", "$2,000"],
                    },
                )
            )

        client.call = fake_call  # type: ignore[method-assign]

        result = run_copilot_turn(
            db,
            user.id,
            user,
            _user_message("Can I afford it?"),
            client,
            as_of=TEST_DATE,
        )

        assert result.kind == "clarifying_question"
        assert result.clarifying_question == (
            "What amount are you considering?"
        )
        assert result.clarifying_options == ["$1,000", "$2,000"]
        # No second (narration) call for a clarifying question.
        assert calls["n"] == 1


def test_decline_out_of_scope() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        client = CopilotClient(api_key="fake-key")

        def fake_call(**kwargs):
            return _response(
                _tool_use_block(
                    "tool_1",
                    "decline_out_of_scope",
                    {
                        "reason": (
                            "I can only help with your Discero finances."
                        ),
                        "category": "non_financial",
                    },
                )
            )

        client.call = fake_call  # type: ignore[method-assign]

        result = run_copilot_turn(
            db,
            user.id,
            user,
            _user_message("What's the weather today?"),
            client,
            as_of=TEST_DATE,
        )

        assert result.kind == "out_of_scope"
        assert "Discero" in (result.answer or "")


def test_text_only_response_without_tool_use() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        client = CopilotClient(api_key="fake-key")

        def fake_call(**kwargs):
            return _response(_text_block("Hi! Ask me about your finances."))

        client.call = fake_call  # type: ignore[method-assign]

        result = run_copilot_turn(
            db,
            user.id,
            user,
            _user_message("hello"),
            client,
            as_of=TEST_DATE,
        )

        assert result.kind == "answer"
        assert result.answer == "Hi! Ask me about your finances."
        assert result.key_numbers == []


def test_invalid_tool_input_becomes_clarifying_question() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        client = CopilotClient(api_key="fake-key")

        def fake_call(**kwargs):
            # Missing required purchase_amount_cents/purchase_date.
            return _response(
                _tool_use_block(
                    "tool_1",
                    "simulate_major_purchase",
                    {"purchase_name": "Laptop"},
                )
            )

        client.call = fake_call  # type: ignore[method-assign]

        result = run_copilot_turn(
            db,
            user.id,
            user,
            _user_message("Can I afford a laptop?"),
            client,
            as_of=TEST_DATE,
        )

        assert result.kind == "clarifying_question"


def test_goal_conflict_defaults_capacity_from_real_income() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=500_000)
        create_goal(
            db,
            user,
            name="Emergency fund",
            target_cents=1_000_000,
            saved_cents=0,
            target_date=date(2026, 12, 31),
        )

        client = CopilotClient(api_key="fake-key")

        def fake_call(**kwargs):
            tools = kwargs.get("tools") or []
            if any(t.get("name") == "present_financial_answer" for t in tools):
                return _response(
                    _tool_use_block(
                        "tool_2",
                        "present_financial_answer",
                        {"answer": "Here's where your goals stand."},
                    )
                )
            return _response(
                _tool_use_block(
                    "tool_1", "check_goal_conflicts", {}
                )
            )

        client.call = fake_call  # type: ignore[method-assign]

        result = run_copilot_turn(
            db,
            user.id,
            user,
            _user_message("Which goal is at risk?"),
            client,
            as_of=TEST_DATE,
        )

        assert result.kind == "answer"
        assert result.tool_used == "Goal Conflict Check"
        assert any(c.label == "Status" for c in result.key_numbers)


def test_goal_intelligence_ai_enhanced_labels_auto_derived_capacity() -> (
    None
):
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=500_000)
        create_goal(
            db,
            user,
            name="Emergency fund",
            target_cents=1_000_000,
            saved_cents=0,
            target_date=date(2026, 12, 31),
        )

        client = CopilotClient(api_key="fake-key")

        def fake_call(**kwargs):
            tools = kwargs.get("tools") or []
            if any(t.get("name") == "present_financial_answer" for t in tools):
                return _response(
                    _tool_use_block(
                        "tool_2",
                        "present_financial_answer",
                        {"answer": "Emergency fund is your most urgent goal."},
                    )
                )
            # Claude omits monthly_capacity_cents -- it was not stated.
            return _response(
                _tool_use_block("tool_1", "get_goal_intelligence", {})
            )

        client.call = fake_call  # type: ignore[method-assign]

        result = run_copilot_turn(
            db,
            user.id,
            user,
            _user_message("Which goal is most urgent?"),
            client,
            as_of=TEST_DATE,
        )

        assert result.kind == "answer"
        assert result.tool_used == "Goal Intelligence"
        source_chip = next(
            c for c in result.key_numbers if c.label == "Capacity source"
        )
        assert source_chip.value_display == "Estimated"
        assert result.low_data_warning is not None
        assert "estimated from your recent financial data" in (
            result.low_data_warning
        )


def test_goal_intelligence_ai_enhanced_labels_explicit_capacity() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=500_000)
        create_goal(
            db,
            user,
            name="Emergency fund",
            target_cents=1_000_000,
            saved_cents=0,
            target_date=date(2026, 12, 31),
        )

        client = CopilotClient(api_key="fake-key")

        def fake_call(**kwargs):
            tools = kwargs.get("tools") or []
            if any(t.get("name") == "present_financial_answer" for t in tools):
                return _response(
                    _tool_use_block(
                        "tool_2",
                        "present_financial_answer",
                        {"answer": "Emergency fund is your most urgent goal."},
                    )
                )
            # Claude passes through the user's stated $500/month.
            return _response(
                _tool_use_block(
                    "tool_1",
                    "get_goal_intelligence",
                    {"monthly_capacity_cents": 50_000},
                )
            )

        client.call = fake_call  # type: ignore[method-assign]

        result = run_copilot_turn(
            db,
            user.id,
            user,
            _user_message("I can save $500/month. Which goal is most urgent?"),
            client,
            as_of=TEST_DATE,
        )

        assert result.kind == "answer"
        source_chip = next(
            c for c in result.key_numbers if c.label == "Capacity source"
        )
        assert source_chip.value_display == "Your stated amount"
        assert "estimated" not in (result.low_data_warning or "").lower()


def test_financial_resilience_ai_enhanced_labels_derived_essential_spending() -> (
    None
):
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=500_000)
        for month in (5, 6, 7):
            db.add(
                Transaction(
                    user_id=user.id,
                    posted_on=date(2026, month, 15),
                    description="Rent",
                    amount_cents=-100_000,
                    category="Housing",
                )
            )
        db.commit()

        client = CopilotClient(api_key="fake-key")

        def fake_call(**kwargs):
            tools = kwargs.get("tools") or []
            if any(t.get("name") == "present_financial_answer" for t in tools):
                return _response(
                    _tool_use_block(
                        "tool_2",
                        "present_financial_answer",
                        {"answer": "Your runway is about 5 months."},
                    )
                )
            # Claude omits essential_spending_cents -- not stated.
            return _response(
                _tool_use_block(
                    "tool_1", "get_financial_resilience", {}
                )
            )

        client.call = fake_call  # type: ignore[method-assign]

        result = run_copilot_turn(
            db,
            user.id,
            user,
            _user_message("What is my emergency runway?"),
            client,
            as_of=TEST_DATE,
        )

        assert result.kind == "answer"
        assert result.tool_used == "Financial Resilience"
        source_chip = next(
            c
            for c in result.key_numbers
            if c.label == "Spending source"
        )
        assert source_chip.value_display == "Estimated"
        assert result.low_data_warning is not None
        assert "Monthly spending baseline" in result.low_data_warning
        assert (
            "does not yet classify essential vs. discretionary "
            "expenses" in result.low_data_warning
        )


def test_financial_resilience_ai_enhanced_labels_explicit_essential_spending() -> (
    None
):
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=500_000)

        client = CopilotClient(api_key="fake-key")

        def fake_call(**kwargs):
            tools = kwargs.get("tools") or []
            if any(t.get("name") == "present_financial_answer" for t in tools):
                return _response(
                    _tool_use_block(
                        "tool_2",
                        "present_financial_answer",
                        {"answer": "Your runway is about 1.25 months."},
                    )
                )
            # Claude passes through the user's stated $4,000/month.
            return _response(
                _tool_use_block(
                    "tool_1",
                    "get_financial_resilience",
                    {"essential_spending_cents": 400_000},
                )
            )

        client.call = fake_call  # type: ignore[method-assign]

        result = run_copilot_turn(
            db,
            user.id,
            user,
            _user_message(
                "What if my essential spending were $4000 per month?"
            ),
            client,
            as_of=TEST_DATE,
        )

        assert result.kind == "answer"
        source_chip = next(
            c
            for c in result.key_numbers
            if c.label == "Spending source"
        )
        assert source_chip.value_display == "Your stated amount"
        assert "estimated" not in (result.low_data_warning or "").lower()


def test_recurring_intelligence_tool_grounds_chips_in_real_calculation() -> (
    None
):
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=500_000)
        create_recurring_item(
            db,
            user,
            merchant="Rent",
            amount_cents=150_000,
            next_payment=date(2026, 8, 20),
        )

        client = CopilotClient(api_key="fake-key")
        calls = {"n": 0}

        def fake_call(**kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return _response(
                    _tool_use_block(
                        "tool_1", "get_recurring_intelligence", {}
                    )
                )
            return _response(
                _tool_use_block(
                    "tool_2",
                    "present_financial_answer",
                    {
                        "answer": "You have one active recurring bill.",
                    },
                )
            )

        client.call = fake_call  # type: ignore[method-assign]

        result = run_copilot_turn(
            db,
            user.id,
            user,
            _user_message("What changed in my recurring bills?"),
            client,
            as_of=TEST_DATE,
        )

        assert result.kind == "answer"
        assert result.tool_used == "Recurring Intelligence"
        monthly_chip = next(
            c for c in result.key_numbers if c.label == "Monthly recurring"
        )
        assert monthly_chip.value_display == "$1,500.00"
        assert calls["n"] == 2


def test_spending_anomalies_tool_grounds_chips_in_real_calculation() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=500_000)

        client = CopilotClient(api_key="fake-key")
        calls = {"n": 0}

        def fake_call(**kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return _response(
                    _tool_use_block("tool_1", "get_spending_anomalies", {})
                )
            return _response(
                _tool_use_block(
                    "tool_2",
                    "present_financial_answer",
                    {"answer": "Nothing unusual stood out."},
                )
            )

        client.call = fake_call  # type: ignore[method-assign]

        result = run_copilot_turn(
            db,
            user.id,
            user,
            _user_message("Did I spend unusually this month?"),
            client,
            as_of=TEST_DATE,
        )

        assert result.kind == "answer"
        assert result.tool_used == "Spending Anomalies"
        anomalies_chip = next(
            c for c in result.key_numbers if c.label == "Anomalies found"
        )
        assert anomalies_chip.value_display == "0"
        assert calls["n"] == 2


def test_spending_anomalies_key_cards_do_not_repeat_the_same_signal() -> (
    None
):
    # Production regression: a merchant charging near-daily (e.g. a
    # broken retry loop) produces several genuinely DISTINCT
    # repeated-charge clusters (different transaction ids/dates) that
    # all share the same title/merchant/amount. The full signal list
    # may legitimately contain all of them, but Copilot's key cards
    # must not show the same-looking signal more than once.
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=500_000)

        for i in range(10):
            db.add(
                Transaction(
                    user_id=user.id,
                    posted_on=date(2026, 7, 25) + timedelta(days=i),
                    description="Fun",
                    merchant_name="Fun",
                    amount_cents=-8_940,
                    category="Entertainment",
                )
            )
        db.commit()

        client = CopilotClient(api_key="fake-key")
        calls = {"n": 0}

        def fake_call(**kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return _response(
                    _tool_use_block("tool_1", "get_spending_anomalies", {})
                )
            return _response(
                _tool_use_block(
                    "tool_2",
                    "present_financial_answer",
                    {"answer": "Found some repeated charges."},
                )
            )

        client.call = fake_call  # type: ignore[method-assign]

        result = run_copilot_turn(
            db,
            user.id,
            user,
            _user_message("What spending looks unusual?"),
            client,
            as_of=TEST_DATE,
        )

        assert result.kind == "answer"
        # Several distinct repeated-charge clusters really do exist
        # (>1) -- the raw count is real, not itself the bug.
        anomalies_chip = next(
            c for c in result.key_numbers if c.label == "Anomalies found"
        )
        assert int(anomalies_chip.value_display) > 1

        signal_titles = [
            c.label for c in result.key_numbers if c.label != "Anomalies found"
        ]
        assert len(signal_titles) == len(set(signal_titles))
