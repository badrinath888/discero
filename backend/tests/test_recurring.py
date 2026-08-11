from datetime import date

from app.models import Transaction
from app.recurring import detect_recurring, project_occurrences


TEST_DATE = date(2026, 8, 4)


def transaction(
    posted_on: date,
    amount_cents: int = -1599,
    merchant: str = "Netflix",
    *,
    category: str = "Subscriptions",
    pending: bool = False,
) -> Transaction:
    return Transaction(
        user_id=1,
        posted_on=posted_on,
        description=merchant,
        merchant_name=merchant,
        amount_cents=amount_cents,
        category=category,
        pending=pending,
    )


def test_requires_three_completed_occurrences() -> None:
    result = detect_recurring(
        [
            transaction(date(2026, 6, 1)),
            transaction(date(2026, 7, 1)),
        ],
        as_of=date(2026, 7, 2),
    )

    assert result == []


def test_ignores_pending_transactions() -> None:
    result = detect_recurring(
        [
            transaction(date(2026, 5, 1)),
            transaction(date(2026, 6, 1)),
            transaction(date(2026, 7, 1)),
            transaction(date(2026, 7, 31), pending=True),
        ],
        as_of=date(2026, 7, 2),
    )

    assert len(result) == 1
    assert result[0]["occurrences"] == 3
    assert result[0]["last_payment"] == date(2026, 7, 1)


def test_tolerates_one_irregular_interval() -> None:
    result = detect_recurring(
        [
            transaction(date(2026, 2, 1)),
            transaction(date(2026, 3, 1)),
            transaction(date(2026, 4, 1)),
            transaction(date(2026, 5, 15)),
            transaction(date(2026, 6, 15)),
        ],
        as_of=date(2026, 6, 16),
    )

    assert len(result) == 1
    assert result[0]["frequency"] == "Monthly"


def test_detects_normal_month_length_variation() -> None:
    result = detect_recurring(
        [
            transaction(date(2026, 1, 31)),
            transaction(date(2026, 2, 28)),
            transaction(date(2026, 3, 31)),
            transaction(date(2026, 4, 30)),
        ],
        as_of=date(2026, 5, 1),
    )

    assert len(result) == 1
    assert result[0]["frequency"] == "Monthly"
    assert result[0]["occurrences"] == 4


def test_normalizes_changing_reference_numbers() -> None:
    result = detect_recurring(
        [
            transaction(
                date(2026, 5, 5),
                merchant="Spotify 92831",
            ),
            transaction(
                date(2026, 6, 5),
                merchant="Spotify 18442",
            ),
            transaction(
                date(2026, 7, 5),
                merchant="Spotify 77390",
            ),
        ],
        as_of=date(2026, 7, 6),
    )

    assert len(result) == 1
    assert result[0]["merchant"] == "Spotify"


def test_ordinary_monthly_dining_habit_is_not_suggested_as_recurring() -> (
    None
):
    # Same interval/amount regularity a genuine bill has -- the only
    # thing that should stop this from being suggested is that Dining
    # isn't a predictable-obligation category.
    result = detect_recurring(
        [
            transaction(
                date(2026, 5, 12),
                -3400,
                merchant="Sweetgreen",
                category="Dining",
            ),
            transaction(
                date(2026, 6, 12),
                -3400,
                merchant="Sweetgreen",
                category="Dining",
            ),
            transaction(
                date(2026, 7, 12),
                -3400,
                merchant="Sweetgreen",
                category="Dining",
            ),
        ],
        as_of=date(2026, 7, 13),
    )

    assert result == []


def test_ordinary_monthly_shopping_habit_is_not_suggested_as_recurring() -> (
    None
):
    result = detect_recurring(
        [
            transaction(
                date(2026, 5, 25),
                -4230,
                merchant="Target",
                category="Shopping",
            ),
            transaction(
                date(2026, 6, 25),
                -4230,
                merchant="Target",
                category="Shopping",
            ),
            transaction(
                date(2026, 7, 25),
                -4230,
                merchant="Target",
                category="Shopping",
            ),
        ],
        as_of=date(2026, 7, 26),
    )

    assert result == []


def test_genuine_bill_categories_still_detected_as_recurring() -> None:
    # Housing, Utilities, and Subscriptions -- the obligation-eligible
    # categories -- must still clear detection with the same strong
    # evidence a real bill has.
    for category, merchant in (
        ("Housing", "Skyline Ridge Apartments"),
        ("Utilities", "Geico"),
        ("Subscriptions", "Netflix"),
    ):
        result = detect_recurring(
            [
                transaction(
                    date(2026, 5, 8),
                    -14200,
                    merchant=merchant,
                    category=category,
                ),
                transaction(
                    date(2026, 6, 8),
                    -14200,
                    merchant=merchant,
                    category=category,
                ),
                transaction(
                    date(2026, 7, 8),
                    -14200,
                    merchant=merchant,
                    category=category,
                ),
            ],
            as_of=date(2026, 7, 9),
        )

        assert len(result) == 1, category
        assert result[0]["merchant"] == merchant.title()


def test_detects_price_increase_warning() -> None:
    result = detect_recurring(
        [
            transaction(date(2026, 4, 10), -1000),
            transaction(date(2026, 5, 10), -1000),
            transaction(date(2026, 6, 10), -1000),
            transaction(date(2026, 7, 10), -1200),
        ],
        as_of=date(2026, 7, 11),
    )

    assert len(result) == 1
    assert result[0]["price_change_percent"] == 20.0
    assert result[0]["price_change_warning"] is True


# --- project_occurrences (30/60/90-day recurrence projection) -----------


def test_monthly_bill_in_thirty_day_horizon() -> None:
    occurrences = project_occurrences(
        date(2026, 8, 10),
        "Monthly",
        as_of=TEST_DATE,
        through_date=date(2026, 9, 3),  # +30 days
    )

    assert occurrences == [date(2026, 8, 10)]


def test_monthly_bill_in_sixty_day_horizon() -> None:
    occurrences = project_occurrences(
        date(2026, 8, 10),
        "Monthly",
        as_of=TEST_DATE,
        through_date=date(2026, 10, 3),  # +60 days
    )

    assert occurrences == [date(2026, 8, 10), date(2026, 9, 10)]


def test_monthly_bill_in_ninety_day_horizon() -> None:
    occurrences = project_occurrences(
        date(2026, 8, 10),
        "Monthly",
        as_of=TEST_DATE,
        through_date=date(2026, 11, 2),  # +90 days
    )

    assert occurrences == [
        date(2026, 8, 10),
        date(2026, 9, 10),
        date(2026, 10, 10),
    ]


def test_weekly_bill_occurrences_over_thirty_days() -> None:
    occurrences = project_occurrences(
        date(2026, 8, 6),
        "Weekly",
        as_of=TEST_DATE,
        through_date=date(2026, 9, 3),  # +30 days
    )

    assert occurrences == [
        date(2026, 8, 6),
        date(2026, 8, 13),
        date(2026, 8, 20),
        date(2026, 8, 27),
        date(2026, 9, 3),
    ]


def test_biweekly_bill_occurrences_over_sixty_days() -> None:
    occurrences = project_occurrences(
        date(2026, 8, 5),
        "Biweekly",
        as_of=TEST_DATE,
        through_date=date(2026, 10, 3),  # +60 days
    )

    assert occurrences == [
        date(2026, 8, 5),
        date(2026, 8, 19),
        date(2026, 9, 2),
        date(2026, 9, 16),
        date(2026, 9, 30),
    ]


def test_next_occurrence_just_outside_horizon_is_excluded() -> None:
    occurrences = project_occurrences(
        date(2026, 9, 5),  # 32 days out
        "Monthly",
        as_of=TEST_DATE,
        through_date=date(2026, 9, 3),  # +30 days
    )

    assert occurrences == []


def test_occurrence_exactly_on_horizon_boundary_is_included() -> None:
    # The weekly test above already lands exactly on day 30 (Sep 3);
    # this asserts that inclusion explicitly and in isolation.
    occurrences = project_occurrences(
        date(2026, 9, 3),
        "Monthly",
        as_of=TEST_DATE,
        through_date=date(2026, 9, 3),
    )

    assert occurrences == [date(2026, 9, 3)]


def test_no_double_counting_all_occurrences_unique_and_ordered() -> None:
    occurrences = project_occurrences(
        date(2026, 8, 6),
        "Weekly",
        as_of=TEST_DATE,
        through_date=date(2026, 11, 2),  # +90 days
    )

    assert len(occurrences) == len(set(occurrences))
    assert occurrences == sorted(occurrences)
    assert len(occurrences) == 13


def test_unsupported_frequency_falls_back_to_single_known_date() -> None:
    # Never fabricate a cadence for a frequency the app doesn't
    # actually detect or accept.
    occurrences = project_occurrences(
        date(2026, 8, 20),
        "Quarterly",
        as_of=TEST_DATE,
        through_date=date(2026, 11, 2),
    )

    assert occurrences == [date(2026, 8, 20)]


def test_unsupported_frequency_excluded_when_out_of_range() -> None:
    occurrences = project_occurrences(
        date(2026, 12, 1),
        "Quarterly",
        as_of=TEST_DATE,
        through_date=date(2026, 11, 2),
    )

    assert occurrences == []


def test_next_payment_before_as_of_is_not_projected_backwards() -> None:
    # A stale next_payment (e.g. sync lag) should never yield an
    # occurrence dated before the calculation window starts.
    occurrences = project_occurrences(
        date(2026, 7, 20),  # before TEST_DATE
        "Weekly",
        as_of=TEST_DATE,
        through_date=date(2026, 8, 11),
    )

    assert all(occurrence >= TEST_DATE for occurrence in occurrences)
    assert occurrences == [date(2026, 8, 10)]
