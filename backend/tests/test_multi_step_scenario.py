from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.models import SavedDecision
from app.schemas import MultiStepScenarioPlanRequest, MultiStepScenarioStepRequest
from app.services import multi_step_scenario_service
from app.services.multi_step_scenario_service import (
    MultiStepScenarioValidationError,
    evaluate_multi_step_scenario_plan,
)
from tests.conftest import TestingSessionLocal, test_engine
from tests.test_safe_to_spend import (
    create_account,
    create_goal,
    create_income_transaction,
    create_user,
)
from tests.test_decisions import register_and_login

TEST_DATE = date(2026, 8, 20)


def _step(step_type: str, label: str, effective_date: date, **kwargs) -> MultiStepScenarioStepRequest:
    return MultiStepScenarioStepRequest(
        step_type=step_type,
        label=label,
        effective_date=effective_date,
        **kwargs,
    )


def _step_json(step_type: str, label: str, effective_date: date, **kwargs) -> dict:
    data = {
        "step_type": step_type,
        "label": label,
        "effective_date": effective_date.isoformat(),
    }
    data.update(kwargs)
    return data


def _plan(steps, **kwargs) -> MultiStepScenarioPlanRequest:
    defaults = {
        "horizon_days": 90,
        "safety_reserve_cents": 0,
        "essential_spending_cents": 0,
    }
    defaults.update(kwargs)
    return MultiStepScenarioPlanRequest(steps=steps, **defaults)


# --- Validation ------------------------------------------------------------


def test_rejects_fewer_than_two_steps() -> None:
    try:
        _plan([_step("one_time_expense", "Laptop", TEST_DATE, amount_cents=1000)])
        assert False, "expected a validation error"
    except Exception as exc:
        assert "at least 2" in str(exc) or "2" in str(exc)


def test_rejects_more_than_five_steps() -> None:
    steps = [
        _step(
            "one_time_expense",
            f"Expense {i}",
            TEST_DATE + timedelta(days=i),
            amount_cents=1000,
        )
        for i in range(6)
    ]
    try:
        _plan(steps)
        assert False, "expected a validation error"
    except Exception as exc:
        assert "5" in str(exc)


def test_rejects_invalid_horizon() -> None:
    steps = [
        _step("one_time_expense", "A", TEST_DATE, amount_cents=1000),
        _step("one_time_expense", "B", TEST_DATE, amount_cents=1000),
    ]
    try:
        _plan(steps, horizon_days=200)
        assert False, "expected a validation error"
    except Exception:
        pass


def test_rejects_invalid_amount() -> None:
    try:
        _step("one_time_expense", "A", TEST_DATE, amount_cents=0)
        assert False, "expected a validation error"
    except Exception:
        pass


def test_rejects_missing_duration_for_temporary_income_loss() -> None:
    try:
        _step(
            "temporary_income_loss",
            "Loss",
            TEST_DATE,
            monthly_income_loss_cents=100_000,
        )
        assert False, "expected a validation error"
    except Exception as exc:
        assert "duration_months" in str(exc)


def test_rejects_duration_where_irrelevant() -> None:
    try:
        _step(
            "one_time_expense",
            "A",
            TEST_DATE,
            amount_cents=1000,
            duration_months=2,
        )
        assert False, "expected a validation error"
    except Exception:
        pass


def test_unsupported_step_type_returns_structured_validation() -> None:
    try:
        _step("crypto_bet", "A", TEST_DATE, amount_cents=1000)
        assert False, "expected a validation error"
    except Exception:
        pass


def test_event_outside_horizon_rejected() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "multistep-horizon")
        create_account(db, user, available_balance_cents=500_000)

        plan = _plan(
            [
                _step("one_time_expense", "A", TEST_DATE, amount_cents=1000),
                _step(
                    "one_time_expense",
                    "Too late",
                    TEST_DATE + timedelta(days=91),
                    amount_cents=1000,
                ),
            ],
            horizon_days=90,
        )

        try:
            evaluate_multi_step_scenario_plan(
                db, user.id, plan, as_of=TEST_DATE
            )
            assert False, "expected a validation error"
        except MultiStepScenarioValidationError as exc:
            assert exc.details["reason"] == "step_date_outside_horizon"


def test_boundary_date_exactly_horizon_end_accepted() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "multistep-boundary")
        create_account(db, user, available_balance_cents=500_000)

        plan = _plan(
            [
                _step("one_time_expense", "A", TEST_DATE, amount_cents=1000),
                _step(
                    "one_time_expense",
                    "Right at the edge",
                    TEST_DATE + timedelta(days=90),
                    amount_cents=1000,
                ),
            ],
            horizon_days=90,
        )

        result = evaluate_multi_step_scenario_plan(
            db, user.id, plan, as_of=TEST_DATE
        )
        assert result.checkpoints[-1].effective_date == TEST_DATE + timedelta(
            days=90
        )


# --- Chronological ordering -------------------------------------------------


def test_chronological_sorting() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "multistep-order")
        create_account(db, user, available_balance_cents=500_000)

        plan = _plan(
            [
                _step(
                    "one_time_expense",
                    "Later",
                    TEST_DATE + timedelta(days=30),
                    amount_cents=1000,
                ),
                _step("one_time_expense", "Earlier", TEST_DATE, amount_cents=1000),
            ]
        )

        result = evaluate_multi_step_scenario_plan(
            db, user.id, plan, as_of=TEST_DATE
        )

        assert [c.label for c in result.checkpoints] == ["Earlier", "Later"]


def test_same_date_stable_ordering() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "multistep-tie")
        create_account(db, user, available_balance_cents=500_000)

        plan = _plan(
            [
                _step("one_time_expense", "First submitted", TEST_DATE, amount_cents=1000),
                _step("one_time_expense", "Second submitted", TEST_DATE, amount_cents=2000),
            ]
        )

        result = evaluate_multi_step_scenario_plan(
            db, user.id, plan, as_of=TEST_DATE
        )

        assert [c.label for c in result.checkpoints] == [
            "First submitted",
            "Second submitted",
        ]


# --- Step semantics ----------------------------------------------------------


def test_one_time_expense_applied_once() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "multistep-onetime")
        create_account(db, user, available_balance_cents=500_000)

        plan = _plan(
            [
                _step("one_time_expense", "Laptop", TEST_DATE, amount_cents=200_000),
                _step(
                    "one_time_expense",
                    "Phone",
                    TEST_DATE + timedelta(days=10),
                    amount_cents=50_000,
                ),
            ]
        )

        result = evaluate_multi_step_scenario_plan(
            db, user.id, plan, as_of=TEST_DATE
        )

        assert result.checkpoints[0].impact_cents == 200_000
        assert result.checkpoints[0].safe_to_spend_before_cents == 500_000
        assert result.checkpoints[0].safe_to_spend_after_cents == 300_000
        assert result.checkpoints[1].impact_cents == 50_000
        assert result.checkpoints[1].safe_to_spend_after_cents == 250_000


def test_recurring_change_persists_and_two_sequential_events() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "multistep-recurring")
        create_account(db, user, available_balance_cents=500_000)

        plan = _plan(
            [
                _step("one_time_expense", "Laptop", TEST_DATE, amount_cents=200_000),
                _step(
                    "monthly_expense_increase",
                    "Rent increase",
                    TEST_DATE + timedelta(days=30),
                    amount_cents=25_000,
                ),
            ],
            horizon_days=90,
        )

        result = evaluate_multi_step_scenario_plan(
            db, user.id, plan, as_of=TEST_DATE
        )

        assert result.checkpoints[0].safe_to_spend_after_cents == 300_000
        # 60 remaining days of a 90-day horizon: 25_000 * 60 / 30 = 50_000
        assert result.checkpoints[1].impact_cents == 50_000
        assert result.checkpoints[1].is_recurring is True
        assert result.checkpoints[1].safe_to_spend_after_cents == 250_000
        assert result.final_safe_to_spend_cents == 250_000
        assert result.starting_safe_to_spend_cents == 500_000


def test_temporary_effect_expires() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "multistep-temp")
        create_account(db, user, available_balance_cents=500_000)

        plan = _plan(
            [
                _step(
                    "temporary_income_loss",
                    "Income interruption",
                    TEST_DATE + timedelta(days=10),
                    monthly_income_loss_cents=60_000,
                    duration_months=1,
                ),
                _step(
                    "one_time_expense",
                    "Later purchase",
                    TEST_DATE + timedelta(days=40),
                    amount_cents=10_000,
                ),
            ],
            horizon_days=90,
        )

        result = evaluate_multi_step_scenario_plan(
            db, user.id, plan, as_of=TEST_DATE
        )

        loss_checkpoint = result.checkpoints[0]
        assert loss_checkpoint.is_temporary is True
        assert loss_checkpoint.expires_on == TEST_DATE + timedelta(days=10 + 30)
        assert loss_checkpoint.impact_cents == 60_000
        assert any(
            "ends on" in warning for warning in result.warnings
        )


def test_three_sequential_supported_events_cumulative_impact() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "multistep-three")
        create_account(db, user, available_balance_cents=500_000)

        plan = _plan(
            [
                _step("one_time_expense", "Laptop", TEST_DATE, amount_cents=200_000),
                _step(
                    "temporary_income_loss",
                    "Income interruption",
                    TEST_DATE + timedelta(days=30),
                    monthly_income_loss_cents=60_000,
                    duration_months=1,
                ),
                _step(
                    "monthly_expense_increase",
                    "Rent increase",
                    TEST_DATE + timedelta(days=60),
                    amount_cents=30_000,
                ),
            ],
            horizon_days=90,
        )

        result = evaluate_multi_step_scenario_plan(
            db, user.id, plan, as_of=TEST_DATE
        )

        assert result.checkpoints[0].safe_to_spend_after_cents == 300_000
        assert result.checkpoints[0].cumulative_impact_cents == 200_000
        assert result.checkpoints[1].safe_to_spend_after_cents == 240_000
        assert result.checkpoints[1].cumulative_impact_cents == 260_000
        assert result.checkpoints[2].safe_to_spend_after_cents == 210_000
        assert result.checkpoints[2].cumulative_impact_cents == 290_000
        assert result.final_safe_to_spend_cents == 210_000
        assert result.total_impact_cents == 210_000 - 500_000


def test_minimum_and_worst_checkpoint() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "multistep-worst")
        create_account(db, user, available_balance_cents=500_000)

        plan = _plan(
            [
                _step("one_time_expense", "Big hit", TEST_DATE, amount_cents=400_000),
                _step(
                    "one_time_expense",
                    "Small hit",
                    TEST_DATE + timedelta(days=5),
                    amount_cents=10_000,
                ),
            ]
        )

        result = evaluate_multi_step_scenario_plan(
            db, user.id, plan, as_of=TEST_DATE
        )

        assert result.minimum_safe_to_spend_cents == 90_000
        assert result.worst_checkpoint_sequence == 2
        assert result.worst_checkpoint_label == "Small hit"


def test_no_double_clamp_allows_recovery_after_shortfall() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "multistep-recover")
        create_account(db, user, available_balance_cents=100_000)

        plan = _plan(
            [
                _step("one_time_expense", "Overdraw", TEST_DATE, amount_cents=150_000),
                _step(
                    "monthly_income_increase",
                    "Raise",
                    TEST_DATE + timedelta(days=1),
                    amount_cents=200_000,
                ),
            ],
            horizon_days=90,
        )

        result = evaluate_multi_step_scenario_plan(
            db, user.id, plan, as_of=TEST_DATE
        )

        assert result.checkpoints[0].safe_to_spend_after_cents == 0
        assert result.checkpoints[0].status == "shortfall"
        # If the running total were clamped to zero after step 1 instead
        # of carried forward raw, this would incorrectly read 593_333.
        assert result.final_safe_to_spend_cents == 543_333


# --- Warnings ----------------------------------------------------------------


def test_warns_when_step_occurs_near_horizon_end() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "multistep-near-end")
        create_account(db, user, available_balance_cents=500_000)

        plan = _plan(
            [
                _step("one_time_expense", "A", TEST_DATE, amount_cents=1000),
                _step(
                    "one_time_expense",
                    "Last minute",
                    TEST_DATE + timedelta(days=88),
                    amount_cents=1000,
                ),
            ],
            horizon_days=90,
        )

        result = evaluate_multi_step_scenario_plan(
            db, user.id, plan, as_of=TEST_DATE
        )

        assert any(
            "Last minute" in warning and "final" in warning
            for warning in result.warnings
        )


def test_warns_when_temporary_loss_overlaps_recurring_change() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "multistep-overlap")
        create_account(db, user, available_balance_cents=500_000)

        plan = _plan(
            [
                _step(
                    "monthly_expense_increase",
                    "Rent increase",
                    TEST_DATE,
                    amount_cents=25_000,
                ),
                _step(
                    "temporary_income_loss",
                    "Income interruption",
                    TEST_DATE + timedelta(days=5),
                    monthly_income_loss_cents=60_000,
                    duration_months=1,
                ),
            ],
            horizon_days=90,
        )

        result = evaluate_multi_step_scenario_plan(
            db, user.id, plan, as_of=TEST_DATE
        )

        assert any(
            "overlaps" in warning and "Rent increase" in warning
            for warning in result.warnings
        )


def test_warns_on_shortfall_and_compounding_pressure() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "multistep-compound")
        create_account(db, user, available_balance_cents=100_000)

        plan = _plan(
            [
                _step("one_time_expense", "First hit", TEST_DATE, amount_cents=150_000),
                _step(
                    "one_time_expense",
                    "Second hit",
                    TEST_DATE + timedelta(days=1),
                    amount_cents=10_000,
                ),
            ]
        )

        result = evaluate_multi_step_scenario_plan(
            db, user.id, plan, as_of=TEST_DATE
        )

        assert any("shortfall" in warning for warning in result.warnings)
        assert any(
            "Second hit" in warning and "further pressure" in warning
            for warning in result.warnings
        )


# --- Goal integration ----------------------------------------------------


def test_goal_impact_integration() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "multistep-goals")
        create_account(db, user, available_balance_cents=500_000)

        for months_back in (1, 2, 3):
            create_income_transaction(
                db,
                user,
                posted_on=date(2026, 8 - months_back, 15),
                amount_cents=300_000,
            )

        create_goal(
            db,
            user,
            target_cents=1_000_000,
            target_date=TEST_DATE + timedelta(days=200),
        )

        plan = _plan(
            [
                _step(
                    "monthly_income_decrease",
                    "Reduced hours",
                    TEST_DATE,
                    amount_cents=250_000,
                ),
                _step(
                    "one_time_expense",
                    "Small purchase",
                    TEST_DATE + timedelta(days=5),
                    amount_cents=1000,
                ),
            ],
            horizon_days=90,
        )

        result = evaluate_multi_step_scenario_plan(
            db, user.id, plan, as_of=TEST_DATE
        )

        assert len(result.goal_impacts) == 1
        goal_impact = result.goal_impacts[0]
        assert (
            goal_impact.adjusted_monthly_allocation_cents
            < goal_impact.baseline_monthly_allocation_cents
        )
        assert result.goal_conflict_intelligence.supported is True


# --- Side effects / determinism ---------------------------------------------


def test_no_result_persistence() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "multistep-nopersist")
        create_account(db, user, available_balance_cents=500_000)

        before_count = db.query(SavedDecision).count()

        plan = _plan(
            [
                _step("one_time_expense", "A", TEST_DATE, amount_cents=1000),
                _step("one_time_expense", "B", TEST_DATE, amount_cents=1000),
            ]
        )
        evaluate_multi_step_scenario_plan(db, user.id, plan, as_of=TEST_DATE)

        after_count = db.query(SavedDecision).count()
        assert before_count == after_count


def test_no_mutation_of_accounts() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "multistep-nomutate")
        account = create_account(db, user, available_balance_cents=500_000)

        plan = _plan(
            [
                _step("one_time_expense", "A", TEST_DATE, amount_cents=1000),
                _step("one_time_expense", "B", TEST_DATE, amount_cents=1000),
            ]
        )
        evaluate_multi_step_scenario_plan(db, user.id, plan, as_of=TEST_DATE)

        db.refresh(account)
        assert account.available_balance_cents == 500_000


def test_deterministic_repeated_request_same_result() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "multistep-deterministic")
        create_account(db, user, available_balance_cents=500_000)

        plan = _plan(
            [
                _step("one_time_expense", "A", TEST_DATE, amount_cents=1000),
                _step(
                    "monthly_expense_increase",
                    "B",
                    TEST_DATE + timedelta(days=10),
                    amount_cents=5000,
                ),
            ]
        )

        first = evaluate_multi_step_scenario_plan(
            db, user.id, plan, as_of=TEST_DATE
        )
        second = evaluate_multi_step_scenario_plan(
            db, user.id, plan, as_of=TEST_DATE
        )

        assert first.model_dump() == second.model_dump()


def test_no_n_plus_one_query_growth_with_step_count() -> None:
    def _query_count(steps: list[MultiStepScenarioStepRequest]) -> int:
        with TestingSessionLocal() as db:
            user = create_user(db, "multistep-queries")
            create_account(db, user, available_balance_cents=500_000)

            plan = _plan(steps)
            counter = {"n": 0}

            def _count(*args, **kwargs) -> None:
                counter["n"] += 1

            event.listen(test_engine, "before_cursor_execute", _count)
            try:
                evaluate_multi_step_scenario_plan(
                    db, user.id, plan, as_of=TEST_DATE
                )
            finally:
                event.remove(test_engine, "before_cursor_execute", _count)

            return counter["n"]

    two_step_queries = _query_count(
        [
            _step("one_time_expense", "A", TEST_DATE, amount_cents=1000),
            _step("one_time_expense", "B", TEST_DATE, amount_cents=1000),
        ]
    )
    five_step_queries = _query_count(
        [
            _step(
                "one_time_expense",
                f"Step {i}",
                TEST_DATE + timedelta(days=i),
                amount_cents=1000,
            )
            for i in range(5)
        ]
    )

    assert five_step_queries == two_step_queries
    assert five_step_queries < 15


# --- HTTP endpoint -----------------------------------------------------------


def test_endpoint_requires_authentication(client: TestClient) -> None:
    response = client.post(
        "/users/9999/decisions/multi-step",
        json={"steps": []},
    )
    assert response.status_code == 401


def test_endpoint_blocks_other_user(client: TestClient) -> None:
    user_id, headers = register_and_login(client, "multistep-owner")

    response = client.post(
        f"/users/{user_id + 1}/decisions/multi-step",
        headers=headers,
        json={
            "steps": [
                _step_json("one_time_expense", "A", TEST_DATE, amount_cents=1000),
                _step_json("one_time_expense", "B", TEST_DATE, amount_cents=1000),
            ]
        },
    )
    assert response.status_code == 403


def test_endpoint_route_precedence_and_malformed_payload(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "multistep-http")

    malformed_response = client.post(
        f"/users/{user_id}/decisions/multi-step",
        headers=headers,
        json={"horizon_days": 90},
    )
    assert malformed_response.status_code == 422

    # The endpoint (unlike the service-level tests above) has no as_of
    # override, so it validates step dates against the real
    # date.today() -- anchor to that instead of the fixed TEST_DATE so
    # this stays valid across a calendar rollover between test-process
    # and server-process timezones.
    server_today = date.today()

    ok_response = client.post(
        f"/users/{user_id}/decisions/multi-step",
        headers=headers,
        json={
            "steps": [
                _step_json(
                    "one_time_expense", "A", server_today, amount_cents=1000
                ),
                _step_json(
                    "one_time_expense",
                    "B",
                    server_today + timedelta(days=1),
                    amount_cents=1000,
                ),
            ]
        },
    )
    assert ok_response.status_code == 200
    body = ok_response.json()
    assert "checkpoints" in body
    assert len(body["checkpoints"]) == 2
