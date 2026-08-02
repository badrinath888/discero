from datetime import date

from app.models import Transaction
from app.recurring import detect_recurring


def transaction(
    posted_on: date,
    amount_cents: int = -1599,
    merchant: str = "Netflix",
    *,
    pending: bool = False,
) -> Transaction:
    return Transaction(
        user_id=1,
        posted_on=posted_on,
        description=merchant,
        merchant_name=merchant,
        amount_cents=amount_cents,
        category="Subscriptions",
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
