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
from app.schemas import CopilotMessageIn, SafeToSpendRequest
from app.services.copilot_service import (
    CopilotClient,
    _handle_safe_to_spend,
    run_copilot_turn,
)
from app.services.safe_to_spend_service import (
    calculate_current_safe_to_spend,
    calculate_safe_to_spend,
)
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


def create_income_transaction(
    db: Session,
    user: User,
    *,
    posted_on: date,
    amount_cents: int,
) -> Transaction:
    transaction = Transaction(
        user_id=user.id,
        posted_on=posted_on,
        description="Test income",
        amount_cents=abs(amount_cents),
        category="Income",
    )
    db.add(transaction)
    db.commit()
    db.refresh(transaction)
    return transaction


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
            # The deterministic router already resolves
            # get_safe_to_spend before any provider call -- this
            # turn's one provider call is NARRATE only.
            return _response(
                _tool_use_block(
                    "tool_1",
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
        assert calls["n"] == 1


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


def test_major_purchase_baseline_matches_canonical_current_safe_to_spend() -> (
    None
):
    """Regression for the production bug where "How much can I safely
    spend right now?" and "Check if a purchase fits" -> "Laptop,
    $2,000" answered from two different Safe-to-Spend baselines in the
    same conversation, because simulate_major_purchase built its own
    SafeToSpendRequest without opting into
    include_projected_income/include_goal_reserve like
    calculate_current_safe_to_spend always does. Income and a
    goal-with-target-date are seeded specifically so the two flags are
    not a no-op -- without the fix, `before` would be strictly less
    than the canonical figure here.
    """
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=5_000_000)

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

        create_goal(
            db,
            user,
            name="Vacation",
            target_cents=600_000,
            saved_cents=0,
            target_date=date(2027, 8, 4),
        )

        canonical = calculate_current_safe_to_spend(
            db, user.id, as_of=TEST_DATE
        )

        client = CopilotClient(api_key="fake-key")
        purchase_amount_cents = 200_000

        def fake_call(**kwargs):
            tools = kwargs.get("tools") or []
            if any(
                t.get("name") == "present_financial_answer"
                for t in tools
            ):
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
                        "purchase_amount_cents": purchase_amount_cents,
                        "purchase_date": TEST_DATE.isoformat(),
                    },
                )
            )

        client.call = fake_call  # type: ignore[method-assign]

        result = run_copilot_turn(
            db,
            user.id,
            user,
            _user_message("Laptop, $2,000"),
            client,
            as_of=TEST_DATE,
        )

        assert result.kind == "answer"
        assert result.tool_used == "Major Purchase Simulator"

        after_chip = next(
            c
            for c in result.key_numbers
            if c.label == "Safe to spend after"
        )
        expected_after_cents = (
            canonical.safe_to_spend_cents - purchase_amount_cents
        )
        assert after_chip.value_display == (
            f"${expected_after_cents / 100:,.2f}"
        )

        # Same read repeated afterwards is unaffected -- simulate is a
        # pure calculation over live source data, never a deduction/
        # reservation persisted anywhere.
        replay = calculate_current_safe_to_spend(
            db, user.id, as_of=TEST_DATE
        )
        assert replay.safe_to_spend_cents == canonical.safe_to_spend_cents


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

        # Deliberately NOT a phrase the deterministic router classifies
        # (unlike "Can I afford it?", which the router now resolves to
        # its own clarification with zero provider calls) -- this
        # exercises PATH B's provider-authored clarification instead.
        result = run_copilot_turn(
            db,
            user.id,
            user,
            _user_message(
                "I'm thinking about making a fairly large purchase soon."
            ),
            client,
            as_of=TEST_DATE,
        )

        assert result.kind == "clarifying_question"
        assert result.clarifying_question == (
            "What amount are you considering?"
        )
        assert result.clarifying_options == ["$1,000", "$2,000"]
        # DECIDE is the only provider call spent -- clarification never
        # spends a second (narration) call.
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
    # tool_choice="any" means a real provider can never skip picking a
    # tool -- but orchestration must still defend against a
    # misbehaving/mocked one that does anyway. Bare prose from DECIDE is
    # never grounded in a real calculation, so it is never shown to the
    # user; the same deterministic router free mode uses decides the
    # real outcome from the actual message instead.
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

        assert result.kind == "out_of_scope"
        assert result.provenance == "deterministic"
        assert "Hi! Ask me about your finances." != result.answer


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
            # The deterministic router already resolves
            # get_recurring_intelligence before any provider call --
            # this turn's one provider call is NARRATE only.
            return _response(
                _tool_use_block(
                    "tool_1",
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
        assert calls["n"] == 1


def test_spending_anomalies_tool_grounds_chips_in_real_calculation() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=500_000)

        client = CopilotClient(api_key="fake-key")
        calls = {"n": 0}

        def fake_call(**kwargs):
            calls["n"] += 1
            # The deterministic router already resolves
            # get_spending_anomalies before any provider call -- this
            # turn's one provider call is NARRATE only.
            return _response(
                _tool_use_block(
                    "tool_1",
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
        assert calls["n"] == 1


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


def test_copilot_safe_to_spend_matches_canonical_current_calculation() -> (
    None
):
    """Regression for the production bug: Overview showed
    $32,475.90 (enriched) while Copilot showed $27,500.90 (unenriched)
    for the same user/date. With a goal and income present, Copilot's
    get_safe_to_spend chip must equal
    `calculate_current_safe_to_spend`'s own figure -- and must diverge
    from what the old unenriched-by-default calculation would have
    produced, proving this fixture would have caught the mismatch.
    """
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=500_000)
        create_goal(
            db,
            user,
            target_cents=200_000,
            target_date=date(2026, 10, 4),
        )
        create_income_transaction(
            db,
            user,
            posted_on=date(2026, 7, 15),
            amount_cents=300_000,
        )

        canonical = calculate_current_safe_to_spend(
            db,
            user.id,
            as_of=TEST_DATE,
        )
        unenriched = calculate_safe_to_spend(
            db,
            user.id,
            SafeToSpendRequest(),
            as_of=TEST_DATE,
        )

        assert canonical.safe_to_spend_cents != unenriched.safe_to_spend_cents

        client = CopilotClient(api_key=None)

        result = run_copilot_turn(
            db,
            user.id,
            user,
            _user_message("What's my safe to spend?"),
            client,
            as_of=TEST_DATE,
        )

        safe_chip = next(
            c for c in result.key_numbers if c.label == "Safe to spend"
        )
        assert safe_chip.value_display == (
            f"${canonical.safe_to_spend_cents / 100:,.2f}"
        )


def test_copilot_safe_to_spend_ignores_llm_supplied_enrichment_flags() -> (
    None
):
    """Trust boundary: the compact CopilotSafeToSpendRequest schema has
    no include_projected_income/include_goal_reserve fields, so even a
    tool_input that tries to set them (a compromised or confused LLM
    tool call) has those keys silently dropped, and
    calculate_current_safe_to_spend still forces both True.
    """
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=500_000)
        create_goal(
            db,
            user,
            target_cents=200_000,
            target_date=date(2026, 10, 4),
        )
        create_income_transaction(
            db,
            user,
            posted_on=date(2026, 7, 15),
            amount_cents=300_000,
        )

        result, _chips, _confidence, _warning = _handle_safe_to_spend(
            db,
            user.id,
            {
                "include_projected_income": False,
                "include_goal_reserve": False,
                "safety_reserve_cents": 0,
            },
            TEST_DATE,
            user,
        )

        assert result.breakdown.projected_income_cents == 300_000
        assert result.breakdown.goal_reserve_cents == 100_000


def test_copilot_safe_to_spend_honors_user_provided_assumptions() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=500_000)

        result, _chips, _confidence, _warning = _handle_safe_to_spend(
            db,
            user.id,
            {
                "safety_reserve_cents": 50_000,
                "essential_spending_cents": 25_000,
                "horizon_days": 45,
            },
            TEST_DATE,
            user,
        )

        assert result.breakdown.safety_reserve_cents == 50_000
        assert result.breakdown.essential_spending_cents == 25_000
        assert result.horizon_days == 45
