from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    DecisionOutcome,
    FinancialAccount,
    SavedDecision,
    Transaction,
    User,
)
from app.schemas import GoalImpactOut, SaveDecisionRequest
from app.services import decision_history_service, decision_portfolio_service
from app.services.decision_goal_conflict_intelligence_service import (
    build_goal_conflict_intelligence,
)
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


def _buy_now_vs_wait_input(
    *,
    buy_now_date: date = TEST_DATE,
    wait_until_date: date | None = None,
    amount_cents: int = 150_000,
) -> dict:
    return {
        "purchase_name": "Laptop",
        "purchase_amount_cents": amount_cents,
        "buy_now_date": buy_now_date.isoformat(),
        "wait_until_date": (
            wait_until_date or (TEST_DATE + timedelta(days=30))
        ).isoformat(),
    }


def _scenario_comparison_input() -> dict:
    return {
        "option_a": _major_purchase_input(150_000),
        "option_b": _major_purchase_input(300_000),
    }


def _what_if_comparison_input(**overrides) -> dict:
    data = {
        "scenarios": [
            {
                "label": "Option A",
                "scenario_type": "one_time_expense",
                "amount_cents": 200_000,
                "effective_date": (TEST_DATE + timedelta(days=5)).isoformat(),
            },
            {
                "label": "Option B",
                "scenario_type": "one_time_expense",
                "amount_cents": 500_000,
                "effective_date": (TEST_DATE + timedelta(days=5)).isoformat(),
            },
        ]
    }
    data.update(overrides)
    return data


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


# --- Stress test -------------------------------------------------------


def test_portfolio_supports_stress_test_happy_path() -> None:
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
        stress = _save(
            db,
            user,
            "stress_test",
            "Car repair",
            _stress_test_input(),
        )

        result = decision_portfolio_service.evaluate_decision_portfolio(
            db, user.id, [purchase.id, stress.id], as_of=TEST_DATE
        )

        assert {d.decision_id for d in result.selected_decisions} == {
            purchase.id,
            stress.id,
        }
        # 5,000,000 baseline - 500,000 purchase - 100,000 stress amount.
        assert result.combined.safe_to_spend_cents == 4_400_000


def test_portfolio_stress_test_event_date_out_of_horizon_rejected() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=5_000_000)

        purchase = _save(
            db,
            user,
            "major_purchase",
            "Purchase",
            _major_purchase_input(100_000),
        )
        stress = _save(
            db,
            user,
            "stress_test",
            "Far off shock",
            _stress_test_input(),
            as_of=TEST_DATE,
        )
        # Mutate the persisted event_date directly so it is now outside
        # the shared portfolio horizon without re-triggering save-time
        # validation.
        stress.input_snapshot = {
            **stress.input_snapshot,
            "event_date": (TEST_DATE + timedelta(days=200)).isoformat(),
        }
        db.commit()

        try:
            decision_portfolio_service.evaluate_decision_portfolio(
                db, user.id, [purchase.id, stress.id], as_of=TEST_DATE
            )
            assert False, "expected DecisionPortfolioValidationError"
        except DecisionPortfolioValidationError as exc:
            assert exc.details["reason"] == "event_date_out_of_horizon"
            assert exc.details["decision_id"] == stress.id


def test_portfolio_stress_test_unresolvable_subtype_fails_safely() -> None:
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

        purchase = _save(
            db,
            user,
            "major_purchase",
            "Purchase",
            _major_purchase_input(100_000),
        )
        # Valid when saved (income history existed then).
        stress = _save(
            db,
            user,
            "stress_test",
            "Income drop",
            {
                "scenario_type": "income_reduction",
                "scenario_name": "Reduced hours",
                "income_reduction_percent": 30,
                "event_date": TEST_DATE.isoformat(),
            },
        )

        # Income history now gone (e.g. account unlinked): the derived
        # amount can no longer be computed from real data, so this must
        # fail closed at portfolio time rather than silently modeling a
        # $0 shock.
        db.query(Transaction).filter(
            Transaction.user_id == user.id
        ).delete()
        db.commit()

        try:
            decision_portfolio_service.evaluate_decision_portfolio(
                db, user.id, [purchase.id, stress.id], as_of=TEST_DATE
            )
            assert False, "expected DecisionPortfolioValidationError"
        except DecisionPortfolioValidationError as exc:
            assert exc.details["reason"] == "stress_amount_unresolvable"
            assert exc.details["decision_id"] == stress.id


def test_portfolio_stress_test_temporary_income_loss_uses_explicit_amount() -> (
    None
):
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=5_000_000)

        purchase = _save(
            db,
            user,
            "major_purchase",
            "Purchase",
            _major_purchase_input(100_000),
        )
        stress = _save(
            db,
            user,
            "stress_test",
            "Between jobs",
            {
                "scenario_type": "temporary_income_loss",
                "scenario_name": "Between jobs",
                "stress_amount_cents": 200_000,
                "event_date": TEST_DATE.isoformat(),
                "duration_days": 15,
            },
        )

        result = decision_portfolio_service.evaluate_decision_portfolio(
            db, user.id, [purchase.id, stress.id], as_of=TEST_DATE
        )

        # A duration-bound temporary loss contributes its explicit
        # entered total once, as a one-time draw -- it does not also
        # add an ongoing monthly capacity reduction (that would double
        # count the same dollars against goal funding).
        assert result.combined.safe_to_spend_cents == 4_700_000
        assert result.goal_impacts == []


def test_portfolio_stress_test_income_reduction_feeds_monthly_capacity() -> (
    None
):
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

        purchase = _save(
            db,
            user,
            "major_purchase",
            "Purchase",
            _major_purchase_input(100_000),
        )
        stress = _save(
            db,
            user,
            "stress_test",
            "Income drop",
            {
                "scenario_type": "income_reduction",
                "scenario_name": "Reduced hours",
                "income_reduction_percent": 30,
                "event_date": TEST_DATE.isoformat(),
            },
        )

        result = decision_portfolio_service.evaluate_decision_portfolio(
            db, user.id, [purchase.id, stress.id], as_of=TEST_DATE
        )

        assert len(result.goal_impacts) == 1
        assert result.goal_impacts[0].status in ("at_risk", "delayed")


def test_portfolio_stress_test_temporary_income_loss_duration_scales_impact() -> (
    None
):
    # Concern 3: when temporary_income_loss's amount is derived (no
    # explicit stress_amount_cents), duration_days IS how
    # financial_stress_test_service defines the shock's size --
    # average_monthly_income_cents * duration_days / 30 (see
    # _derive_temporary_income_loss_cents). The portfolio reuses that
    # same function unmodified, so two persisted decisions differing
    # only in duration_days must produce materially different combined
    # totals, not the same number under two labels.
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

        purchase = _save(
            db,
            user,
            "major_purchase",
            "Purchase",
            _major_purchase_input(100_000),
        )
        short = _save(
            db,
            user,
            "stress_test",
            "Short gap",
            {
                "scenario_type": "temporary_income_loss",
                "scenario_name": "Short gap",
                "event_date": TEST_DATE.isoformat(),
                "duration_days": 30,
            },
        )
        long = _save(
            db,
            user,
            "stress_test",
            "Long gap",
            {
                "scenario_type": "temporary_income_loss",
                "scenario_name": "Long gap",
                "event_date": TEST_DATE.isoformat(),
                "duration_days": 90,
            },
        )

        short_result = decision_portfolio_service.evaluate_decision_portfolio(
            db, user.id, [purchase.id, short.id], as_of=TEST_DATE
        )
        long_result = decision_portfolio_service.evaluate_decision_portfolio(
            db, user.id, [purchase.id, long.id], as_of=TEST_DATE
        )

        # Both share the same baseline (same income history, same
        # as_of), so the gap between them isolates the duration-driven
        # amount: trailing 3-month average income is 500,000/month, and
        # the derived amount is average_monthly_income_cents *
        # duration_days / 30 -- a 90-day gap must draw exactly
        # 1,000,000 more than a 30-day gap (1,500,000 vs 500,000).
        assert (
            short_result.combined.safe_to_spend_cents
            - long_result.combined.safe_to_spend_cents
            == 1_000_000
        )


def test_portfolio_stress_test_income_reduction_ignores_duration_like_standalone() -> (
    None
):
    # income_reduction models an ongoing monthly reduction (it feeds
    # monthly_capacity_delta_cents), not a fixed-duration lump sum --
    # financial_stress_test_service never reads duration_days for this
    # subtype (see _income_reduction_amount). Two otherwise-identical
    # decisions differing only in duration_days must therefore produce
    # the SAME portfolio effect: that is the underlying engine's own
    # definition of this subtype, reused unmodified, not a
    # portfolio-introduced compression of a real difference.
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

        purchase = _save(
            db,
            user,
            "major_purchase",
            "Purchase",
            _major_purchase_input(100_000),
        )
        short = _save(
            db,
            user,
            "stress_test",
            "Short",
            {
                "scenario_type": "income_reduction",
                "scenario_name": "Short",
                "income_reduction_percent": 30,
                "event_date": TEST_DATE.isoformat(),
                "duration_days": 30,
            },
        )
        long = _save(
            db,
            user,
            "stress_test",
            "Long",
            {
                "scenario_type": "income_reduction",
                "scenario_name": "Long",
                "income_reduction_percent": 30,
                "event_date": TEST_DATE.isoformat(),
                "duration_days": 90,
            },
        )

        short_result = decision_portfolio_service.evaluate_decision_portfolio(
            db, user.id, [purchase.id, short.id], as_of=TEST_DATE
        )
        long_result = decision_portfolio_service.evaluate_decision_portfolio(
            db, user.id, [purchase.id, long.id], as_of=TEST_DATE
        )

        assert (
            short_result.combined.safe_to_spend_cents
            == long_result.combined.safe_to_spend_cents
        )


# --- Buy now vs wait -----------------------------------------------------


def test_portfolio_buy_now_vs_wait_requires_variant() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=5_000_000)

        purchase = _save(
            db,
            user,
            "major_purchase",
            "Purchase",
            _major_purchase_input(100_000),
        )
        bnw = _save(
            db,
            user,
            "buy_now_vs_wait",
            "Laptop",
            _buy_now_vs_wait_input(),
        )

        try:
            decision_portfolio_service.evaluate_decision_portfolio(
                db, user.id, [purchase.id, bnw.id], as_of=TEST_DATE
            )
            assert False, "expected DecisionPortfolioValidationError"
        except DecisionPortfolioValidationError as exc:
            assert exc.details["reason"] == "variant_required"
            assert exc.details["decision_id"] == bnw.id


def test_portfolio_buy_now_vs_wait_invalid_variant_rejected() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=5_000_000)

        purchase = _save(
            db,
            user,
            "major_purchase",
            "Purchase",
            _major_purchase_input(100_000),
        )
        bnw = _save(
            db,
            user,
            "buy_now_vs_wait",
            "Laptop",
            _buy_now_vs_wait_input(),
        )

        try:
            decision_portfolio_service.evaluate_decision_portfolio(
                db,
                user.id,
                [purchase.id, bnw.id],
                variants={bnw.id: "later"},
                as_of=TEST_DATE,
            )
            assert False, "expected DecisionPortfolioValidationError"
        except DecisionPortfolioValidationError as exc:
            assert exc.details["reason"] == "invalid_variant"
            assert exc.details["decision_id"] == bnw.id


def test_portfolio_buy_now_vs_wait_buy_now_variant() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=5_000_000)

        purchase = _save(
            db,
            user,
            "major_purchase",
            "Purchase",
            _major_purchase_input(100_000),
        )
        bnw = _save(
            db,
            user,
            "buy_now_vs_wait",
            "Laptop",
            _buy_now_vs_wait_input(),
        )

        result = decision_portfolio_service.evaluate_decision_portfolio(
            db,
            user.id,
            [purchase.id, bnw.id],
            variants={bnw.id: "buy_now"},
            as_of=TEST_DATE,
        )

        assert result.combined.safe_to_spend_cents == (
            5_000_000 - 100_000 - 150_000
        )
        selection = next(
            d for d in result.selected_decisions if d.decision_id == bnw.id
        )
        assert selection.variant == "buy_now"
        assert selection.variant_label == "Buy now"


def test_portfolio_buy_now_vs_wait_wait_variant_rejected_as_unsupported() -> (
    None
):
    # Concern 1: buy_now and wait must not silently collapse into the
    # same financial calculation under a different label. The portfolio
    # has one shared baseline as of today, so it cannot honor WAIT's
    # real meaning (safe-to-spend re-evaluated as of the wait date) --
    # it must reject the branch outright rather than approximate it as
    # a same-dollar purchase on a later date.
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=5_000_000)

        purchase = _save(
            db,
            user,
            "major_purchase",
            "Purchase",
            _major_purchase_input(100_000),
        )
        bnw = _save(
            db,
            user,
            "buy_now_vs_wait",
            "Laptop",
            _buy_now_vs_wait_input(),
        )

        try:
            decision_portfolio_service.evaluate_decision_portfolio(
                db,
                user.id,
                [purchase.id, bnw.id],
                variants={bnw.id: "wait"},
                as_of=TEST_DATE,
            )
            assert False, "expected DecisionPortfolioValidationError"
        except DecisionPortfolioValidationError as exc:
            assert exc.details["reason"] == "wait_branch_unsupported"
            assert exc.details["decision_id"] == bnw.id


def test_portfolio_buy_now_vs_wait_buy_now_variant_ignores_persisted_wait_date() -> (
    None
):
    # buy_now's financial effect must come only from buy_now_date /
    # purchase_amount_cents -- a wait_until_date far outside the
    # horizon must not affect the buy_now branch at all.
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=5_000_000)

        purchase = _save(
            db,
            user,
            "major_purchase",
            "Purchase",
            _major_purchase_input(100_000),
        )
        bnw = _save(
            db,
            user,
            "buy_now_vs_wait",
            "Laptop",
            _buy_now_vs_wait_input(
                wait_until_date=TEST_DATE + timedelta(days=95)
            ),
        )

        result = decision_portfolio_service.evaluate_decision_portfolio(
            db,
            user.id,
            [purchase.id, bnw.id],
            variants={bnw.id: "buy_now"},
            as_of=TEST_DATE,
        )
        assert result.combined.safe_to_spend_cents == (
            5_000_000 - 100_000 - 150_000
        )
        selection = next(
            d for d in result.selected_decisions if d.decision_id == bnw.id
        )
        assert selection.variant == "buy_now"
        assert selection.variant_label == "Buy now"


def test_portfolio_buy_now_vs_wait_selection_does_not_mutate_saved_decision() -> (
    None
):
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=5_000_000)

        purchase = _save(
            db,
            user,
            "major_purchase",
            "Purchase",
            _major_purchase_input(100_000),
        )
        bnw = _save(
            db,
            user,
            "buy_now_vs_wait",
            "Laptop",
            _buy_now_vs_wait_input(),
        )
        original_input_snapshot = dict(bnw.input_snapshot)
        original_status = bnw.status

        decision_portfolio_service.evaluate_decision_portfolio(
            db,
            user.id,
            [purchase.id, bnw.id],
            variants={bnw.id: "buy_now"},
            as_of=TEST_DATE,
        )

        reloaded = db.get(SavedDecision, bnw.id)
        assert reloaded.input_snapshot == original_input_snapshot
        assert reloaded.status == original_status


# --- What-if comparison --------------------------------------------------


def test_portfolio_what_if_comparison_requires_variant() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=5_000_000)

        purchase = _save(
            db,
            user,
            "major_purchase",
            "Purchase",
            _major_purchase_input(100_000),
        )
        comparison = _save(
            db,
            user,
            "what_if_comparison",
            "Comparison",
            _what_if_comparison_input(),
        )

        try:
            decision_portfolio_service.evaluate_decision_portfolio(
                db, user.id, [purchase.id, comparison.id], as_of=TEST_DATE
            )
            assert False, "expected DecisionPortfolioValidationError"
        except DecisionPortfolioValidationError as exc:
            assert exc.details["reason"] == "variant_required"
            assert exc.details["decision_id"] == comparison.id


def test_portfolio_what_if_comparison_invalid_variant_rejected() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=5_000_000)

        purchase = _save(
            db,
            user,
            "major_purchase",
            "Purchase",
            _major_purchase_input(100_000),
        )
        comparison = _save(
            db,
            user,
            "what_if_comparison",
            "Comparison",
            _what_if_comparison_input(),
        )

        try:
            decision_portfolio_service.evaluate_decision_portfolio(
                db,
                user.id,
                [purchase.id, comparison.id],
                variants={comparison.id: "option_c"},
                as_of=TEST_DATE,
            )
            assert False, "expected DecisionPortfolioValidationError"
        except DecisionPortfolioValidationError as exc:
            assert exc.details["reason"] == "invalid_variant"
            assert exc.details["decision_id"] == comparison.id


def test_portfolio_what_if_comparison_label_is_not_a_valid_variant() -> None:
    # Concern 2: the branch identifier is option_a/option_b, never the
    # persisted display label -- even though the label happens to be
    # accepted input shape-wise (a string under 60 chars), it must not
    # resolve to a branch.
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=5_000_000)

        purchase = _save(
            db,
            user,
            "major_purchase",
            "Purchase",
            _major_purchase_input(100_000),
        )
        comparison = _save(
            db,
            user,
            "what_if_comparison",
            "Comparison",
            _what_if_comparison_input(),
        )

        try:
            decision_portfolio_service.evaluate_decision_portfolio(
                db,
                user.id,
                [purchase.id, comparison.id],
                variants={comparison.id: "Option A"},
                as_of=TEST_DATE,
            )
            assert False, "expected DecisionPortfolioValidationError"
        except DecisionPortfolioValidationError as exc:
            assert exc.details["reason"] == "invalid_variant"
            assert exc.details["decision_id"] == comparison.id


def test_portfolio_what_if_comparison_option_a_variant() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=5_000_000)

        purchase = _save(
            db,
            user,
            "major_purchase",
            "Purchase",
            _major_purchase_input(100_000),
        )
        comparison = _save(
            db,
            user,
            "what_if_comparison",
            "Comparison",
            _what_if_comparison_input(),
        )

        result = decision_portfolio_service.evaluate_decision_portfolio(
            db,
            user.id,
            [purchase.id, comparison.id],
            variants={comparison.id: "option_a"},
            as_of=TEST_DATE,
        )

        assert result.combined.safe_to_spend_cents == (
            5_000_000 - 100_000 - 200_000
        )
        selection = next(
            d
            for d in result.selected_decisions
            if d.decision_id == comparison.id
        )
        assert selection.variant == "option_a"
        assert selection.variant_label == "Option A"


def test_portfolio_what_if_comparison_option_b_variant() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=5_000_000)

        purchase = _save(
            db,
            user,
            "major_purchase",
            "Purchase",
            _major_purchase_input(100_000),
        )
        comparison = _save(
            db,
            user,
            "what_if_comparison",
            "Comparison",
            _what_if_comparison_input(),
        )

        result = decision_portfolio_service.evaluate_decision_portfolio(
            db,
            user.id,
            [purchase.id, comparison.id],
            variants={comparison.id: "option_b"},
            as_of=TEST_DATE,
        )

        assert result.combined.safe_to_spend_cents == (
            5_000_000 - 100_000 - 500_000
        )
        selection = next(
            d
            for d in result.selected_decisions
            if d.decision_id == comparison.id
        )
        assert selection.variant == "option_b"
        assert selection.variant_label == "Option B"


def test_portfolio_what_if_comparison_option_a_maps_only_to_scenario_a() -> (
    None
):
    # option_a must never resolve to scenario B's numbers, and vice
    # versa, regardless of how many scenarios are persisted.
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=5_000_000)

        purchase = _save(
            db,
            user,
            "major_purchase",
            "Purchase",
            _major_purchase_input(100_000),
        )
        comparison = _save(
            db,
            user,
            "what_if_comparison",
            "Comparison",
            _what_if_comparison_input(
                scenarios=[
                    {
                        "label": "Same label",
                        "scenario_type": "one_time_expense",
                        "amount_cents": 200_000,
                        "effective_date": (
                            TEST_DATE + timedelta(days=5)
                        ).isoformat(),
                    },
                    {
                        "label": "Same label (2)",
                        "scenario_type": "one_time_expense",
                        "amount_cents": 500_000,
                        "effective_date": (
                            TEST_DATE + timedelta(days=5)
                        ).isoformat(),
                    },
                ]
            ),
        )

        option_a_result = (
            decision_portfolio_service.evaluate_decision_portfolio(
                db,
                user.id,
                [purchase.id, comparison.id],
                variants={comparison.id: "option_a"},
                as_of=TEST_DATE,
            )
        )
        option_b_result = (
            decision_portfolio_service.evaluate_decision_portfolio(
                db,
                user.id,
                [purchase.id, comparison.id],
                variants={comparison.id: "option_b"},
                as_of=TEST_DATE,
            )
        )

        assert option_a_result.combined.safe_to_spend_cents == (
            5_000_000 - 100_000 - 200_000
        )
        assert option_b_result.combined.safe_to_spend_cents == (
            5_000_000 - 100_000 - 500_000
        )


def test_portfolio_what_if_comparison_long_display_label_still_selectable() -> (
    None
):
    # A persisted scenario's display label (up to 60 chars) must never
    # make that scenario unselectable just because the label is long --
    # the variant is a short positional key, independent of label
    # length.
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=5_000_000)

        long_label = "A" * 60
        purchase = _save(
            db,
            user,
            "major_purchase",
            "Purchase",
            _major_purchase_input(100_000),
        )
        comparison = _save(
            db,
            user,
            "what_if_comparison",
            "Comparison",
            _what_if_comparison_input(
                scenarios=[
                    {
                        "label": long_label,
                        "scenario_type": "one_time_expense",
                        "amount_cents": 200_000,
                        "effective_date": (
                            TEST_DATE + timedelta(days=5)
                        ).isoformat(),
                    },
                    {
                        "label": "Option B",
                        "scenario_type": "one_time_expense",
                        "amount_cents": 500_000,
                        "effective_date": (
                            TEST_DATE + timedelta(days=5)
                        ).isoformat(),
                    },
                ]
            ),
        )

        result = decision_portfolio_service.evaluate_decision_portfolio(
            db,
            user.id,
            [purchase.id, comparison.id],
            variants={comparison.id: "option_a"},
            as_of=TEST_DATE,
        )

        assert result.combined.safe_to_spend_cents == (
            5_000_000 - 100_000 - 200_000
        )
        selection = next(
            d
            for d in result.selected_decisions
            if d.decision_id == comparison.id
        )
        assert selection.variant_label == long_label


def test_portfolio_what_if_comparison_duplicate_display_labels_rejected_safely() -> (
    None
):
    # WhatIfComparisonRequest.validate_unique_labels already refuses
    # duplicate labels at save time, and _parse_input revalidates every
    # persisted input through that same schema -- so even a directly
    # tampered snapshot with two identical labels can't reach branch
    # resolution and be matched ambiguously. This closes the door the
    # old exact-label-as-variant design would have left open: branch
    # identity (option_a/option_b) never depends on labels being
    # unique in the first place.
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=5_000_000)

        purchase = _save(
            db,
            user,
            "major_purchase",
            "Purchase",
            _major_purchase_input(100_000),
        )
        comparison = _save(
            db,
            user,
            "what_if_comparison",
            "Comparison",
            _what_if_comparison_input(),
        )
        comparison.input_snapshot = {
            **comparison.input_snapshot,
            "scenarios": [
                {
                    **comparison.input_snapshot["scenarios"][0],
                    "label": "Duplicate",
                },
                {
                    **comparison.input_snapshot["scenarios"][1],
                    "label": "Duplicate",
                },
            ],
        }
        db.commit()

        try:
            decision_portfolio_service.evaluate_decision_portfolio(
                db,
                user.id,
                [purchase.id, comparison.id],
                variants={comparison.id: "option_a"},
                as_of=TEST_DATE,
            )
            assert False, "expected DecisionPortfolioValidationError"
        except DecisionPortfolioValidationError as exc:
            assert exc.details["reason"] == "invalid_persisted_input"
            assert exc.details["decision_id"] == comparison.id


def test_portfolio_what_if_comparison_selection_does_not_mutate_saved_decision() -> (
    None
):
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=5_000_000)

        purchase = _save(
            db,
            user,
            "major_purchase",
            "Purchase",
            _major_purchase_input(100_000),
        )
        comparison = _save(
            db,
            user,
            "what_if_comparison",
            "Comparison",
            _what_if_comparison_input(),
        )
        original_input_snapshot = dict(comparison.input_snapshot)

        decision_portfolio_service.evaluate_decision_portfolio(
            db,
            user.id,
            [purchase.id, comparison.id],
            variants={comparison.id: "option_a"},
            as_of=TEST_DATE,
        )

        reloaded = db.get(SavedDecision, comparison.id)
        assert reloaded.input_snapshot == original_input_snapshot


def test_portfolio_variant_provided_for_non_variant_decision_rejected() -> (
    None
):
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=5_000_000)

        purchase = _save(
            db,
            user,
            "major_purchase",
            "Purchase",
            _major_purchase_input(100_000),
        )
        what_if = _save(
            db,
            user,
            "what_if",
            "What if",
            _what_if_one_time_input(
                50_000, effective_date=TEST_DATE + timedelta(days=5)
            ),
        )

        try:
            decision_portfolio_service.evaluate_decision_portfolio(
                db,
                user.id,
                [purchase.id, what_if.id],
                variants={what_if.id: "option_a"},
                as_of=TEST_DATE,
            )
            assert False, "expected DecisionPortfolioValidationError"
        except DecisionPortfolioValidationError as exc:
            assert exc.details["reason"] == "invalid_variant"
            assert exc.details["decision_id"] == what_if.id


# --- Mixed-type combination ------------------------------------------------


def test_portfolio_combines_all_supported_types_with_stable_ranking() -> (
    None
):
    with TestingSessionLocal() as db:
        user = create_user(db)
        create_account(db, user, available_balance_cents=20_000_000)

        purchase = _save(
            db,
            user,
            "major_purchase",
            "Purchase",
            _major_purchase_input(1_000_000),
        )
        what_if = _save(
            db,
            user,
            "what_if",
            "What if",
            _what_if_one_time_input(
                500_000, effective_date=TEST_DATE + timedelta(days=5)
            ),
        )
        stress = _save(
            db, user, "stress_test", "Car repair", _stress_test_input()
        )
        bnw = _save(
            db,
            user,
            "buy_now_vs_wait",
            "Laptop",
            _buy_now_vs_wait_input(),
        )
        comparison = _save(
            db,
            user,
            "what_if_comparison",
            "Comparison",
            _what_if_comparison_input(),
        )

        result = decision_portfolio_service.evaluate_decision_portfolio(
            db,
            user.id,
            [purchase.id, what_if.id, stress.id, bnw.id, comparison.id],
            variants={bnw.id: "buy_now", comparison.id: "option_a"},
            as_of=TEST_DATE,
        )

        assert result.combined.safe_to_spend_cents == (
            20_000_000
            - 1_000_000
            - 500_000
            - 100_000
            - 150_000
            - 200_000
        )
        assert len(result.decision_impacts) == 5
        ranks = [impact.risk_rank for impact in result.decision_impacts]
        assert ranks == sorted(ranks)
        impacts_cents = [
            impact.incremental_safe_to_spend_impact_cents
            for impact in result.decision_impacts
        ]
        assert impacts_cents == sorted(impacts_cents)


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

        # Goal Conflict Intelligence normalizes the SAME goal_impacts
        # entry above -- it must never recompute or diverge from it.
        intelligence = result.goal_conflict_intelligence
        assert intelligence.supported is True
        assert len(intelligence.goals) == 1
        item = intelligence.goals[0]
        assert item.goal_id == goal_impact.goal_id
        assert item.funding_shortfall_cents == goal_impact.funding_shortfall_cents
        assert item.status == goal_impact.status == "at_risk"
        assert item.severity == "high"
        assert item.conflict is True
        assert intelligence.conflict_count == 1
        assert intelligence.most_affected_goal_id == goal_impact.goal_id

        # Regression: the underlying goal_impacts values are exactly as
        # they were before this feature existed.
        assert result.goal_impacts[0].funding_shortfall_cents == 3_600_000
        assert result.goal_impacts[0].status == "at_risk"


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


def test_portfolio_endpoint_rejects_both_decision_ids_and_items(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "portfolio-both-shapes")

    response = client.post(
        f"/users/{user_id}/decisions/portfolio",
        headers=headers,
        json={
            "decision_ids": [1, 2],
            "items": [{"decision_id": 1}, {"decision_id": 2}],
        },
    )

    assert response.status_code == 422


def test_portfolio_endpoint_rejects_neither_decision_ids_nor_items(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "portfolio-no-shape")

    response = client.post(
        f"/users/{user_id}/decisions/portfolio",
        headers=headers,
        json={},
    )

    assert response.status_code == 422


def test_portfolio_endpoint_supports_items_with_variant(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "portfolio-items")

    with TestingSessionLocal() as db:
        user = db.get(User, user_id)
        create_account(db, user, available_balance_cents=10_000_000)

    today = date.today()

    purchase_response = client.post(
        f"/users/{user_id}/decisions",
        headers=headers,
        json={
            "decision_type": "major_purchase",
            "title": "Laptop",
            "input": _major_purchase_input(1_000_000, purchase_date=today),
        },
    )
    purchase_id = purchase_response.json()["id"]

    bnw_response = client.post(
        f"/users/{user_id}/decisions",
        headers=headers,
        json={
            "decision_type": "buy_now_vs_wait",
            "title": "Car",
            "input": {
                "purchase_name": "Car",
                "purchase_amount_cents": 2_000_000,
                "buy_now_date": today.isoformat(),
                "wait_until_date": (today + timedelta(days=30)).isoformat(),
            },
        },
    )
    bnw_id = bnw_response.json()["id"]

    portfolio_response = client.post(
        f"/users/{user_id}/decisions/portfolio",
        headers=headers,
        json={
            "items": [
                {"decision_id": purchase_id},
                {"decision_id": bnw_id, "variant": "buy_now"},
            ]
        },
    )

    assert portfolio_response.status_code == 200
    body = portfolio_response.json()
    assert body["combined"]["safe_to_spend_cents"] == (
        10_000_000 - 1_000_000 - 2_000_000
    )
    selections = {
        d["decision_id"]: d for d in body["selected_decisions"]
    }
    assert selections[bnw_id]["variant"] == "buy_now"
    assert selections[bnw_id]["variant_label"] == "Buy now"


def test_portfolio_endpoint_rejects_missing_variant(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "portfolio-http-variant")

    with TestingSessionLocal() as db:
        user = db.get(User, user_id)
        create_account(db, user, available_balance_cents=5_000_000)

    today = date.today()

    purchase_response = client.post(
        f"/users/{user_id}/decisions",
        headers=headers,
        json={
            "decision_type": "major_purchase",
            "title": "Laptop",
            "input": _major_purchase_input(100_000, purchase_date=today),
        },
    )
    purchase_id = purchase_response.json()["id"]

    bnw_response = client.post(
        f"/users/{user_id}/decisions",
        headers=headers,
        json={
            "decision_type": "buy_now_vs_wait",
            "title": "Car",
            "input": {
                "purchase_name": "Car",
                "purchase_amount_cents": 200_000,
                "buy_now_date": today.isoformat(),
                "wait_until_date": (today + timedelta(days=30)).isoformat(),
            },
        },
    )
    bnw_id = bnw_response.json()["id"]

    response = client.post(
        f"/users/{user_id}/decisions/portfolio",
        headers=headers,
        json={"decision_ids": [purchase_id, bnw_id]},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "variant_required"


# --- Goal conflict intelligence (pure unit tests) ---------------------


def _goal_impact(
    goal_id: int,
    status: str,
    *,
    funding_shortfall_cents: int = 0,
    delay_months: int = 0,
    baseline_allocation_cents: int = 10_000,
    adjusted_allocation_cents: int = 10_000,
) -> GoalImpactOut:
    return GoalImpactOut(
        goal_id=goal_id,
        goal_name=f"Goal {goal_id}",
        target_date=None,
        target_amount_cents=100_000,
        saved_amount_cents=0,
        remaining_amount_cents=100_000,
        current_required_monthly_contribution_cents=10_000,
        baseline_monthly_allocation_cents=baseline_allocation_cents,
        adjusted_monthly_allocation_cents=adjusted_allocation_cents,
        monthly_allocation_change_cents=(
            adjusted_allocation_cents - baseline_allocation_cents
        ),
        baseline_estimated_completion_date=None,
        adjusted_estimated_completion_date=None,
        delay_months=delay_months,
        funding_shortfall_cents=funding_shortfall_cents,
        status=status,
        explanation="x",
    )


def test_goal_conflict_intelligence_unaffected_goal_has_no_conflict() -> None:
    result = build_goal_conflict_intelligence(
        [_goal_impact(1, "unaffected")]
    )

    item = result.goals[0]
    assert item.conflict is False
    assert item.severity == "none"
    assert result.conflict_count == 0
    assert result.most_affected_goal_id is None


def test_goal_conflict_intelligence_reduced_allocation_is_low_not_conflict() -> (
    None
):
    result = build_goal_conflict_intelligence(
        [
            _goal_impact(
                1,
                "reduced",
                baseline_allocation_cents=10_000,
                adjusted_allocation_cents=6_000,
            )
        ]
    )

    item = result.goals[0]
    assert item.severity == "low"
    assert item.conflict is False
    assert item.allocation_change_cents == -4_000


def test_goal_conflict_intelligence_completion_delay_is_medium_conflict() -> (
    None
):
    result = build_goal_conflict_intelligence(
        [_goal_impact(1, "delayed", delay_months=3)]
    )

    item = result.goals[0]
    assert item.severity == "medium"
    assert item.conflict is True
    assert item.delay_months == 3


def test_goal_conflict_intelligence_at_risk_and_impossible_are_high_severity() -> (
    None
):
    result = build_goal_conflict_intelligence(
        [
            _goal_impact(1, "at_risk", funding_shortfall_cents=100),
            _goal_impact(2, "impossible", funding_shortfall_cents=200),
        ]
    )

    assert all(item.severity == "high" for item in result.goals)
    assert all(item.conflict for item in result.goals)
    assert result.conflict_count == 2


def test_goal_conflict_intelligence_ranks_multiple_goals_by_severity_then_magnitude() -> (
    None
):
    unaffected = _goal_impact(1, "unaffected")
    delayed = _goal_impact(2, "delayed", delay_months=1)
    at_risk_small = _goal_impact(3, "at_risk", funding_shortfall_cents=500)
    at_risk_large = _goal_impact(4, "at_risk", funding_shortfall_cents=1_000)

    result = build_goal_conflict_intelligence(
        [unaffected, delayed, at_risk_small, at_risk_large]
    )

    assert [item.goal_id for item in result.goals] == [4, 3, 2, 1]
    assert [item.rank for item in result.goals] == [1, 2, 3, 4]
    assert result.most_affected_goal_id == 4


def test_goal_conflict_intelligence_deterministic_tie_break_by_goal_id() -> (
    None
):
    result = build_goal_conflict_intelligence(
        [
            _goal_impact(5, "at_risk", funding_shortfall_cents=1_000),
            _goal_impact(3, "at_risk", funding_shortfall_cents=1_000),
        ]
    )

    assert [item.goal_id for item in result.goals] == [3, 5]


def test_goal_conflict_intelligence_empty_goal_impacts_is_supported_empty() -> (
    None
):
    result = build_goal_conflict_intelligence([])

    assert result.supported is True
    assert result.goals == []
    assert result.most_affected_goal_id is None
    assert result.conflict_count == 0
