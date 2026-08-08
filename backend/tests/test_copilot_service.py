from datetime import date
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models import FinancialAccount, PlaidItem, SavingsGoal, User
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
                            "I can only help with your FinSight finances."
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
        assert "FinSight" in (result.answer or "")


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
