from datetime import date, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import (
    FinancialAccount,
    PlaidItem,
    SavingsGoal,
    Transaction,
    User,
)
from app.schemas import (
    MajorPurchaseSimulationOut,
    MajorPurchaseSimulationRequest,
    SafeToSpendBreakdownOut,
    SafeToSpendOut,
    ScenarioComparisonRequest,
)
from app.services.scenario_comparison_service import (
    _build_reasons,
    _build_scorecard,
    _determine_recommendation,
    compare_major_purchase_scenarios,
)
from tests.conftest import TestingSessionLocal


TEST_DATE = date(2026, 8, 4)


def _currency(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def _make_simulation(
    *,
    purchase_name: str,
    purchase_amount_cents: int = 100_000,
    affordability_status: str = "affordable",
    safe_to_spend_after_purchase_cents: int = 400_000,
    shortfall_after_purchase_cents: int = 0,
    purchase_impact_percent: float = 20.0,
    goal_impact_months: float = 0.0,
    confidence_score: float = 85.0,
) -> MajorPurchaseSimulationOut:
    safe_before = (
        safe_to_spend_after_purchase_cents + purchase_amount_cents
    )
    through_date = TEST_DATE + timedelta(days=30)

    return MajorPurchaseSimulationOut(
        purchase_name=purchase_name,
        purchase_amount_cents=purchase_amount_cents,
        purchase_date=TEST_DATE + timedelta(days=7),
        as_of=TEST_DATE,
        through_date=through_date,
        affordability_status=affordability_status,
        safe_to_spend_before_purchase_cents=safe_before,
        safe_to_spend_after_purchase_cents=(
            safe_to_spend_after_purchase_cents
        ),
        shortfall_after_purchase_cents=(
            shortfall_after_purchase_cents
        ),
        recommended_max_purchase_cents=round(safe_before * 0.75),
        purchase_impact_percent=purchase_impact_percent,
        goal_monthly_savings_required_cents=0,
        goal_impact_months=goal_impact_months,
        confidence_score=confidence_score,
        explanation="test explanation",
        alternatives=[],
        safe_to_spend=SafeToSpendOut(
            as_of=TEST_DATE,
            through_date=through_date,
            horizon_days=30,
            safe_to_spend_cents=safe_before,
            shortfall_cents=0,
            status="safe",
            confidence_score=confidence_score,
            breakdown=SafeToSpendBreakdownOut(
                liquid_balance_cents=safe_before,
                upcoming_obligations_cents=0,
                essential_spending_cents=0,
                safety_reserve_cents=0,
            ),
            obligations=[],
            warnings=[],
        ),
    )


def create_user(
    db: Session,
    email_prefix: str = "scenario-comparison",
) -> User:
    user = User(
        email=f"{email_prefix}-{uuid4().hex}@example.com",
        password_hash="test-password-hash",
        email_verified=True,
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return user


def create_account(
    db: Session,
    user: User,
    *,
    available_balance_cents: int | None = 500_000,
    current_balance_cents: int | None = 500_000,
) -> FinancialAccount:
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
        current_balance_cents=current_balance_cents,
        available_balance_cents=available_balance_cents,
        currency="USD",
    )

    db.add(account)
    db.commit()
    db.refresh(account)

    return account


def register_and_login(
    client: TestClient,
    prefix: str,
) -> tuple[int, dict[str, str]]:
    email = f"{prefix}-{uuid4().hex}@example.com"
    password = "TestPassword123!"

    create_response = client.post(
        "/users",
        json={
            "email": email,
            "password": password,
        },
    )

    assert create_response.status_code == 201

    login_response = client.post(
        "/users/login",
        json={
            "email": email,
            "password": password,
        },
    )

    assert login_response.status_code == 200

    return create_response.json()["id"], {
        "Authorization": (
            f"Bearer {login_response.json()['access_token']}"
        )
    }


def _comparison_request(
    *,
    option_a_name: str = "Laptop",
    option_a_amount: int = 200_000,
    option_b_name: str = "Vacation",
    option_b_amount: int = 400_000,
    purchase_date: date | None = None,
    safety_reserve_cents: int = 0,
    essential_spending_cents: int = 0,
    horizon_days: int = 30,
) -> ScenarioComparisonRequest:
    purchase_day = purchase_date or (TEST_DATE + timedelta(days=7))

    return ScenarioComparisonRequest(
        option_a=MajorPurchaseSimulationRequest(
            purchase_name=option_a_name,
            purchase_amount_cents=option_a_amount,
            purchase_date=purchase_day,
            safety_reserve_cents=safety_reserve_cents,
            essential_spending_cents=essential_spending_cents,
            horizon_days=horizon_days,
        ),
        option_b=MajorPurchaseSimulationRequest(
            purchase_name=option_b_name,
            purchase_amount_cents=option_b_amount,
            purchase_date=purchase_day,
            safety_reserve_cents=safety_reserve_cents,
            essential_spending_cents=essential_spending_cents,
            horizon_days=horizon_days,
        ),
    )


def test_affordable_option_beats_caution_option() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "affordable-vs-caution")

        create_account(
            db,
            user,
            available_balance_cents=500_000,
        )

        result = compare_major_purchase_scenarios(
            db,
            user.id,
            _comparison_request(
                option_a_amount=200_000,
                option_b_amount=400_000,
            ),
            as_of=TEST_DATE,
        )

        assert result.recommended_option == "option_a"
        assert result.option_a.affordability_rank == 3
        assert result.option_b.affordability_rank == 2
        assert (
            result.option_a.simulation.affordability_status
            == "affordable"
        )
        assert (
            result.option_b.simulation.affordability_status
            == "caution"
        )

        affordability_criterion = next(
            criterion
            for criterion in result.scorecard.criteria
            if criterion.key == "affordability"
        )
        assert affordability_criterion.winner == "option_a"
        assert (
            result.scorecard.option_a_score
            > result.scorecard.option_b_score
        )
        assert (
            result.scorecard.option_a_score
            + result.scorecard.option_b_score
            == result.scorecard.max_score
        )
        assert 2 <= len(result.reasons) <= 4
        assert "affordable" in result.reasons[0].lower()


def test_caution_option_beats_not_affordable_option() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "caution-vs-not-affordable")

        create_account(
            db,
            user,
            available_balance_cents=500_000,
        )

        result = compare_major_purchase_scenarios(
            db,
            user.id,
            _comparison_request(
                option_a_amount=400_000,
                option_b_amount=550_000,
            ),
            as_of=TEST_DATE,
        )

        assert result.recommended_option == "option_a"
        assert result.option_a.affordability_rank == 2
        assert result.option_b.affordability_rank == 1


def test_lower_shortfall_wins_when_affordability_ranks_match() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "shortfall-tiebreak")

        create_account(
            db,
            user,
            available_balance_cents=300_000,
        )

        result = compare_major_purchase_scenarios(
            db,
            user.id,
            _comparison_request(
                option_a_amount=350_000,
                option_b_amount=450_000,
            ),
            as_of=TEST_DATE,
        )

        assert result.recommended_option == "option_a"
        assert (
            result.option_a.simulation.shortfall_after_purchase_cents
            < result.option_b.simulation.shortfall_after_purchase_cents
        )
        assert (
            result.option_a.simulation.affordability_status
            == "not_affordable"
        )
        assert (
            result.option_b.simulation.affordability_status
            == "not_affordable"
        )

        shortfall_criterion = next(
            criterion
            for criterion in result.scorecard.criteria
            if criterion.key == "shortfall"
        )
        assert shortfall_criterion.winner == "option_a"
        assert any(
            "lower shortfall" in reason for reason in result.reasons
        )


def test_higher_remaining_safe_to_spend_wins() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "safe-to-spend-tiebreak")

        create_account(
            db,
            user,
            available_balance_cents=500_000,
        )

        result = compare_major_purchase_scenarios(
            db,
            user.id,
            _comparison_request(
                option_a_amount=200_000,
                option_b_amount=250_000,
            ),
            as_of=TEST_DATE,
        )

        assert result.recommended_option == "option_a"
        assert (
            result.option_a.simulation.safe_to_spend_after_purchase_cents
            > result.option_b.simulation.safe_to_spend_after_purchase_cents
        )
        assert (
            result.option_a.simulation.shortfall_after_purchase_cents
            == result.option_b.simulation.shortfall_after_purchase_cents
        )

        safe_to_spend_criterion = next(
            criterion
            for criterion in result.scorecard.criteria
            if criterion.key == "safe_to_spend_after"
        )
        assert safe_to_spend_criterion.winner == "option_a"
        assert any(
            "more safe-to-spend after purchase" in reason
            for reason in result.reasons
        )


def test_lower_impact_wins_when_needed() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "impact-tiebreak")

        create_account(
            db,
            user,
            available_balance_cents=500_000,
        )

        purchase_day = TEST_DATE + timedelta(days=7)

        result = compare_major_purchase_scenarios(
            db,
            user.id,
            ScenarioComparisonRequest(
                option_a=MajorPurchaseSimulationRequest(
                    purchase_name="Used car",
                    purchase_amount_cents=200_000,
                    purchase_date=purchase_day,
                    essential_spending_cents=100_000,
                    horizon_days=30,
                ),
                option_b=MajorPurchaseSimulationRequest(
                    purchase_name="New car",
                    purchase_amount_cents=250_000,
                    purchase_date=purchase_day,
                    essential_spending_cents=50_000,
                    horizon_days=30,
                ),
            ),
            as_of=TEST_DATE,
        )

        assert result.recommended_option == "option_a"
        assert result.option_a.affordability_rank == 3
        assert result.option_b.affordability_rank == 3
        assert (
            result.option_a.simulation.shortfall_after_purchase_cents
            == result.option_b.simulation.shortfall_after_purchase_cents
        )
        assert (
            result.option_a.simulation.safe_to_spend_after_purchase_cents
            == result.option_b.simulation.safe_to_spend_after_purchase_cents
        )
        assert (
            result.option_a.simulation.purchase_impact_percent
            < result.option_b.simulation.purchase_impact_percent
        )


def test_identical_options_return_tie() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "identical-options")

        create_account(
            db,
            user,
            available_balance_cents=500_000,
        )

        result = compare_major_purchase_scenarios(
            db,
            user.id,
            _comparison_request(
                option_a_name="Laptop",
                option_a_amount=200_000,
                option_b_name="Laptop",
                option_b_amount=200_000,
            ),
            as_of=TEST_DATE,
        )

        assert result.recommended_option == "tie"
        assert "equally viable" in result.recommendation.lower()

        assert all(
            criterion.winner == "tie"
            for criterion in result.scorecard.criteria
        )
        assert (
            result.scorecard.option_a_score
            == result.scorecard.option_b_score
            == result.scorecard.max_score / 2
        )
        assert len(result.reasons) == 1
        assert "equally viable" in result.reasons[0].lower()


def test_dollar_formatted_recommendation() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "formatted-recommendation")

        create_account(
            db,
            user,
            available_balance_cents=500_000,
        )

        result = compare_major_purchase_scenarios(
            db,
            user.id,
            _comparison_request(
                option_a_amount=200_000,
                option_b_amount=400_000,
            ),
            as_of=TEST_DATE,
        )

        assert "$" in result.recommendation
        assert "$3,000.00" in result.recommendation
        assert "$1,000.00" in result.recommendation


def test_invalid_purchase_date_returns_422(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client,
        "invalid-purchase-date",
    )

    with TestingSessionLocal() as db:
        user = db.get(User, user_id)

        assert user is not None

        create_account(db, user)

    response = client.post(
        f"/users/{user_id}/major-purchase/compare",
        headers=headers,
        json={
            "option_a": {
                "purchase_name": "Laptop",
                "purchase_amount_cents": 200_000,
                "purchase_date": (
                    date.today() - timedelta(days=1)
                ).isoformat(),
                "horizon_days": 30,
            },
            "option_b": {
                "purchase_name": "Phone",
                "purchase_amount_cents": 100_000,
                "purchase_date": (
                    date.today() + timedelta(days=7)
                ).isoformat(),
                "horizon_days": 30,
            },
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "purchase date cannot be before the calculation date"
    )


def test_compare_endpoint_success(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client,
        "compare-endpoint",
    )

    with TestingSessionLocal() as db:
        user = db.get(User, user_id)

        assert user is not None

        create_account(
            db,
            user,
            available_balance_cents=500_000,
        )

    response = client.post(
        f"/users/{user_id}/major-purchase/compare",
        headers=headers,
        json={
            "option_a": {
                "purchase_name": "Laptop",
                "purchase_amount_cents": 200_000,
                "purchase_date": (
                    date.today() + timedelta(days=7)
                ).isoformat(),
                "safety_reserve_cents": 0,
                "essential_spending_cents": 0,
                "horizon_days": 30,
            },
            "option_b": {
                "purchase_name": "Vacation",
                "purchase_amount_cents": 400_000,
                "purchase_date": (
                    date.today() + timedelta(days=7)
                ).isoformat(),
                "safety_reserve_cents": 0,
                "essential_spending_cents": 0,
                "horizon_days": 30,
            },
        },
    )

    assert response.status_code == 200

    payload = response.json()

    assert payload["recommended_option"] == "option_a"
    assert payload["option_a"]["option_key"] == "option_a"
    assert payload["option_b"]["option_key"] == "option_b"
    assert (
        payload["option_a"]["simulation"]["affordability_status"]
        == "affordable"
    )
    assert (
        payload["safe_to_spend_difference_cents"]
        == payload["option_a"]["simulation"][
            "safe_to_spend_after_purchase_cents"
        ]
        - payload["option_b"]["simulation"][
            "safe_to_spend_after_purchase_cents"
        ]
    )


def test_compare_endpoint_blocks_other_user(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client,
        "compare-owner",
    )
    other_user_id, _ = register_and_login(
        client,
        "compare-other",
    )

    response = client.post(
        f"/users/{other_user_id}/major-purchase/compare",
        headers=headers,
        json={
            "option_a": {
                "purchase_name": "Laptop",
                "purchase_amount_cents": 200_000,
                "purchase_date": (
                    date.today() + timedelta(days=7)
                ).isoformat(),
                "horizon_days": 30,
            },
            "option_b": {
                "purchase_name": "Phone",
                "purchase_amount_cents": 100_000,
                "purchase_date": (
                    date.today() + timedelta(days=7)
                ).isoformat(),
                "horizon_days": 30,
            },
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "you cannot access another user's data"
    )


def test_near_tie_decided_by_single_factor() -> None:
    simulation_a = _make_simulation(
        purchase_name="A",
        purchase_impact_percent=20.0,
    )
    simulation_b = _make_simulation(
        purchase_name="B",
        purchase_impact_percent=20.5,
    )

    recommended = _determine_recommendation(
        simulation_a, simulation_b
    )
    scorecard = _build_scorecard(simulation_a, simulation_b)
    reasons = _build_reasons(
        recommended, scorecard, simulation_a, simulation_b
    )

    assert recommended == "option_a"

    winning_criteria = [
        criterion
        for criterion in scorecard.criteria
        if criterion.winner == "option_a"
    ]
    tied_criteria = [
        criterion
        for criterion in scorecard.criteria
        if criterion.winner == "tie"
    ]

    assert len(winning_criteria) == 1
    assert winning_criteria[0].key == "impact_percent"
    assert len(tied_criteria) == 6

    assert len(reasons) == 2
    assert "impact" in reasons[0].lower()
    assert "close call" in reasons[1].lower()


def test_confidence_only_decides_when_everything_else_ties() -> None:
    simulation_a = _make_simulation(
        purchase_name="A",
        confidence_score=90.0,
    )
    simulation_b = _make_simulation(
        purchase_name="B",
        confidence_score=70.0,
    )

    recommended = _determine_recommendation(
        simulation_a, simulation_b
    )
    scorecard = _build_scorecard(simulation_a, simulation_b)
    reasons = _build_reasons(
        recommended, scorecard, simulation_a, simulation_b
    )

    assert recommended == "option_a"

    confidence_criterion = next(
        criterion
        for criterion in scorecard.criteria
        if criterion.key == "confidence"
    )
    assert confidence_criterion.winner == "option_a"

    non_confidence_criteria = [
        criterion
        for criterion in scorecard.criteria
        if criterion.key != "confidence"
    ]
    assert all(
        criterion.winner == "tie"
        for criterion in non_confidence_criteria
    )
    assert any("confidence" in reason.lower() for reason in reasons)


def test_confidence_does_not_override_financial_safety() -> None:
    simulation_a = _make_simulation(
        purchase_name="A",
        affordability_status="affordable",
        confidence_score=50.0,
    )
    simulation_b = _make_simulation(
        purchase_name="B",
        affordability_status="caution",
        confidence_score=99.0,
    )

    recommended = _determine_recommendation(
        simulation_a, simulation_b
    )

    assert recommended == "option_a"


def test_winner_due_to_lower_goal_impact() -> None:
    simulation_a = _make_simulation(
        purchase_name="A",
        goal_impact_months=1.0,
    )
    simulation_b = _make_simulation(
        purchase_name="B",
        goal_impact_months=3.0,
    )

    recommended = _determine_recommendation(
        simulation_a, simulation_b
    )
    scorecard = _build_scorecard(simulation_a, simulation_b)
    reasons = _build_reasons(
        recommended, scorecard, simulation_a, simulation_b
    )

    assert recommended == "option_a"

    goal_criterion = next(
        criterion
        for criterion in scorecard.criteria
        if criterion.key == "goal_impact"
    )
    assert goal_criterion.winner == "option_a"
    assert any("goal" in reason.lower() for reason in reasons)
    assert any("1.0 months" in reason for reason in reasons)


def test_goal_impact_is_sourced_from_savings_goals() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "goal-impact-wiring")

        create_account(
            db,
            user,
            available_balance_cents=500_000,
        )

        goal = SavingsGoal(
            user_id=user.id,
            name="Vacation",
            target_cents=120_000,
            saved_cents=0,
            target_date=date(2026, 10, 4),
        )
        db.add(goal)
        db.commit()

        result = compare_major_purchase_scenarios(
            db,
            user.id,
            _comparison_request(
                option_a_amount=200_000,
                option_b_amount=200_000,
            ),
            as_of=TEST_DATE,
        )

        simulation = result.option_a.simulation

        assert simulation.goal_monthly_savings_required_cents == 60_000
        assert simulation.goal_impact_months == round(
            200_000 / 60_000, 1
        )


def test_goal_impacts_included_on_both_comparison_options() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "goal-impacts-comparison")

        create_account(
            db,
            user,
            available_balance_cents=500_000,
        )

        goal = SavingsGoal(
            user_id=user.id,
            name="Vacation",
            target_cents=120_000,
            saved_cents=0,
            target_date=date(2026, 10, 4),
        )
        db.add(goal)
        db.commit()

        result = compare_major_purchase_scenarios(
            db,
            user.id,
            _comparison_request(
                option_a_amount=200_000,
                option_b_amount=100_000,
            ),
            as_of=TEST_DATE,
        )

        # Additive field on the shared simulation model used by both
        # options; existing top-level comparison fields still work.
        assert len(result.option_a.simulation.goal_impacts) == 1
        assert len(result.option_b.simulation.goal_impacts) == 1
        assert (
            result.option_a.simulation.goal_impacts[0].goal_name
            == "Vacation"
        )
        assert result.recommended_option in (
            "option_a",
            "option_b",
            "tie",
        )
        assert result.scorecard.max_score > 0


def test_scenario_comparison_goal_impact_matches_individual_result() -> (
    None
):
    # Regression test for a production report (2026-08-08): the
    # scorecard's "goal savings pace" ratio (purchase amount vs. the
    # goal's required monthly savings pace) legitimately differs
    # between a $1,500 and a $3,000 option -- that's a valid size
    # comparison, not a bug. The old wording ("uses less of your
    # monthly savings-goal capacity") falsely implied the purchases
    # actually consumed goal funding. Both options here are fully
    # covered by liquid safe-to-spend funds, so the authoritative
    # per-goal signal must show the goal unaffected for both,
    # consistent with the already-fixed individual Major Purchase
    # Simulator result.
    with TestingSessionLocal() as db:
        user = create_user(db, "scenario-goal-impact-regression")

        create_account(db, user, available_balance_cents=6_500_000)

        for month in (5, 6, 7):
            db.add(
                Transaction(
                    user_id=user.id,
                    posted_on=date(2026, month, 1),
                    description="Paycheck",
                    amount_cents=70_000,
                    category="Income",
                )
            )
        db.commit()

        goal = SavingsGoal(
            user_id=user.id,
            name="Production Test Goal",
            target_cents=100_000,
            saved_cents=25_000,
            target_date=date(2026, 12, 31),
        )
        db.add(goal)
        db.commit()

        result = compare_major_purchase_scenarios(
            db,
            user.id,
            _comparison_request(
                option_a_name="Laptop Test",
                option_a_amount=150_000,
                option_b_name="More expensive option",
                option_b_amount=300_000,
                purchase_date=date(2026, 8, 8),
                safety_reserve_cents=500_000,
                essential_spending_cents=200_000,
                horizon_days=30,
            ),
            as_of=date(2026, 8, 8),
        )

        assert result.recommended_option == "option_a"
        assert (
            result.option_a.simulation.shortfall_after_purchase_cents
            == 0
        )
        assert (
            result.option_b.simulation.shortfall_after_purchase_cents
            == 0
        )

        # The ratio legitimately differs -- it's a purchase-size
        # comparison, not a claim about actual funding impact.
        assert result.option_a.simulation.goal_impact_months == 10.0
        assert result.option_b.simulation.goal_impact_months == 20.0

        # The authoritative per-goal signal must agree with the
        # already-fixed individual Major Purchase result: an
        # affordable purchase fully covered by liquid funds leaves
        # the goal unaffected, for both options.
        for option in (result.option_a, result.option_b):
            impact = option.simulation.goal_impacts[0]
            assert impact.status != "impossible"
            assert (
                impact.adjusted_monthly_allocation_cents
                == impact.baseline_monthly_allocation_cents
            )
            assert impact.funding_shortfall_cents == 0

        goal_criterion = next(
            criterion
            for criterion in result.scorecard.criteria
            if criterion.key == "goal_impact"
        )
        assert goal_criterion.label == "Goal savings pace"

        reasons = _build_reasons(
            result.recommended_option,
            result.scorecard,
            result.option_a.simulation,
            result.option_b.simulation,
        )
        assert not any(
            "capacity" in reason.lower() for reason in reasons
        )


def test_reasons_match_actual_metrics() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "reasons-match-metrics")

        create_account(
            db,
            user,
            available_balance_cents=500_000,
        )

        result = compare_major_purchase_scenarios(
            db,
            user.id,
            _comparison_request(
                option_a_amount=200_000,
                option_b_amount=400_000,
            ),
            as_of=TEST_DATE,
        )

        winner_sim = result.option_a.simulation
        loser_sim = result.option_b.simulation
        combined_reasons = " ".join(result.reasons)

        assert (
            _currency(winner_sim.safe_to_spend_after_purchase_cents)
            in combined_reasons
        )
        assert (
            _currency(loser_sim.safe_to_spend_after_purchase_cents)
            in combined_reasons
        )
        assert (
            f"{winner_sim.purchase_impact_percent}%"
            in combined_reasons
        )
        assert (
            f"{loser_sim.purchase_impact_percent}%"
            in combined_reasons
        )
