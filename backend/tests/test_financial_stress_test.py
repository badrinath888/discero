from datetime import date, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import FinancialAccount, PlaidItem, User
from app.schemas import FinancialStressTestRequest
from app.services.financial_stress_test_service import (
    run_financial_stress_test,
)
from tests.conftest import TestingSessionLocal


TEST_DATE = date(2026, 8, 4)


def create_user(
    db: Session,
    email_prefix: str = "financial-stress-test",
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


def test_emergency_expense_resilient() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "emergency-resilient")

        create_account(
            db,
            user,
            available_balance_cents=500_000,
        )

        result = run_financial_stress_test(
            db,
            user.id,
            FinancialStressTestRequest(
                scenario_type="emergency_expense",
                scenario_name="Car repair",
                stress_amount_cents=100_000,
                event_date=TEST_DATE + timedelta(days=3),
                horizon_days=30,
            ),
            as_of=TEST_DATE,
        )

        assert result.risk_level == "resilient"
        assert result.safe_to_spend_before_stress_cents == 500_000
        assert result.safe_to_spend_after_stress_cents == 400_000
        assert result.total_financial_impact_cents == 100_000
        assert result.shortfall_cents == 0
        assert result.estimated_recovery_days == 0
        assert result.confidence_score == 88.0
        assert "Car repair" in result.explanation
        assert len(result.recommendations) >= 1


def test_resilient_boundary_at_exactly_half_safe_to_spend() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "boundary-resilient")

        create_account(
            db,
            user,
            available_balance_cents=500_000,
        )

        result = run_financial_stress_test(
            db,
            user.id,
            FinancialStressTestRequest(
                scenario_type="emergency_expense",
                scenario_name="Appliance replacement",
                stress_amount_cents=250_000,
                event_date=TEST_DATE + timedelta(days=3),
            ),
            as_of=TEST_DATE,
        )

        assert result.risk_level == "resilient"
        assert result.safe_to_spend_after_stress_cents == 250_000


def test_recurring_bill_increase_strained() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "bill-increase-strained")

        create_account(
            db,
            user,
            available_balance_cents=500_000,
        )

        result = run_financial_stress_test(
            db,
            user.id,
            FinancialStressTestRequest(
                scenario_type="recurring_bill_increase",
                scenario_name="Rent increase",
                stress_amount_cents=300_000,
                event_date=TEST_DATE + timedelta(days=5),
            ),
            as_of=TEST_DATE,
        )

        assert result.risk_level == "strained"
        assert result.safe_to_spend_after_stress_cents == 200_000
        assert result.shortfall_cents == 0
        assert result.estimated_recovery_days == 0


def test_temporary_income_loss_critical() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "income-loss-critical")

        create_account(
            db,
            user,
            available_balance_cents=500_000,
        )

        result = run_financial_stress_test(
            db,
            user.id,
            FinancialStressTestRequest(
                scenario_type="temporary_income_loss",
                scenario_name="Reduced hours",
                stress_amount_cents=600_000,
                event_date=TEST_DATE + timedelta(days=2),
                duration_days=14,
            ),
            as_of=TEST_DATE,
        )

        assert result.risk_level == "critical"
        assert result.safe_to_spend_after_stress_cents == 0
        assert result.shortfall_cents == 100_000
        assert result.estimated_recovery_days == 14
        assert result.confidence_score == 83.8


def test_temporary_income_loss_preserves_exact_entered_amount() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "income-loss-exact-amount")

        create_account(
            db,
            user,
            available_balance_cents=500_000,
        )

        result = run_financial_stress_test(
            db,
            user.id,
            FinancialStressTestRequest(
                scenario_type="temporary_income_loss",
                scenario_name="Reduced hours",
                stress_amount_cents=200_000,
                event_date=TEST_DATE + timedelta(days=2),
                duration_days=14,
            ),
            as_of=TEST_DATE,
        )

        assert result.total_financial_impact_cents == 200_000
        assert "$2,000.00" in result.explanation
        assert "$1,999" not in result.explanation


def test_emergency_expense_does_not_mention_duration() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "emergency-no-duration")

        create_account(
            db,
            user,
            available_balance_cents=500_000,
        )

        result = run_financial_stress_test(
            db,
            user.id,
            FinancialStressTestRequest(
                scenario_type="emergency_expense",
                scenario_name="Car repair",
                stress_amount_cents=100_000,
                event_date=TEST_DATE + timedelta(days=3),
            ),
            as_of=TEST_DATE,
        )

        assert result.duration_days is None
        assert "duration" not in result.explanation.lower()

        for recommendation in result.recommendations:
            assert "duration" not in recommendation.lower()


def test_recurring_bill_increase_does_not_mention_duration() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "bill-increase-no-duration")

        create_account(
            db,
            user,
            available_balance_cents=500_000,
        )

        result = run_financial_stress_test(
            db,
            user.id,
            FinancialStressTestRequest(
                scenario_type="recurring_bill_increase",
                scenario_name="Rent increase",
                stress_amount_cents=300_000,
                event_date=TEST_DATE + timedelta(days=5),
            ),
            as_of=TEST_DATE,
        )

        assert result.duration_days is None
        assert "duration" not in result.explanation.lower()

        for recommendation in result.recommendations:
            assert "duration" not in recommendation.lower()


def test_temporary_income_loss_recovery_disclaimer_not_duplicated_in_recommendations() -> (
    None
):
    with TestingSessionLocal() as db:
        user = create_user(db, "income-loss-no-dup-disclaimer")

        create_account(
            db,
            user,
            available_balance_cents=500_000,
        )

        result = run_financial_stress_test(
            db,
            user.id,
            FinancialStressTestRequest(
                scenario_type="temporary_income_loss",
                scenario_name="Reduced hours",
                stress_amount_cents=200_000,
                event_date=TEST_DATE + timedelta(days=2),
                duration_days=14,
            ),
            as_of=TEST_DATE,
        )

        for recommendation in result.recommendations:
            assert "duration" not in recommendation.lower()
            assert "recovery timeline" not in recommendation.lower()

        assert all(
            recommendation
            for recommendation in result.recommendations
        )


def test_delayed_paycheck_recovery_equals_duration() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "delayed-paycheck")

        create_account(
            db,
            user,
            available_balance_cents=500_000,
        )

        result = run_financial_stress_test(
            db,
            user.id,
            FinancialStressTestRequest(
                scenario_type="delayed_paycheck",
                scenario_name="Late direct deposit",
                stress_amount_cents=150_000,
                event_date=TEST_DATE + timedelta(days=1),
                duration_days=5,
            ),
            as_of=TEST_DATE,
        )

        assert result.risk_level == "resilient"
        assert result.estimated_recovery_days == 5


def test_respects_reserve_and_essential_spending() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "reserve")

        create_account(
            db,
            user,
            available_balance_cents=600_000,
        )

        result = run_financial_stress_test(
            db,
            user.id,
            FinancialStressTestRequest(
                scenario_type="emergency_expense",
                scenario_name="Pet emergency",
                stress_amount_cents=100_000,
                event_date=TEST_DATE + timedelta(days=4),
                safety_reserve_cents=150_000,
                essential_spending_cents=100_000,
            ),
            as_of=TEST_DATE,
        )

        assert result.safe_to_spend_before_stress_cents == 350_000
        assert result.safe_to_spend_after_stress_cents == 250_000


def test_rejects_missing_duration_for_temporary_income_loss() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "missing-duration-income")

        create_account(db, user)

        try:
            run_financial_stress_test(
                db,
                user.id,
                FinancialStressTestRequest(
                    scenario_type="temporary_income_loss",
                    scenario_name="Layoff",
                    stress_amount_cents=200_000,
                    event_date=TEST_DATE + timedelta(days=2),
                ),
                as_of=TEST_DATE,
            )
        except ValueError as exc:
            assert str(exc) == (
                "duration_days is required for the temporary "
                "income loss scenario"
            )
        else:
            raise AssertionError("expected ValueError")


def test_rejects_missing_duration_for_delayed_paycheck() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "missing-duration-paycheck")

        create_account(db, user)

        try:
            run_financial_stress_test(
                db,
                user.id,
                FinancialStressTestRequest(
                    scenario_type="delayed_paycheck",
                    scenario_name="Payroll issue",
                    stress_amount_cents=150_000,
                    event_date=TEST_DATE + timedelta(days=2),
                ),
                as_of=TEST_DATE,
            )
        except ValueError as exc:
            assert str(exc) == (
                "duration_days is required for the delayed "
                "paycheck scenario"
            )
        else:
            raise AssertionError("expected ValueError")


def test_rejects_event_date_before_calculation_date() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "past-event-date")

        create_account(db, user)

        try:
            run_financial_stress_test(
                db,
                user.id,
                FinancialStressTestRequest(
                    scenario_type="emergency_expense",
                    scenario_name="Broken laptop",
                    stress_amount_cents=100_000,
                    event_date=TEST_DATE - timedelta(days=1),
                ),
                as_of=TEST_DATE,
            )
        except ValueError as exc:
            assert str(exc) == (
                "event date cannot be before the calculation date"
            )
        else:
            raise AssertionError("expected ValueError")


def test_rejects_event_date_outside_horizon() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "outside-horizon")

        create_account(db, user)

        try:
            run_financial_stress_test(
                db,
                user.id,
                FinancialStressTestRequest(
                    scenario_type="emergency_expense",
                    scenario_name="Roof leak",
                    stress_amount_cents=100_000,
                    event_date=TEST_DATE + timedelta(days=31),
                    horizon_days=30,
                ),
                as_of=TEST_DATE,
            )
        except ValueError as exc:
            assert str(exc) == (
                "event date must fall within the selected horizon"
            )
        else:
            raise AssertionError("expected ValueError")


def test_financial_stress_test_endpoint(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client,
        "stress-test-endpoint",
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
        f"/users/{user_id}/financial-stress-test",
        headers=headers,
        json={
            "scenario_type": "emergency_expense",
            "scenario_name": "Car repair",
            "stress_amount_cents": 100_000,
            "event_date": (
                date.today() + timedelta(days=3)
            ).isoformat(),
            "safety_reserve_cents": 0,
            "essential_spending_cents": 0,
            "horizon_days": 30,
        },
    )

    assert response.status_code == 200

    payload = response.json()

    assert payload["risk_level"] == "resilient"
    assert payload["safe_to_spend_before_stress_cents"] == 500_000
    assert payload["safe_to_spend_after_stress_cents"] == 400_000
    assert payload["total_financial_impact_cents"] == 100_000
    assert payload["shortfall_cents"] == 0
    assert payload["estimated_recovery_days"] == 0
    assert len(payload["recommendations"]) >= 1
    assert payload["safe_to_spend"]["safe_to_spend_cents"] == 500_000


def test_financial_stress_test_endpoint_maps_value_error_to_422(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client,
        "stress-test-validation",
    )

    with TestingSessionLocal() as db:
        user = db.get(User, user_id)

        assert user is not None

        create_account(db, user)

    response = client.post(
        f"/users/{user_id}/financial-stress-test",
        headers=headers,
        json={
            "scenario_type": "delayed_paycheck",
            "scenario_name": "Payroll issue",
            "stress_amount_cents": 150_000,
            "event_date": (
                date.today() + timedelta(days=2)
            ).isoformat(),
            "horizon_days": 30,
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "duration_days is required for the delayed "
        "paycheck scenario"
    )


def test_financial_stress_test_endpoint_rejects_invalid_amount(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client,
        "stress-test-invalid-amount",
    )

    response = client.post(
        f"/users/{user_id}/financial-stress-test",
        headers=headers,
        json={
            "scenario_type": "emergency_expense",
            "scenario_name": "Car repair",
            "stress_amount_cents": 0,
            "event_date": (
                date.today() + timedelta(days=3)
            ).isoformat(),
        },
    )

    assert response.status_code == 422


def test_financial_stress_test_endpoint_rejects_whitespace_scenario_name(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client,
        "stress-test-blank-name",
    )

    response = client.post(
        f"/users/{user_id}/financial-stress-test",
        headers=headers,
        json={
            "scenario_type": "emergency_expense",
            "scenario_name": "   ",
            "stress_amount_cents": 100_000,
            "event_date": (
                date.today() + timedelta(days=3)
            ).isoformat(),
        },
    )

    assert response.status_code == 422


def test_financial_stress_test_endpoint_rejects_unreasonable_duration(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client,
        "stress-test-bad-duration",
    )

    response = client.post(
        f"/users/{user_id}/financial-stress-test",
        headers=headers,
        json={
            "scenario_type": "temporary_income_loss",
            "scenario_name": "Layoff",
            "stress_amount_cents": 100_000,
            "event_date": (
                date.today() + timedelta(days=3)
            ).isoformat(),
            "duration_days": 400,
        },
    )

    assert response.status_code == 422


def test_scenario_name_is_trimmed() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "trim-scenario-name")

        create_account(
            db,
            user,
            available_balance_cents=500_000,
        )

        result = run_financial_stress_test(
            db,
            user.id,
            FinancialStressTestRequest(
                scenario_type="emergency_expense",
                scenario_name="  Car repair  ",
                stress_amount_cents=100_000,
                event_date=TEST_DATE + timedelta(days=3),
            ),
            as_of=TEST_DATE,
        )

        assert result.scenario_name == "Car repair"
        assert "  Car repair  " not in result.explanation
        assert "Car repair would cost" in result.explanation


def test_duration_ignored_for_confidence_when_not_required() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "duration-ignored")

        create_account(
            db,
            user,
            available_balance_cents=500_000,
        )

        without_duration = run_financial_stress_test(
            db,
            user.id,
            FinancialStressTestRequest(
                scenario_type="emergency_expense",
                scenario_name="Car repair",
                stress_amount_cents=100_000,
                event_date=TEST_DATE + timedelta(days=3),
            ),
            as_of=TEST_DATE,
        )

        with_duration = run_financial_stress_test(
            db,
            user.id,
            FinancialStressTestRequest(
                scenario_type="emergency_expense",
                scenario_name="Car repair",
                stress_amount_cents=100_000,
                event_date=TEST_DATE + timedelta(days=3),
                duration_days=200,
            ),
            as_of=TEST_DATE,
        )

        assert (
            without_duration.confidence_score
            == with_duration.confidence_score
        )


def test_confidence_penalty_caps_at_maximum() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "confidence-cap")

        create_account(
            db,
            user,
            available_balance_cents=500_000,
        )

        result = run_financial_stress_test(
            db,
            user.id,
            FinancialStressTestRequest(
                scenario_type="temporary_income_loss",
                scenario_name="Long layoff",
                stress_amount_cents=100_000,
                event_date=TEST_DATE + timedelta(days=3),
                duration_days=200,
            ),
            as_of=TEST_DATE,
        )

        assert result.confidence_score == 58.0


def test_confidence_floors_at_zero() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "confidence-floor")

        result = run_financial_stress_test(
            db,
            user.id,
            FinancialStressTestRequest(
                scenario_type="temporary_income_loss",
                scenario_name="Long layoff",
                stress_amount_cents=100_000,
                event_date=TEST_DATE + timedelta(days=3),
                duration_days=365,
            ),
            as_of=TEST_DATE,
        )

        assert result.confidence_score == 0.0


def test_full_depletion_is_strained_not_critical() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "full-depletion")

        create_account(
            db,
            user,
            available_balance_cents=500_000,
        )

        result = run_financial_stress_test(
            db,
            user.id,
            FinancialStressTestRequest(
                scenario_type="emergency_expense",
                scenario_name="Total drain",
                stress_amount_cents=500_000,
                event_date=TEST_DATE + timedelta(days=3),
            ),
            as_of=TEST_DATE,
        )

        assert result.risk_level == "strained"
        assert result.safe_to_spend_after_stress_cents == 0
        assert result.shortfall_cents == 0


def test_financial_stress_test_endpoint_blocks_other_user(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(
        client,
        "stress-test-owner",
    )
    other_user_id, _ = register_and_login(
        client,
        "stress-test-other",
    )

    response = client.post(
        f"/users/{other_user_id}/financial-stress-test",
        headers=headers,
        json={
            "scenario_type": "emergency_expense",
            "scenario_name": "Car repair",
            "stress_amount_cents": 100_000,
            "event_date": (
                date.today() + timedelta(days=3)
            ).isoformat(),
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "you cannot access another user's data"
    )
