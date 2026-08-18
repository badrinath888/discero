from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DecisionOutcome, FinancialAccount, SavedDecision, User
from app.schemas import SaveDecisionRequest
from app.services import decision_history_service, decision_portfolio_service
from app.services.decision_portfolio_service import (
    DecisionPortfolioNotFoundError,
    DecisionPortfolioValidationError,
)
from tests.conftest import TestingSessionLocal
from tests.test_decisions import register_and_login
from tests.test_safe_to_spend import (
    create_account,
    create_goal,
    create_income_transaction,
    create_user,
)

TEST_DATE = date(2026, 8, 8)


def _major_purchase_input(
    amount_cents: int,
    *,
    purchase_date: date = TEST_DATE,
    **overrides,
) -> dict:
    data = {
        "purchase_name": "Purchase",
        "purchase_amount_cents": amount_cents,
        "purchase_date": purchase_date.isoformat(),
    }
    data.update(overrides)
    return data


def _what_if_one_time_input(
    amount_cents: int,
    *,
    effective_date: date,
    **overrides,
) -> dict:
    data = {
        "scenario_type": "one_time_expense",
        "scenario_name": "Scenario",
        "amount_cents": amount_cents,
        "effective_date": effective_date.isoformat(),
    }
    data.update(overrides)
    return data


def _what_if_monthly_expense_input(change_cents: int, **overrides) -> dict:
    data = {
        "scenario_type": "monthly_expense_change",
        "scenario_name": "Expense change",
        "monthly_amount_change_cents": change_cents,
    }
    data.update(overrides)
    return data


def _stress_test_input() -> dict:
    return {
        "scenario_type": "emergency_expense",
        "scenario_name": "Car repair",
        "stress_amount_cents": 100_000,
        "event_date": TEST_DATE.isoformat(),
    }


def _buy_now_vs_wait_input() -> dict:
    return {
        "purchase_name": "Laptop",
        "purchase_amount_cents": 150_000,
        "buy_now_date": TEST_DATE.isoformat(),
        "wait_until_date": (TEST_DATE + timedelta(days=30)).isoformat(),
    }


def _scenario_comparison_input() -> dict:
    return {
        "option_a": _major_purchase_input(150_000),
        "option_b": _major_purchase_input(300_000),
    }


def _save(
    db: Session,
    user,
    decision_type: str,
    title: str,
    input_dict: dict,
    *,
    as_of: date = TEST_DATE,
    status: str = "saved",
) -> SavedDecision:
    decision = decision_history_service.save_decision(
        db,
        user.id,
        SaveDecisionRequest(
            decision_type=decision_type, title=title, input=input_dict
        ),
        as_of=as_of,
    )

    if status != "saved":
        decision_history_service.update_decision_status(
            db, user.id, decision.id, status
        )
        db.refresh(decision)

    return decision


# --- Request validation --------------------------------------------------


def test_portfolio_rejects_fewer_than_two_decisions() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)

        try:
            decision_portfolio_service.evaluate_decision_portfolio(
                db, user.id, [1]
            )
            assert False, "expected DecisionPortfolioValidationError"
        except DecisionPortfolioValidationError as exc:
            assert exc.details["reason"] == "invalid_selection_count"


def test_portfolio_rejects_more_than_five_decisions() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)

        try:
            decision_portfolio_service.evaluate_decision_portfolio(
                db, user.id, [1, 2, 3, 4, 5, 6]
            )
            assert False, "expected DecisionPortfolioValidationError"
        except DecisionPortfolioValidationError as exc:
            assert exc.details["reason"] == "invalid_selection_count"


def test_portfolio_rejects_duplicate_decision_ids() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)

        try:
            decision_portfolio_service.evaluate_decision_portfolio(
                db, user.id, [1, 1]
            )
            assert False, "expected DecisionPortfolioValidationError"
        except DecisionPortfolioValidationError as exc:
            assert exc.details["reason"] == "duplicate_decision_ids"
            assert exc.details["duplicate_decision_ids"] == [1]


# --- Security --------------------------------------------------------------


def test_portfolio_excludes_cross_user_decision() -> None:
    with TestingSessionLocal() as db:
        owner = create_user(db, "portfolio-owner")
        other = create_user(db, "portfolio-other")
        create_account(db, owner, available_balance_cents=5_000_000)

        mine = _save(
            db, owner, "major_purchase", "Mine", _major_purchase_input(100_000)
        )
        theirs = _save(
            db,
            other,
            "major_purchase",
            "Theirs",
            _major_purchase_input(100_000),
        )

        try:
            decision_portfolio_service.evaluate_decision_portfolio(
                db, owner.id, [mine.id, theirs.id]
            )
            assert False, "expected DecisionPortfolioNotFoundError"
        except DecisionPortfolioNotFoundError as exc:
            assert exc.missing_decision_ids == [theirs.id]


def test_portfolio_missing_decision_handled_safely() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=5_000_000)

        mine = _save(
            db, user, "major_purchase", "Mine", _major_purchase_input(100_000)
        )

        try:
            decision_portfolio_service.evaluate_decision_portfolio(
                db, user.id, [mine.id, 999_999]
            )
            assert False, "expected DecisionPortfolioNotFoundError"
        except DecisionPortfolioNotFoundError as exc:
            assert exc.missing_decision_ids == [999_999]


# --- Lifecycle ---------------------------------------------------------


def test_portfolio_rejects_dismissed_decision() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=5_000_000)

        active = _save(
            db,
            user,
            "major_purchase",
            "Active",
            _major_purchase_input(100_000),
        )
        dismissed = _save(
            db,
            user,
            "major_purchase",
            "Dismissed",
            _major_purchase_input(200_000),
            status="dismissed",
        )

        try:
            decision_portfolio_service.evaluate_decision_portfolio(
                db, user.id, [active.id, dismissed.id]
            )
            assert False, "expected DecisionPortfolioValidationError"
        except DecisionPortfolioValidationError as exc:
            assert exc.details["reason"] == "incompatible_decisions"
            incompatible = exc.details["incompatible_decisions"]
            assert incompatible == [
                {
                    "decision_id": dismissed.id,
                    "decision_type": "major_purchase",
                    "reason": "dismissed",
                }
            ]


def test_portfolio_accepts_saved_and_acted_on_decisions() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=5_000_000)

        saved = _save(
            db, user, "major_purchase", "Saved", _major_purchase_input(100_000)
        )
        acted_on = _save(
            db,
            user,
            "what_if",
            "Acted on",
            _what_if_one_time_input(
                50_000, effective_date=TEST_DATE + timedelta(days=5)
            ),
            status="acted_on",
        )

        result = decision_portfolio_service.evaluate_decision_portfolio(
            db, user.id, [saved.id, acted_on.id], as_of=TEST_DATE
        )

        assert {d.decision_id for d in result.selected_decisions} == {
            saved.id,
            acted_on.id,
        }


# --- Compatibility -------------------------------------------------------


def test_portfolio_accepts_major_purchase_and_what_if() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=5_000_000)

        purchase = _save(
            db,
            user,
            "major_purchase",
            "Purchase",
            _major_purchase_input(500_000),
        )
        what_if = _save(
            db,
            user,
            "what_if",
            "What if",
            _what_if_one_time_input(
                200_000, effective_date=TEST_DATE + timedelta(days=5)
            ),
        )

        result = decision_portfolio_service.evaluate_decision_portfolio(
            db, user.id, [purchase.id, what_if.id], as_of=TEST_DATE
        )

        assert result.combined.safe_to_spend_cents == 5_000_000 - 700_000


def _assert_rejects_unsupported_type(
    db: Session, user, decision_type: str, input_dict: dict
) -> None:
    compatible = _save(
        db,
        user,
        "major_purchase",
        "Compatible",
        _major_purchase_input(100_000),
    )
    unsupported = _save(db, user, decision_type, "Unsupported", input_dict)

    try:
        decision_portfolio_service.evaluate_decision_portfolio(
            db, user.id, [compatible.id, unsupported.id]
        )
        assert False, "expected DecisionPortfolioValidationError"
    except DecisionPortfolioValidationError as exc:
        assert exc.details["reason"] == "incompatible_decisions"
        incompatible = exc.details["incompatible_decisions"]
        assert incompatible == [
            {
                "decision_id": unsupported.id,
                "decision_type": decision_type,
                "reason": "unsupported_type",
            }
        ]


def test_portfolio_rejects_stress_test_type() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=5_000_000)
        _assert_rejects_unsupported_type(
            db, user, "stress_test", _stress_test_input()
        )


def test_portfolio_rejects_buy_now_vs_wait_type() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=5_000_000)
        _assert_rejects_unsupported_type(
            db, user, "buy_now_vs_wait", _buy_now_vs_wait_input()
        )


def test_portfolio_rejects_scenario_comparison_type() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=5_000_000)
        _assert_rejects_unsupported_type(
            db,
            user,
            "scenario_comparison",
            _scenario_comparison_input(),
        )


# --- Calculation -----------------------------------------------------------


def test_portfolio_combines_two_major_purchases_against_one_baseline() -> (
    None
):
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=10_000_000)

        first = _save(
            db,
            user,
            "major_purchase",
            "First",
            _major_purchase_input(6_000_000),
        )
        second = _save(
            db,
            user,
            "major_purchase",
            "Second",
            _major_purchase_input(2_000_000),
        )

        result = decision_portfolio_service.evaluate_decision_portfolio(
            db, user.id, [first.id, second.id], as_of=TEST_DATE
        )

        assert result.baseline.safe_to_spend_cents == 10_000_000
        assert result.combined.safe_to_spend_cents == 2_000_000

        # Never simply composed from each decision's own independently
        # calculated result_snapshot: each of those was computed
        # against the FULL baseline on its own, so summing them would
        # double count the shared liquid balance.
        naive_wrong_total = (
            first.result_snapshot["safe_to_spend_after_purchase_cents"]
            + second.result_snapshot["safe_to_spend_after_purchase_cents"]
        )
        assert naive_wrong_total == 12_000_000
        assert result.combined.safe_to_spend_cents != naive_wrong_total


def test_portfolio_combines_major_purchase_and_what_if() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=10_000_000)

        purchase = _save(
            db,
            user,
            "major_purchase",
            "Purchase",
            _major_purchase_input(4_000_000),
        )
        what_if = _save(
            db,
            user,
            "what_if",
            "What if",
            _what_if_one_time_input(
                1_000_000, effective_date=TEST_DATE + timedelta(days=5)
            ),
        )

        result = decision_portfolio_service.evaluate_decision_portfolio(
            db, user.id, [purchase.id, what_if.id], as_of=TEST_DATE
        )

        assert result.combined.safe_to_spend_cents == 5_000_000


def test_portfolio_reflects_current_financial_data_changes() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        account = create_account(
            db, user, available_balance_cents=10_000_000
        )

        purchase = _save(
            db,
            user,
            "major_purchase",
            "Purchase",
            _major_purchase_input(2_000_000),
        )
        what_if = _save(
            db,
            user,
            "what_if",
            "What if",
            _what_if_one_time_input(
                1_000_000, effective_date=TEST_DATE + timedelta(days=5)
            ),
        )

        before = decision_portfolio_service.evaluate_decision_portfolio(
            db, user.id, [purchase.id, what_if.id], as_of=TEST_DATE
        )
        assert before.baseline.safe_to_spend_cents == 10_000_000

        stored_account = db.get(FinancialAccount, account.id)
        stored_account.available_balance_cents = 4_000_000
        stored_account.current_balance_cents = 4_000_000
        db.commit()

        after = decision_portfolio_service.evaluate_decision_portfolio(
            db, user.id, [purchase.id, what_if.id], as_of=TEST_DATE
        )
        assert after.baseline.safe_to_spend_cents == 4_000_000
        assert after.combined.safe_to_spend_cents == 1_000_000


def test_portfolio_leaves_saved_decision_result_snapshot_unchanged() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=10_000_000)

        first = _save(
            db,
            user,
            "major_purchase",
            "First",
            _major_purchase_input(1_000_000),
        )
        second = _save(
            db,
            user,
            "what_if",
            "Second",
            _what_if_one_time_input(
                500_000, effective_date=TEST_DATE + timedelta(days=5)
            ),
        )

        original_first = dict(first.result_snapshot)
        original_second = dict(second.result_snapshot)

        decision_portfolio_service.evaluate_decision_portfolio(
            db, user.id, [first.id, second.id], as_of=TEST_DATE
        )

        reloaded_first = db.get(SavedDecision, first.id)
        reloaded_second = db.get(SavedDecision, second.id)

        assert reloaded_first.result_snapshot == original_first
        assert reloaded_second.result_snapshot == original_second


def test_portfolio_creates_no_decision_outcomes() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=10_000_000)

        first = _save(
            db,
            user,
            "major_purchase",
            "First",
            _major_purchase_input(1_000_000),
        )
        second = _save(
            db,
            user,
            "major_purchase",
            "Second",
            _major_purchase_input(500_000),
        )

        decision_portfolio_service.evaluate_decision_portfolio(
            db, user.id, [first.id, second.id], as_of=TEST_DATE
        )

        outcomes = db.scalars(select(DecisionOutcome)).all()
        assert list(outcomes) == []


# --- Impact ranking --------------------------------------------------------


def test_portfolio_ranks_most_negative_impact_first() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=20_000_000)

        small = _save(
            db, user, "major_purchase", "Small", _major_purchase_input(500_000)
        )
        large = _save(
            db,
            user,
            "major_purchase",
            "Large",
            _major_purchase_input(3_000_000),
        )
        medium = _save(
            db,
            user,
            "major_purchase",
            "Medium",
            _major_purchase_input(1_000_000),
        )

        result = decision_portfolio_service.evaluate_decision_portfolio(
            db, user.id, [small.id, large.id, medium.id], as_of=TEST_DATE
        )

        impacts = result.decision_impacts
        assert [impact.decision_id for impact in impacts] == [
            large.id,
            medium.id,
            small.id,
        ]
        assert [impact.risk_rank for impact in impacts] == [1, 2, 3]
        assert impacts[0].incremental_safe_to_spend_impact_cents == -3_000_000
        assert impacts[0].contribution_level == "high"


def test_portfolio_ranks_ties_by_decision_id_ascending() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=10_000_000)

        first = _save(
            db,
            user,
            "major_purchase",
            "First",
            _major_purchase_input(1_000_000),
        )
        second = _save(
            db,
            user,
            "major_purchase",
            "Second",
            _major_purchase_input(1_000_000),
        )

        assert first.id < second.id

        result = decision_portfolio_service.evaluate_decision_portfolio(
            db, user.id, [second.id, first.id], as_of=TEST_DATE
        )

        impacts = result.decision_impacts
        assert (
            impacts[0].incremental_safe_to_spend_impact_cents
            == impacts[1].incremental_safe_to_spend_impact_cents
        )
        assert impacts[0].decision_id == first.id
        assert impacts[1].decision_id == second.id
        assert impacts[0].risk_rank == 1
        assert impacts[1].risk_rank == 2


# --- Goals -----------------------------------------------------------------


def test_portfolio_surfaces_goal_impact_and_conflict() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=5_000_000)

        for month in (5, 6, 7):
            create_income_transaction(
                db,
                user,
                posted_on=date(2026, month, 15),
                amount_cents=500_000,
            )

        create_goal(
            db,
            user,
            target_cents=6_000_000,
            saved_cents=0,
            target_date=date(2027, 8, 8),
        )

        expense_change = _save(
            db,
            user,
            "what_if",
            "More monthly expenses",
            _what_if_monthly_expense_input(300_000),
        )
        purchase = _save(
            db,
            user,
            "major_purchase",
            "Purchase",
            _major_purchase_input(1_000_000),
        )

        result = decision_portfolio_service.evaluate_decision_portfolio(
            db,
            user.id,
            [expense_change.id, purchase.id],
            as_of=TEST_DATE,
        )

        assert len(result.goal_impacts) == 1
        goal_impact = result.goal_impacts[0]
        assert goal_impact.status == "at_risk"
        assert goal_impact.funding_shortfall_cents == 3_600_000
        assert goal_impact.current_required_monthly_contribution_cents == (
            500_000
        )

        assert result.conflicts.conflict_status == "conflict"
        assert result.conflicts.monthly_shortfall_cents == 300_000


# --- Legacy / corrupt input --------------------------------------------


def test_portfolio_corrupt_persisted_input_fails_safely() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=5_000_000)

        good = _save(
            db,
            user,
            "major_purchase",
            "Good",
            _major_purchase_input(500_000),
        )
        corrupted = _save(
            db,
            user,
            "major_purchase",
            "Corrupted",
            _major_purchase_input(500_000),
        )

        # Simulate a corrupted/legacy input_snapshot that no longer
        # matches the request schema for this decision type.
        corrupted.input_snapshot = {"purchase_name": "Laptop"}
        db.commit()

        try:
            decision_portfolio_service.evaluate_decision_portfolio(
                db, user.id, [good.id, corrupted.id], as_of=TEST_DATE
            )
            assert False, "expected DecisionPortfolioValidationError"
        except DecisionPortfolioValidationError as exc:
            assert exc.details["reason"] == "invalid_persisted_input"
            assert exc.details["decision_id"] == corrupted.id

        outcomes = db.scalars(select(DecisionOutcome)).all()
        assert list(outcomes) == []


# --- HTTP / authorization ---------------------------------------------


def test_portfolio_endpoint_requires_authentication(client: TestClient) -> None:
    response = client.post(
        "/users/9999/decisions/portfolio",
        json={"decision_ids": [1, 2]},
    )
    assert response.status_code == 401


def test_portfolio_endpoint_blocks_other_user(client: TestClient) -> None:
    user_id, headers = register_and_login(client, "portfolio-owner")

    response = client.post(
        f"/users/{user_id + 1}/decisions/portfolio",
        headers=headers,
        json={"decision_ids": [1, 2]},
    )

    assert response.status_code == 403


def test_portfolio_endpoint_full_http_lifecycle(client: TestClient) -> None:
    user_id, headers = register_and_login(client, "portfolio-http")

    with TestingSessionLocal() as db:
        user = db.get(User, user_id)
        create_account(db, user, available_balance_cents=10_000_000)

    today = date.today()

    first_response = client.post(
        f"/users/{user_id}/decisions",
        headers=headers,
        json={
            "decision_type": "major_purchase",
            "title": "Laptop",
            "input": _major_purchase_input(2_000_000, purchase_date=today),
        },
    )
    assert first_response.status_code == 201
    first_id = first_response.json()["id"]

    second_response = client.post(
        f"/users/{user_id}/decisions",
        headers=headers,
        json={
            "decision_type": "what_if",
            "title": "Rent increase",
            "input": _what_if_one_time_input(
                1_000_000, effective_date=today + timedelta(days=5)
            ),
        },
    )
    assert second_response.status_code == 201
    second_id = second_response.json()["id"]

    portfolio_response = client.post(
        f"/users/{user_id}/decisions/portfolio",
        headers=headers,
        json={"decision_ids": [first_id, second_id]},
    )

    assert portfolio_response.status_code == 200
    body = portfolio_response.json()
    assert body["combined"]["safe_to_spend_cents"] == 10_000_000 - 3_000_000
    assert len(body["selected_decisions"]) == 2
    assert len(body["decision_impacts"]) == 2


def test_portfolio_endpoint_rejects_invalid_selection_count(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "portfolio-bad-count")

    response = client.post(
        f"/users/{user_id}/decisions/portfolio",
        headers=headers,
        json={"decision_ids": [1]},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "invalid_selection_count"


def test_portfolio_endpoint_rejects_missing_decision(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "portfolio-missing")

    response = client.post(
        f"/users/{user_id}/decisions/portfolio",
        headers=headers,
        json={"decision_ids": [123, 456]},
    )

    assert response.status_code == 404
