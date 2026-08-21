from datetime import date, timedelta

from sqlalchemy import event

from app.schemas import MultiStepScenarioStepRequest
from app.services.time_aware_financial_simulation_service import (
    advance_known_state_to_date,
    chronological_order,
    project_known_cashflow_delta_cents,
    resolve_step_effect,
    walk_step_timeline,
)
from tests.conftest import TestingSessionLocal, test_engine
from tests.test_buy_now_vs_wait import (
    create_account,
    create_recurring_item,
    create_user,
    seed_income,
)

TEST_DATE = date(2026, 8, 9)


def _step(step_type: str, label: str, effective_date: date, **kwargs):
    return MultiStepScenarioStepRequest(
        step_type=step_type,
        label=label,
        effective_date=effective_date,
        **kwargs,
    )


# --- chronological_order / same-date ordering -------------------------------


def test_chronological_order_sorts_by_date() -> None:
    later = _step("one_time_expense", "Later", TEST_DATE + timedelta(days=5), amount_cents=100)
    earlier = _step("one_time_expense", "Earlier", TEST_DATE, amount_cents=100)

    ordered = chronological_order([later, earlier])

    assert [step.label for step in ordered] == ["Earlier", "Later"]


def test_chronological_order_same_date_stable_tie_break() -> None:
    first = _step("one_time_expense", "First", TEST_DATE, amount_cents=100)
    second = _step("one_time_expense", "Second", TEST_DATE, amount_cents=200)

    ordered_once = chronological_order([first, second])
    ordered_again = chronological_order([first, second])

    assert [s.label for s in ordered_once] == ["First", "Second"]
    assert [s.label for s in ordered_again] == ["First", "Second"]


# --- resolve_step_effect / walk_step_timeline -------------------------------


def test_one_time_event_effect_is_flat_not_prorated() -> None:
    step = _step("one_time_expense", "Laptop", TEST_DATE, amount_cents=100_000)
    effect = resolve_step_effect(step, TEST_DATE + timedelta(days=90))

    assert effect.cost_delta_cents == 100_000
    assert effect.is_recurring is False
    assert effect.is_temporary is False
    assert effect.expires_on is None


def test_recurring_increase_effect_is_prorated_to_remaining_horizon() -> None:
    step = _step(
        "monthly_expense_increase",
        "Rent increase",
        TEST_DATE + timedelta(days=30),
        amount_cents=30_000,
    )
    effect = resolve_step_effect(step, TEST_DATE + timedelta(days=90))

    # 60 remaining days of a 30-day month convention: 30_000 * 60 / 30
    assert effect.cost_delta_cents == 60_000
    assert effect.is_recurring is True
    assert effect.monthly_capacity_delta_cents == 30_000


def test_recurring_decrease_effect_is_negative_and_prorated() -> None:
    step = _step(
        "monthly_income_increase",
        "Raise",
        TEST_DATE,
        amount_cents=50_000,
    )
    effect = resolve_step_effect(step, TEST_DATE + timedelta(days=30))

    assert effect.cost_delta_cents == -50_000
    assert effect.is_recurring is True


def test_temporary_effect_bounded_by_duration_and_reports_expiry() -> None:
    step = _step(
        "temporary_income_loss",
        "Income interruption",
        TEST_DATE,
        monthly_income_loss_cents=60_000,
        duration_months=2,
    )
    effect = resolve_step_effect(step, TEST_DATE + timedelta(days=90))

    assert effect.is_temporary is True
    assert effect.cost_delta_cents == 120_000
    assert effect.expires_on == TEST_DATE + timedelta(days=60)


def test_temporary_effect_never_bleeds_past_horizon_end() -> None:
    # Duration of 6 months requested but only 30 days remain in the
    # horizon -- the effect must be capped, never overrun the horizon.
    step = _step(
        "temporary_income_loss",
        "Income interruption",
        TEST_DATE + timedelta(days=60),
        monthly_income_loss_cents=30_000,
        duration_months=6,
    )
    effect = resolve_step_effect(step, TEST_DATE + timedelta(days=90))

    assert effect.cost_delta_cents == 30_000  # exactly 1 month remaining


def test_walk_step_timeline_worst_and_final_state_from_one_path() -> None:
    horizon_end = TEST_DATE + timedelta(days=90)
    steps = chronological_order(
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

    result = walk_step_timeline(
        steps, baseline_raw_cents=500_000, horizon_end=horizon_end
    )

    assert result.final_raw_cents == 90_000
    assert result.minimum_safe_cents == 90_000
    assert result.worst_sequence == 2
    assert result.worst_label == "Small hit"


def test_walk_step_timeline_recovery_after_shortfall_no_double_clamp() -> None:
    horizon_end = TEST_DATE + timedelta(days=90)
    steps = chronological_order(
        [
            _step("one_time_expense", "Overdraw", TEST_DATE, amount_cents=150_000),
            _step(
                "monthly_income_increase",
                "Raise",
                TEST_DATE + timedelta(days=1),
                amount_cents=200_000,
            ),
        ]
    )

    result = walk_step_timeline(
        steps, baseline_raw_cents=100_000, horizon_end=horizon_end
    )

    assert result.checkpoints[0].after_raw_cents == -50_000
    assert result.final_raw_cents == 543_333


def test_walk_step_timeline_deterministic_rerun_same_result() -> None:
    horizon_end = TEST_DATE + timedelta(days=90)
    steps = chronological_order(
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

    first = walk_step_timeline(
        steps, baseline_raw_cents=500_000, horizon_end=horizon_end
    )
    second = walk_step_timeline(
        steps, baseline_raw_cents=500_000, horizon_end=horizon_end
    )

    assert first.final_raw_cents == second.final_raw_cents
    assert first.minimum_safe_cents == second.minimum_safe_cents
    assert [c.effect for c in first.checkpoints] == [
        c.effect for c in second.checkpoints
    ]


# --- known-cashflow projection / state advance (Buy Now vs Wait) -----------


def test_project_known_cashflow_delta_counts_obligations_in_window() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "engine-cashflow-obligation")
        create_recurring_item(
            db, user, next_payment=date(2026, 8, 14), amount_cents=100_000
        )

        projection = project_known_cashflow_delta_cents(
            db, user.id, date(2026, 8, 9), date(2026, 8, 29)
        )

        assert projection.obligations_cents == 100_000
        assert projection.net_delta_cents == 100_000
        assert projection.notices


def test_project_known_cashflow_delta_counts_projected_income() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "engine-cashflow-income")
        seed_income(db, user, monthly_amount_cents=300_000)

        projection = project_known_cashflow_delta_cents(
            db, user.id, date(2026, 8, 9), date(2026, 9, 8)
        )

        assert projection.projected_income_cents > 0
        assert projection.net_delta_cents == (
            projection.obligations_cents - projection.projected_income_cents
        )


def test_project_known_cashflow_end_date_exclusive_no_double_counting() -> None:
    """An obligation landing exactly on end_date must not be counted --
    a caller evaluates end_date's own safe-to-spend window separately,
    and end_date is where that window starts.
    """
    with TestingSessionLocal() as db:
        user = create_user(db, "engine-cashflow-boundary")
        create_recurring_item(
            db, user, next_payment=date(2026, 8, 29), amount_cents=50_000
        )

        projection = project_known_cashflow_delta_cents(
            db, user.id, date(2026, 8, 9), date(2026, 8, 29)
        )

        assert projection.obligations_cents == 0


def test_project_known_cashflow_empty_window_returns_zero() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "engine-cashflow-empty")

        projection = project_known_cashflow_delta_cents(
            db, user.id, date(2026, 8, 29), date(2026, 8, 9)
        )

        assert projection.net_delta_cents == 0
        assert projection.notices == []


def test_advance_known_state_subtracts_net_obligations() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "engine-advance")
        create_recurring_item(
            db, user, next_payment=date(2026, 8, 14), amount_cents=100_000
        )

        advanced_cents, notices = advance_known_state_to_date(
            db,
            user.id,
            current_liquid_balance_cents=500_000,
            start_date=date(2026, 8, 9),
            target_date=date(2026, 8, 29),
        )

        assert advanced_cents == 400_000
        assert notices


def test_advance_known_state_bounded_query_count() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "engine-advance-queries")
        create_account(db, user, available_balance_cents=500_000)
        for offset in range(5):
            create_recurring_item(
                db,
                user,
                next_payment=date(2026, 8, 10 + offset),
                amount_cents=1_000,
            )

        counter = {"n": 0}

        def _count(*args, **kwargs) -> None:
            counter["n"] += 1

        event.listen(test_engine, "before_cursor_execute", _count)
        try:
            advance_known_state_to_date(
                db,
                user.id,
                current_liquid_balance_cents=500_000,
                start_date=date(2026, 8, 9),
                target_date=date(2026, 11, 9),
            )
        finally:
            event.remove(test_engine, "before_cursor_execute", _count)

        # One query for obligations, one for the income-average
        # transaction scan -- never one per recurring item or per day
        # in the 90-day gap window.
        assert counter["n"] <= 3
