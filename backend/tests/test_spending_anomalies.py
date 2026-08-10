from datetime import date, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import FinancialAccount, PlaidItem, Transaction, User
from app.services.spending_anomaly_service import detect_spending_anomalies
from tests.conftest import TestingSessionLocal


TEST_DATE = date(2026, 8, 9)


def create_user(
    db: Session,
    email_prefix: str = "anomaly",
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


def create_account(db: Session, user: User) -> FinancialAccount:
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
        current_balance_cents=500_000,
        available_balance_cents=500_000,
        currency="USD",
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def create_transaction(
    db: Session,
    user: User,
    *,
    posted_on: date,
    amount_cents: int,
    merchant_name: str,
    category: str = "Shopping",
    pending: bool = False,
) -> Transaction:
    transaction = Transaction(
        user_id=user.id,
        posted_on=posted_on,
        description=merchant_name,
        merchant_name=merchant_name,
        amount_cents=amount_cents,
        category=category,
        pending=pending,
    )
    db.add(transaction)
    db.commit()
    db.refresh(transaction)
    return transaction


def register_and_login(
    client: TestClient,
    prefix: str,
) -> tuple[int, dict[str, str]]:
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


def _fill_baseline(
    db: Session,
    user: User,
    *,
    count: int,
    start: date,
    merchant_prefix: str = "Filler Merchant",
    amount_cents: int = -1_000,
) -> None:
    """Unrelated filler transactions -- spread across distinct merchants
    so they never accidentally trip the merchant-level or repeated-
    charge detectors, only used to clear the overall minimum-sample
    gate."""
    for i in range(count):
        create_transaction(
            db,
            user,
            posted_on=start + timedelta(days=i * 3),
            amount_cents=amount_cents,
            merchant_name=f"{merchant_prefix} {i}",
            category="Misc",
        )


def test_normal_transaction_not_flagged() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "normal")
        create_account(db, user)

        # All within the same completed month so this can never also
        # register as a (separate, unrelated) category spike -- fewer
        # than the 2 completed months that detector requires.
        for i, amount in enumerate([4_500, 5_000, 5_500, 4_800, 5_200]):
            create_transaction(
                db,
                user,
                posted_on=date(2026, 3, 1) + timedelta(days=i * 4),
                amount_cents=-amount,
                merchant_name="Whole Foods",
                category="Groceries",
            )
        # A recent charge well within the normal range.
        create_transaction(
            db,
            user,
            posted_on=TEST_DATE - timedelta(days=2),
            amount_cents=-5_100,
            merchant_name="Whole Foods",
            category="Groceries",
        )
        _fill_baseline(db, user, count=5, start=date(2026, 2, 10))

        result = detect_spending_anomalies(db, user.id, as_of=TEST_DATE)

        assert result.anomalies == []


def test_large_merchant_deviation_flagged() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "merchant-deviation")
        create_account(db, user)

        for i, amount in enumerate([4_800, 5_000, 5_200, 4_900, 5_100]):
            create_transaction(
                db,
                user,
                posted_on=date(2026, 3, 1) + timedelta(days=i * 20),
                amount_cents=-amount,
                merchant_name="Whole Foods",
                category="Groceries",
            )
        create_transaction(
            db,
            user,
            posted_on=TEST_DATE - timedelta(days=4),
            amount_cents=-40_000,
            merchant_name="Whole Foods",
            category="Groceries",
        )
        _fill_baseline(db, user, count=5, start=date(2026, 2, 10))

        result = detect_spending_anomalies(db, user.id, as_of=TEST_DATE)

        merchant_anomalies = [
            a for a in result.anomalies if a.type == "merchant_unusual_spend"
        ]
        assert len(merchant_anomalies) == 1
        anomaly = merchant_anomalies[0]
        assert anomaly.severity in ("warning", "high")
        assert anomaly.current_amount_cents == 40_000
        assert anomaly.baseline_amount_cents == 5_000
        assert anomaly.difference_cents == 35_000
        assert anomaly.category == "Groceries"
        assert anomaly.merchant == "Whole Foods"


def test_category_spike_flagged() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "category-spike")
        create_account(db, user)

        for month in (5, 6, 7):
            create_transaction(
                db,
                user,
                posted_on=date(2026, month, 3),
                amount_cents=-20_000,
                merchant_name="Restaurant",
                category="Dining",
            )
        # Current month (August) already at $150 by day 9 across two
        # transactions -- paced out across the full month that's well
        # above the $200 baseline. Two transactions (not one) so this
        # clears the min-current-transactions guard.
        create_transaction(
            db,
            user,
            posted_on=date(2026, 8, 3),
            amount_cents=-10_000,
            merchant_name="Restaurant",
            category="Dining",
        )
        create_transaction(
            db,
            user,
            posted_on=date(2026, 8, 5),
            amount_cents=-5_000,
            merchant_name="Restaurant",
            category="Dining",
        )
        _fill_baseline(db, user, count=7, start=date(2026, 2, 10))

        result = detect_spending_anomalies(db, user.id, as_of=TEST_DATE)

        spikes = [a for a in result.anomalies if a.type == "category_spike"]
        assert len(spikes) == 1
        spike = spikes[0]
        assert spike.category == "Dining"
        assert spike.baseline_amount_cents == 20_000
        assert spike.severity == "high"
        assert spike.percent_difference is not None
        assert spike.percent_difference >= 100.0


def test_category_spike_wording_is_pace_based_and_distinguishes_actual() -> (
    None
):
    with TestingSessionLocal() as db:
        user = create_user(db, "category-spike-wording")
        create_account(db, user)

        for month in (5, 6, 7):
            create_transaction(
                db,
                user,
                posted_on=date(2026, month, 3),
                amount_cents=-20_000,
                merchant_name="Restaurant",
                category="Dining",
            )
        create_transaction(
            db,
            user,
            posted_on=date(2026, 8, 3),
            amount_cents=-10_000,
            merchant_name="Restaurant",
            category="Dining",
        )
        create_transaction(
            db,
            user,
            posted_on=date(2026, 8, 5),
            amount_cents=-5_000,
            merchant_name="Restaurant",
            category="Dining",
        )
        _fill_baseline(db, user, count=7, start=date(2026, 2, 10))

        result = detect_spending_anomalies(db, user.id, as_of=TEST_DATE)

        spike = next(
            a for a in result.anomalies if a.type == "category_spike"
        )

        # Explicit pace/projection language, never a bare "you spent
        # X% more this month" claim built from the prorated figure.
        assert "current pace" in spike.title.lower()
        assert "current pace" in spike.reason.lower()
        assert "projec" in spike.reason.lower()
        assert "you spent x%" not in spike.reason.lower()
        assert "you spent 158% more" not in spike.reason.lower()

        # Actual spend-to-date ($150.00) and the projected month-end
        # total ($516.67-ish) must both appear, and be distinct.
        assert "$150.00" in spike.reason
        assert "$150.00" != f"{spike.current_amount_cents / 100:,.2f}"
        projected_display = f"${spike.current_amount_cents / 100:,.2f}"
        assert projected_display in spike.reason
        assert "$150.00" not in projected_display


def test_category_spike_not_triggered_too_early_in_month() -> None:
    # Only 2 days into the month -- far too little data for a
    # month-end projection to mean anything, regardless of how large
    # the one transaction is.
    with TestingSessionLocal() as db:
        user = create_user(db, "category-spike-too-early")
        create_account(db, user)
        as_of = date(2026, 8, 2)

        for month in (5, 6, 7):
            create_transaction(
                db,
                user,
                posted_on=date(2026, month, 3),
                amount_cents=-20_000,
                merchant_name="Restaurant",
                category="Dining",
            )
        create_transaction(
            db,
            user,
            posted_on=date(2026, 8, 1),
            amount_cents=-30_000,
            merchant_name="Restaurant",
            category="Dining",
        )
        _fill_baseline(db, user, count=8, start=date(2026, 2, 10))

        result = detect_spending_anomalies(db, user.id, as_of=as_of)

        assert [
            a for a in result.anomalies if a.type == "category_spike"
        ] == []


def test_category_spike_not_triggered_by_single_early_transaction() -> None:
    # Elapsed days are fine, but a single large transaction is not
    # enough of a sample to prorate into a confident spike signal.
    with TestingSessionLocal() as db:
        user = create_user(db, "category-spike-single-txn")
        create_account(db, user)

        for month in (5, 6, 7):
            create_transaction(
                db,
                user,
                posted_on=date(2026, month, 3),
                amount_cents=-20_000,
                merchant_name="Restaurant",
                category="Dining",
            )
        create_transaction(
            db,
            user,
            posted_on=date(2026, 8, 5),
            amount_cents=-15_000,
            merchant_name="Restaurant",
            category="Dining",
        )
        _fill_baseline(db, user, count=7, start=date(2026, 2, 10))

        result = detect_spending_anomalies(db, user.id, as_of=TEST_DATE)

        assert [
            a for a in result.anomalies if a.type == "category_spike"
        ] == []


def test_large_individual_transaction_flagged() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "large-transaction")
        create_account(db, user)

        for i in range(10):
            create_transaction(
                db,
                user,
                posted_on=date(2026, 3, 1) + timedelta(days=i * 5),
                amount_cents=-(2_000 + i * 50),
                merchant_name=f"Everyday Merchant {i}",
                category="Shopping",
            )
        create_transaction(
            db,
            user,
            posted_on=TEST_DATE - timedelta(days=3),
            amount_cents=-60_000,
            merchant_name="Electronics Outlet",
            category="Shopping",
        )

        result = detect_spending_anomalies(db, user.id, as_of=TEST_DATE)

        large = [a for a in result.anomalies if a.type == "large_transaction"]
        assert len(large) == 1
        assert large[0].current_amount_cents == 60_000
        assert large[0].merchant == "Electronics Outlet"


def test_repeated_similar_charge_flagged() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "repeated-charge")
        create_account(db, user)

        create_transaction(
            db,
            user,
            posted_on=TEST_DATE - timedelta(days=2),
            amount_cents=-2_500,
            merchant_name="Coffee Shop",
            category="Dining",
        )
        create_transaction(
            db,
            user,
            posted_on=TEST_DATE - timedelta(days=2),
            amount_cents=-2_500,
            merchant_name="Coffee Shop",
            category="Dining",
        )

        _fill_baseline(
            db,
            user,
            count=8,
            start=date(2026, 2, 10),
        )

        result = detect_spending_anomalies(
            db,
            user.id,
            as_of=TEST_DATE,
        )

        repeated = [
            anomaly
            for anomaly in result.anomalies
            if anomaly.type == "repeated_charge"
        ]

        assert len(repeated) == 1

        anomaly = repeated[0]

        assert anomaly.severity == "high"
        assert anomaly.current_amount_cents == 2_500
        assert anomaly.baseline_amount_cents == 2_500
        assert anomaly.confidence == "high"


def test_multiple_repeated_charges_are_grouped_into_one_anomaly() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "grouped-repeated-charge")
        create_account(db, user)

        for _ in range(4):
            create_transaction(
                db,
                user,
                posted_on=TEST_DATE - timedelta(days=2),
                amount_cents=-8_940,
                merchant_name="Fun",
                category="Entertainment",
            )

        _fill_baseline(db, user, count=8, start=date(2026, 2, 10))

        result = detect_spending_anomalies(
            db,
            user.id,
            as_of=TEST_DATE,
        )

        repeated = [
            anomaly
            for anomaly in result.anomalies
            if anomaly.type == "repeated_charge"
        ]

        assert len(repeated) == 1

        anomaly = repeated[0]

        assert anomaly.merchant == "Fun"
        assert anomaly.current_amount_cents == 8_940
        assert anomaly.baseline_amount_cents == 8_940
        assert anomaly.severity == "high"
        assert anomaly.confidence == "high"
        assert anomaly.occurrence_count == 4
        assert anomaly.transaction_ids is not None
        assert len(anomaly.transaction_ids) == 4
        assert len(set(anomaly.transaction_ids)) == 4
        assert "4 similar charges" in anomaly.reason
        assert "$89.40" in anomaly.reason


def test_repeated_charge_reversed_insertion_order_still_one_anomaly() -> (
    None
):
    # The later-dated transaction is inserted into the DB FIRST --
    # detection must sort by date internally, not rely on insertion/
    # row order, so this still collapses into exactly one anomaly.
    with TestingSessionLocal() as db:
        user = create_user(db, "reversed-order")
        create_account(db, user)

        create_transaction(
            db,
            user,
            posted_on=TEST_DATE - timedelta(days=1),
            amount_cents=-8_940,
            merchant_name="Fun",
            category="Entertainment",
        )
        create_transaction(
            db,
            user,
            posted_on=TEST_DATE - timedelta(days=2),
            amount_cents=-8_940,
            merchant_name="Fun",
            category="Entertainment",
        )
        _fill_baseline(db, user, count=8, start=date(2026, 2, 10))

        result = detect_spending_anomalies(db, user.id, as_of=TEST_DATE)

        repeated = [
            a for a in result.anomalies if a.type == "repeated_charge"
        ]
        assert len(repeated) == 1
        assert repeated[0].occurrence_count == 2


def test_distinct_repeated_charge_pairs_each_produce_their_own_anomaly() -> (
    None
):
    # Two genuinely separate duplicate-charge incidents (different
    # merchants) must each be reported -- deduplication must never
    # collapse real, distinct signals into one.
    with TestingSessionLocal() as db:
        user = create_user(db, "distinct-pairs")
        create_account(db, user)

        for posted_on in (
            TEST_DATE - timedelta(days=2),
            TEST_DATE - timedelta(days=2),
        ):
            create_transaction(
                db,
                user,
                posted_on=posted_on,
                amount_cents=-8_940,
                merchant_name="Fun",
                category="Entertainment",
            )
        for posted_on in (
            TEST_DATE - timedelta(days=5),
            TEST_DATE - timedelta(days=5),
        ):
            create_transaction(
                db,
                user,
                posted_on=posted_on,
                amount_cents=-3_200,
                merchant_name="Rideshare",
                category="Transportation",
            )
        _fill_baseline(db, user, count=8, start=date(2026, 2, 10))

        result = detect_spending_anomalies(db, user.id, as_of=TEST_DATE)

        repeated = [
            a for a in result.anomalies if a.type == "repeated_charge"
        ]
        assert len(repeated) == 2
        merchants = {a.merchant for a in repeated}
        assert merchants == {"Fun", "Rideshare"}
        assert len({a.id for a in repeated}) == 2


def test_repeated_charge_not_flagged_days_apart() -> None:
    # Two genuinely separate grocery runs a few days apart -- normal
    # behavior, must never be treated as a duplicate charge.
    with TestingSessionLocal() as db:
        user = create_user(db, "not-repeated")
        create_account(db, user)

        create_transaction(
            db,
            user,
            posted_on=TEST_DATE - timedelta(days=6),
            amount_cents=-5_000,
            merchant_name="Whole Foods",
            category="Groceries",
        )
        create_transaction(
            db,
            user,
            posted_on=TEST_DATE - timedelta(days=3),
            amount_cents=-5_000,
            merchant_name="Whole Foods",
            category="Groceries",
        )
        _fill_baseline(db, user, count=8, start=date(2026, 2, 10))

        result = detect_spending_anomalies(db, user.id, as_of=TEST_DATE)

        assert [a for a in result.anomalies if a.type == "repeated_charge"] == []


def test_insufficient_history_returns_no_anomalies() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "insufficient")
        create_account(db, user)

        for i in range(4):
            create_transaction(
                db,
                user,
                posted_on=TEST_DATE - timedelta(days=i),
                amount_cents=-1_000,
                merchant_name=f"Merchant {i}",
            )

        result = detect_spending_anomalies(db, user.id, as_of=TEST_DATE)

        assert result.anomalies == []
        assert result.data_quality_note is not None


def test_small_noisy_deviation_ignored() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "noisy")
        create_account(db, user)

        # All within the same completed month -- see
        # test_normal_transaction_not_flagged for why.
        for i, amount in enumerate([4_500, 5_000, 5_500, 4_800, 5_200]):
            create_transaction(
                db,
                user,
                posted_on=date(2026, 3, 1) + timedelta(days=i * 4),
                amount_cents=-amount,
                merchant_name="Whole Foods",
                category="Groceries",
            )
        create_transaction(
            db,
            user,
            posted_on=TEST_DATE - timedelta(days=2),
            amount_cents=-6_000,
            merchant_name="Whole Foods",
            category="Groceries",
        )
        _fill_baseline(db, user, count=5, start=date(2026, 2, 10))

        result = detect_spending_anomalies(db, user.id, as_of=TEST_DATE)

        assert result.anomalies == []


def test_severity_warning_boundary() -> None:
    # MAD-zero fallback path: an identical baseline plus a candidate
    # 52% above it (>= the 50% floor, < the 100% "high" cutoff).
    with TestingSessionLocal() as db:
        user = create_user(db, "severity-warning")
        create_account(db, user)

        for i in range(5):
            create_transaction(
                db,
                user,
                posted_on=date(2026, 3, 1) + timedelta(days=i * 20),
                amount_cents=-5_000,
                merchant_name="Corner Store",
                category="Shopping",
            )
        create_transaction(
            db,
            user,
            posted_on=TEST_DATE - timedelta(days=2),
            amount_cents=-7_600,
            merchant_name="Corner Store",
            category="Shopping",
        )
        _fill_baseline(db, user, count=5, start=date(2026, 2, 10))

        result = detect_spending_anomalies(db, user.id, as_of=TEST_DATE)

        merchant_anomalies = [
            a for a in result.anomalies if a.type == "merchant_unusual_spend"
        ]
        assert len(merchant_anomalies) == 1
        assert merchant_anomalies[0].severity == "warning"


def test_severity_high_boundary() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "severity-high")
        create_account(db, user)

        for i in range(5):
            create_transaction(
                db,
                user,
                posted_on=date(2026, 3, 1) + timedelta(days=i * 20),
                amount_cents=-5_000,
                merchant_name="Corner Store",
                category="Shopping",
            )
        create_transaction(
            db,
            user,
            posted_on=TEST_DATE - timedelta(days=2),
            amount_cents=-11_000,
            merchant_name="Corner Store",
            category="Shopping",
        )
        _fill_baseline(db, user, count=5, start=date(2026, 2, 10))

        result = detect_spending_anomalies(db, user.id, as_of=TEST_DATE)

        merchant_anomalies = [
            a for a in result.anomalies if a.type == "merchant_unusual_spend"
        ]
        assert len(merchant_anomalies) == 1
        assert merchant_anomalies[0].severity == "high"


def test_anomalies_are_user_scoped() -> None:
    with TestingSessionLocal() as db:
        user_a = create_user(db, "isolation-a")
        user_b = create_user(db, "isolation-b")
        create_account(db, user_a)
        create_account(db, user_b)

        for i, amount in enumerate([4_800, 5_000, 5_200, 4_900, 5_100]):
            create_transaction(
                db,
                user_a,
                posted_on=date(2026, 3, 1) + timedelta(days=i * 20),
                amount_cents=-amount,
                merchant_name="Whole Foods",
                category="Groceries",
            )
        create_transaction(
            db,
            user_a,
            posted_on=TEST_DATE - timedelta(days=2),
            amount_cents=-40_000,
            merchant_name="Whole Foods",
            category="Groceries",
        )
        _fill_baseline(db, user_a, count=5, start=date(2026, 2, 10))
        _fill_baseline(db, user_b, count=12, start=date(2026, 2, 10))

        result_a = detect_spending_anomalies(db, user_a.id, as_of=TEST_DATE)
        result_b = detect_spending_anomalies(db, user_b.id, as_of=TEST_DATE)

        assert len(result_a.anomalies) >= 1
        assert result_b.anomalies == []


def test_spending_anomalies_endpoint_requires_authentication(
    client: TestClient,
) -> None:
    response = client.get("/users/1/spending-anomalies")
    assert response.status_code == 401


def test_spending_anomalies_endpoint_blocks_other_user(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "anomaly-owner")
    other_user_id, _ = register_and_login(client, "anomaly-other")

    response = client.get(
        f"/users/{other_user_id}/spending-anomalies",
        headers=headers,
    )

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "you cannot access another user's data"
    )


def test_spending_anomalies_endpoint_validates_query_params(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "anomaly-validation")

    too_far = client.get(
        f"/users/{user_id}/spending-anomalies?lookback_months=25",
        headers=headers,
    )
    assert too_far.status_code == 422

    zero_lookback = client.get(
        f"/users/{user_id}/spending-anomalies?lookback_months=0",
        headers=headers,
    )
    assert zero_lookback.status_code == 422

    too_high_limit = client.get(
        f"/users/{user_id}/spending-anomalies?limit=101",
        headers=headers,
    )
    assert too_high_limit.status_code == 422


def test_spending_anomalies_endpoint_returns_real_data(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "anomaly-real")

    response = client.get(
        f"/users/{user_id}/spending-anomalies",
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["anomalies"] == []
    assert payload["data_quality_note"] is not None
