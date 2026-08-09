from datetime import date
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import FinancialAccount, PlaidItem, Transaction, User
from app.services.financial_resilience_service import (
    _ACTIONS_USER_PROVIDED,
    _WHAT_THIS_MEANS_USER_PROVIDED,
    evaluate_financial_resilience,
)
from tests.conftest import TestingSessionLocal


TEST_DATE = date(2026, 8, 4)


def create_user(db: Session, prefix: str = "resilience") -> User:
    user = User(
        email=f"{prefix}-{uuid4().hex}@example.com",
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
    account_type: str = "depository",
    available_balance_cents: int | None = 0,
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
        account_type=account_type,
        current_balance_cents=available_balance_cents,
        available_balance_cents=available_balance_cents,
        currency="USD",
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def seed_spending(
    db: Session,
    user: User,
    *,
    monthly_amount_cents: int = 100_000,
    months: tuple[int, ...] = (5, 6, 7),
) -> None:
    for month in months:
        db.add(
            Transaction(
                user_id=user.id,
                posted_on=date(2026, month, 15),
                description="Rent",
                amount_cents=-monthly_amount_cents,
                category="Housing",
            )
        )
    db.commit()


def register_and_login(client: TestClient, prefix: str) -> tuple[int, dict]:
    email = f"{prefix}-{uuid4().hex}@example.com"
    password = "TestPassword123!"

    create_response = client.post(
        "/users", json={"email": email, "password": password}
    )
    assert create_response.status_code == 201

    login_response = client.post(
        "/users/login", json={"email": email, "password": password}
    )
    assert login_response.status_code == 200

    return create_response.json()["id"], {
        "Authorization": f"Bearer {login_response.json()['access_token']}"
    }


def test_zero_liquid_cash_is_critical() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "zero-cash")
        create_account(db, user, available_balance_cents=0)

        result = evaluate_financial_resilience(
            db,
            user.id,
            essential_spending_cents=100_000,
            as_of=TEST_DATE,
        )

        assert result.liquid_balance_cents == 0
        assert result.runway_months == 0.0
        assert result.resilience_status == "critical"


def test_less_than_one_month_runway_is_critical() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "sub-one-month")
        create_account(db, user, available_balance_cents=50_000)

        result = evaluate_financial_resilience(
            db,
            user.id,
            essential_spending_cents=100_000,
            as_of=TEST_DATE,
        )

        assert result.runway_months == 0.5
        assert result.resilience_status == "critical"


def test_one_to_three_months_is_weak() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "weak")
        create_account(db, user, available_balance_cents=200_000)

        result = evaluate_financial_resilience(
            db,
            user.id,
            essential_spending_cents=100_000,
            as_of=TEST_DATE,
        )

        assert result.runway_months == 2.0
        assert result.resilience_status == "weak"


def test_three_to_six_months_is_fair() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "fair")
        create_account(db, user, available_balance_cents=400_000)

        result = evaluate_financial_resilience(
            db,
            user.id,
            essential_spending_cents=100_000,
            as_of=TEST_DATE,
        )

        assert result.runway_months == 4.0
        assert result.resilience_status == "fair"


def test_six_to_twelve_months_is_strong() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "strong")
        create_account(db, user, available_balance_cents=800_000)

        result = evaluate_financial_resilience(
            db,
            user.id,
            essential_spending_cents=100_000,
            as_of=TEST_DATE,
        )

        assert result.runway_months == 8.0
        assert result.resilience_status == "strong"


def test_twelve_plus_months_is_very_strong() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "very-strong")
        create_account(db, user, available_balance_cents=1_500_000)

        result = evaluate_financial_resilience(
            db,
            user.id,
            essential_spending_cents=100_000,
            as_of=TEST_DATE,
        )

        assert result.runway_months == 15.0
        assert result.resilience_status == "very_strong"


def test_band_boundaries_round_up_to_the_higher_band() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "boundary")
        create_account(db, user, available_balance_cents=300_000)

        # Exactly 1.0, 3.0, 6.0, 12.0 month ratios must land in the
        # HIGHER (safer) band, matching the documented ">=" bands.
        for essential_cents, expected_status in (
            (300_000, "weak"),  # ratio == 1.0
            (100_000, "fair"),  # ratio == 3.0
            (50_000, "strong"),  # ratio == 6.0
            (25_000, "very_strong"),  # ratio == 12.0
        ):
            result = evaluate_financial_resilience(
                db,
                user.id,
                essential_spending_cents=essential_cents,
                as_of=TEST_DATE,
            )
            assert result.resilience_status == expected_status, (
                essential_cents,
                result.resilience_status,
            )


def test_zero_essential_spending_is_safe_and_undefined_runway() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "zero-essential")
        create_account(db, user, available_balance_cents=500_000)

        result = evaluate_financial_resilience(
            db,
            user.id,
            essential_spending_cents=0,
            as_of=TEST_DATE,
        )

        assert result.monthly_essential_cents == 0
        assert result.runway_months is None
        assert result.runway_days is None
        assert result.resilience_status == "very_strong"
        assert result.essential_spending_source == "user_provided"

        for horizon in result.horizons:
            assert horizon.required_essential_cents == 0
            assert horizon.shortfall_cents == 0
            assert horizon.coverage_percent == 100.0


def test_user_provided_essential_spending_is_used_exactly() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "explicit-essential")
        create_account(db, user, available_balance_cents=1_000_000)
        # Seed spending history too -- an explicit override must win
        # over any derived figure, never blend with it.
        seed_spending(db, user, monthly_amount_cents=50_000)

        result = evaluate_financial_resilience(
            db,
            user.id,
            essential_spending_cents=400_000,
            as_of=TEST_DATE,
        )

        assert result.monthly_essential_cents == 400_000
        assert result.essential_spending_source == "user_provided"
        assert result.confidence_score == 100.0
        assert result.data_quality_note is None


def test_derived_essential_spending_from_transaction_history() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "derived-essential")
        create_account(db, user, available_balance_cents=1_000_000)
        seed_spending(db, user, monthly_amount_cents=100_000)

        result = evaluate_financial_resilience(
            db, user.id, as_of=TEST_DATE
        )

        assert result.monthly_essential_cents == 100_000
        assert result.essential_spending_source == "derived"
        assert result.months_of_spending_data == 3
        assert result.data_quality_note is None


def test_derived_essential_spending_with_no_history_warns() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "no-history")
        create_account(db, user, available_balance_cents=1_000_000)

        result = evaluate_financial_resilience(
            db, user.id, as_of=TEST_DATE
        )

        assert result.monthly_essential_cents == 0
        assert result.essential_spending_source == "derived"
        assert result.months_of_spending_data == 0
        assert result.data_quality_note is not None
        assert "No spending history" in result.data_quality_note
        assert result.data_quality_note in result.warnings


def test_derived_essential_spending_with_partial_history_is_rough() -> (
    None
):
    with TestingSessionLocal() as db:
        user = create_user(db, "partial-history")
        create_account(db, user, available_balance_cents=1_000_000)
        seed_spending(db, user, monthly_amount_cents=100_000, months=(7,))

        result = evaluate_financial_resilience(
            db, user.id, as_of=TEST_DATE
        )

        assert result.months_of_spending_data == 1
        assert result.data_quality_note is not None
        assert "rough estimate" in result.data_quality_note
        assert result.confidence_score < 90.0


def test_thirty_sixty_ninety_day_coverage_and_shortfall() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "coverage")
        create_account(db, user, available_balance_cents=100_000)

        result = evaluate_financial_resilience(
            db,
            user.id,
            essential_spending_cents=60_000,
            as_of=TEST_DATE,
        )

        by_horizon = {h.horizon_days: h for h in result.horizons}

        thirty = by_horizon[30]
        assert thirty.required_essential_cents == 60_000
        assert thirty.remaining_liquid_cents == 40_000
        assert thirty.shortfall_cents == 0
        assert thirty.coverage_percent == 100.0

        sixty = by_horizon[60]
        assert sixty.required_essential_cents == 120_000
        assert sixty.remaining_liquid_cents == 0
        assert sixty.shortfall_cents == 20_000
        assert sixty.coverage_percent == 83.3

        ninety = by_horizon[90]
        assert ninety.required_essential_cents == 180_000
        assert ninety.remaining_liquid_cents == 0
        assert ninety.shortfall_cents == 80_000
        assert ninety.coverage_percent == 55.6


def test_exact_cents_scaling_has_no_float_drift() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "precision")
        create_account(db, user, available_balance_cents=0)

        result = evaluate_financial_resilience(
            db,
            user.id,
            essential_spending_cents=333_333,
            as_of=TEST_DATE,
        )

        by_horizon = {h.horizon_days: h for h in result.horizons}
        assert by_horizon[30].required_essential_cents == 333_333
        assert by_horizon[60].required_essential_cents == 666_666
        assert by_horizon[90].required_essential_cents == 999_999

        for horizon in result.horizons:
            assert isinstance(horizon.required_essential_cents, int)
            assert isinstance(horizon.remaining_liquid_cents, int)
            assert isinstance(horizon.shortfall_cents, int)


def test_liquid_account_count_reflects_usable_accounts() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "account-count")
        create_account(db, user, available_balance_cents=100_000)
        create_account(db, user, available_balance_cents=200_000)

        result = evaluate_financial_resilience(
            db,
            user.id,
            essential_spending_cents=100_000,
            as_of=TEST_DATE,
        )

        assert result.liquid_account_count == 2
        assert result.liquid_balance_cents == 300_000


def test_non_liquid_account_excluded() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "non-liquid")
        create_account(
            db, user, account_type="investment", available_balance_cents=1_000_000
        )

        result = evaluate_financial_resilience(
            db,
            user.id,
            essential_spending_cents=100_000,
            as_of=TEST_DATE,
        )

        assert result.liquid_balance_cents == 0
        assert result.liquid_account_count == 0
        assert result.resilience_status == "critical"


# --- Router-level HTTP tests -----------------------------------------


def test_financial_resilience_endpoint_requires_authentication(
    client: TestClient,
) -> None:
    response = client.get("/users/9999/financial-resilience")
    assert response.status_code == 401


def test_financial_resilience_endpoint_blocks_other_user(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "resilience-owner")

    response = client.get(
        f"/users/{user_id + 1}/financial-resilience", headers=headers
    )

    assert response.status_code == 403


def test_financial_resilience_endpoint_returns_real_data(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "resilience-endpoint")

    response = client.get(
        f"/users/{user_id}/financial-resilience"
        "?essential_spending_cents=100000",
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["monthly_essential_cents"] == 100_000
    assert body["essential_spending_source"] == "user_provided"
    assert len(body["horizons"]) == 3


def test_financial_resilience_endpoint_rejects_negative_override(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "resilience-negative")

    response = client.get(
        f"/users/{user_id}/financial-resilience"
        "?essential_spending_cents=-100",
        headers=headers,
    )

    assert response.status_code == 422


# --- Terminology: "essential spending" only when explicitly provided -----


def test_user_provided_uses_essential_spending_terminology() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "terminology-explicit")
        create_account(db, user, available_balance_cents=400_000)

        result = evaluate_financial_resilience(
            db,
            user.id,
            essential_spending_cents=100_000,
            as_of=TEST_DATE,
        )

        assert result.spending_basis_label == "Monthly essential spending"
        assert "emergency runway" in result.headline.lower()
        assert "essential" in result.why.lower()
        # The "critical" band's copy explicitly names essential
        # spending; the mid-tier "fair" band text is generic across
        # both sources, so assert on a band that actually mentions it.
        assert "essential" in (
            _WHAT_THIS_MEANS_USER_PROVIDED["critical"].lower()
        )
        assert "essential" in (_ACTIONS_USER_PROVIDED["fair"][0].lower())


def test_derived_uses_spending_baseline_terminology_not_essential() -> (
    None
):
    with TestingSessionLocal() as db:
        user = create_user(db, "terminology-derived")
        create_account(db, user, available_balance_cents=400_000)
        seed_spending(db, user, monthly_amount_cents=100_000)

        result = evaluate_financial_resilience(
            db, user.id, as_of=TEST_DATE
        )

        assert result.spending_basis_label == "Monthly spending baseline"
        assert "spending coverage" in result.headline.lower()
        assert "emergency runway" not in result.headline.lower()

        # `headline`/`what_this_means`/`suggested_actions` may never
        # claim FinSight knows what is "essential". `why` may mention
        # "essential vs. discretionary" ONLY as part of the explicit
        # disclosure that FinSight does NOT classify them.
        never_essential = " ".join(
            [result.headline, result.what_this_means]
            + result.suggested_actions
        ).lower()
        assert "essential" not in never_essential
        assert "spending pace" in result.why.lower()
        assert "does not yet classify essential" in result.why.lower()
        assert "approximately" in result.why.lower()


def test_derived_why_matches_conservative_coverage_framing() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "terminology-framing")
        create_account(db, user, available_balance_cents=840_000)
        seed_spending(db, user, monthly_amount_cents=100_000)

        result = evaluate_financial_resilience(
            db, user.id, as_of=TEST_DATE
        )

        assert result.runway_months == 8.4
        assert "8.4 month(s)" in result.why
        assert "at your recent spending pace" in result.why
