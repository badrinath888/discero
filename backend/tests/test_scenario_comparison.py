from datetime import date, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import FinancialAccount, PlaidItem, User
from app.schemas import (
    MajorPurchaseSimulationRequest,
    ScenarioComparisonRequest,
)
from app.services.scenario_comparison_service import (
    compare_major_purchase_scenarios,
)
from tests.conftest import TestingSessionLocal


TEST_DATE = date(2026, 8, 4)


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
