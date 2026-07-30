import re
from collections import defaultdict
from datetime import date

from app.models import Transaction


def _merchant(description: str) -> str:
    normalized = re.sub(r"\d+", "", description.upper())
    normalized = re.sub(r"[^A-Z ]", " ", normalized)
    return " ".join(normalized.split())


def detect_recurring(
    transactions: list[Transaction],
) -> list[dict[str, int | str | date]]:
    groups: dict[str, list[Transaction]] = defaultdict(list)

    for transaction in transactions:
        merchant = _merchant(transaction.description)

        if transaction.amount_cents < 0 and merchant:
            groups[merchant].append(transaction)

    recurring = []

    for merchant, items in groups.items():
        items.sort(key=lambda item: item.posted_on)

        if len(items) < 2:
            continue

        intervals = [
            (current.posted_on - previous.posted_on).days
            for previous, current in zip(items, items[1:])
        ]

        amounts = [abs(item.amount_cents) for item in items]
        average = round(sum(amounts) / len(amounts))
        tolerance = max(100, round(average * 0.1))

        monthly = all(20 <= interval <= 40 for interval in intervals)
        consistent = all(
            abs(amount - average) <= tolerance
            for amount in amounts
        )

        if not monthly or not consistent:
            continue

        recurring.append(
            {
                "merchant": merchant.title(),
                "amount_cents": average,
                "frequency": "Monthly",
                "last_payment": items[-1].posted_on,
                "occurrences": len(items),
            }
        )

    return sorted(
        recurring,
        key=lambda item: int(item["amount_cents"]),
        reverse=True,
    )