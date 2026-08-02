import re
from calendar import monthrange
from collections import defaultdict
from datetime import date, timedelta
from statistics import median

from app.models import Transaction


def _merchant(transaction: Transaction) -> str:
    raw_name = (
        transaction.merchant_name
        or transaction.description
    )

    normalized = re.sub(r"\d+", "", raw_name.upper())
    normalized = re.sub(r"[^A-Z ]", " ", normalized)

    return " ".join(normalized.split())


def _frequency(
    intervals: list[int],
) -> tuple[str, int] | None:
    ranges = (
        ("Weekly", 7, 5, 9),
        ("Biweekly", 14, 11, 17),
        ("Monthly", 30, 24, 38),
    )

    allowed_misses = 1 if len(intervals) >= 4 else 0

    for name, expected_days, minimum, maximum in ranges:
        matching = sum(
            minimum <= interval <= maximum
            for interval in intervals
        )

        typical_interval = round(median(intervals))

        if (
            matching >= len(intervals) - allowed_misses
            and minimum <= typical_interval <= maximum
        ):
            return name, expected_days

    return None


def _confidence_score(
    intervals: list[int],
    amounts: list[int],
    expected_interval: int,
) -> float:
    average_amount = sum(amounts) / len(amounts)

    interval_error = (
        sum(
            min(
                abs(interval - expected_interval),
                expected_interval,
            )
            for interval in intervals
        )
        / len(intervals)
    )

    amount_error = (
        sum(
            abs(amount - average_amount)
            for amount in amounts
        )
        / len(amounts)
    )

    interval_score = max(
        0.0,
        1 - interval_error / expected_interval,
    )

    amount_score = max(
        0.0,
        1 - amount_error / max(average_amount, 1),
    )

    occurrence_score = min(
        1.0,
        len(amounts) / 4,
    )

    score = (
        interval_score * 0.45
        + amount_score * 0.35
        + occurrence_score * 0.20
    )

    return round(score * 100, 1)


def _next_payment_date(
    last_payment: date,
    frequency: str,
    expected_interval: int,
) -> date:
    if frequency != "Monthly":
        return last_payment + timedelta(days=expected_interval)

    if last_payment.month == 12:
        year = last_payment.year + 1
        month = 1
    else:
        year = last_payment.year
        month = last_payment.month + 1

    day = min(
        last_payment.day,
        monthrange(year, month)[1],
    )

    return date(year, month, day)


def detect_recurring(
    transactions: list[Transaction],
    as_of: date | None = None,
) -> list[dict]:
    groups: dict[str, list[Transaction]] = defaultdict(list)

    for transaction in transactions:
        merchant = _merchant(transaction)

        if (
            transaction.amount_cents < 0
            and not transaction.pending
            and merchant
        ):
            groups[merchant].append(transaction)

    today = as_of or date.today()
    recurring: list[dict] = []

    for merchant, items in groups.items():
        items.sort(key=lambda item: item.posted_on)

        if len(items) < 3:
            continue

        intervals = [
            (current.posted_on - previous.posted_on).days
            for previous, current in zip(items, items[1:])
        ]

        frequency_result = _frequency(intervals)

        if frequency_result is None:
            continue

        frequency, expected_interval = frequency_result

        amounts = [
            abs(item.amount_cents)
            for item in items
        ]

        average_amount = round(
            sum(amounts) / len(amounts)
        )

        amount_tolerance = max(
            100,
            round(average_amount * 0.20),
        )

        if any(
            abs(amount - average_amount) > amount_tolerance
            for amount in amounts
        ):
            continue

        previous_average = round(
            sum(amounts[:-1]) / len(amounts[:-1])
        )

        latest_amount = amounts[-1]

        price_change_percent = (
            round(
                (
                    latest_amount - previous_average
                )
                / previous_average
                * 100,
                1,
            )
            if previous_average
            else 0.0
        )

        price_change_warning = (
            abs(latest_amount - previous_average) >= 100
            and abs(price_change_percent) >= 10
        )

        next_payment = _next_payment_date(
            items[-1].posted_on,
            frequency,
            expected_interval,
        )

        recurring.append(
            {
                "merchant": merchant.title(),
                "amount_cents": average_amount,
                "frequency": frequency,
                "last_payment": items[-1].posted_on,
                "next_payment": next_payment,
                "days_until_due": (
                    next_payment - today
                ).days,
                "occurrences": len(items),
                "confidence_score": _confidence_score(
                    intervals,
                    amounts,
                    expected_interval,
                ),
                "price_change_percent": price_change_percent,
                "price_change_warning": price_change_warning,
            }
        )

    return sorted(
        recurring,
        key=lambda item: (
            int(item["days_until_due"]),
            -int(item["amount_cents"]),
        ),
    )
