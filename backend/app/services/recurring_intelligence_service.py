"""Deterministic Recurring-Payment Intelligence.

Surfaces signals about the user's ACTIVE recurring items (status ==
"active", the same filter Safe-to-Spend uses) by cross-referencing the
persisted `RecurringItem` records against the user's real transaction
history -- never inventing a pattern that isn't backed by real data.

All recurrence-horizon math (30/60/90-day obligations) reuses
`app.recurring.project_occurrences`, the same helper Safe-to-Spend uses,
so a longer horizon is never a second recurrence formula, just more
occurrences of the same one.

Amount-change/new/missing/duplicate detection is intentionally
conservative: every signal requires a minimum amount of real history or
strong multi-factor evidence before it fires, per the product
requirement to avoid noise and false positives.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RecurringItem, Transaction
from app.recurring import _merchant, project_occurrences
from app.schemas import (
    DuplicateRecurringPairOut,
    MissingRecurringPaymentOut,
    NewRecurringPaymentOut,
    RecurringAmountChangeOut,
    RecurringBurdenOut,
    RecurringIntelligenceOut,
    RecurringUpcomingObligationOut,
)
from app.services.major_purchase_service import _average_monthly_income_cents

_TRAILING_MONTHS_FOR_SPENDING_AVERAGE = 3

# A recurring item needs at least 3 prior occurrences PLUS the current
# one before its latest amount is compared against a baseline -- fewer
# than that and it's still "newly established", not yet a reliable
# change signal. Mirrors detect_recurring's own minimum of 3 matching
# transactions to ever surface a pattern at all.
_MIN_OCCURRENCES_FOR_BASELINE = 4
_CHANGE_MIN_PERCENT = 10.0
_CHANGE_MIN_ABS_CENTS = 100

# Grace window before a not-yet-seen payment is surfaced as possibly
# missing -- wide enough to absorb a few days of normal posting-date
# jitter per cadence, narrow enough to still be a timely signal.
_GRACE_DAYS = {"Weekly": 4, "Biweekly": 6, "Monthly": 10}
_DEFAULT_GRACE_DAYS = 10

_DUPLICATE_AMOUNT_TOLERANCE_PERCENT = 0.15
_DUPLICATE_AMOUNT_TOLERANCE_MIN_CENTS = 100

# Mirrors detect_recurring's own amount_tolerance formula in
# app/recurring.py (20% of the expected amount, floored at $1) -- a
# same-merchant transaction only counts as "the expected payment" if
# it's within the same tolerance the app already uses to decide two
# charges belong to the same recurring pattern in the first place.
_PAYMENT_MATCH_AMOUNT_TOLERANCE_PERCENT = 0.20
_PAYMENT_MATCH_AMOUNT_TOLERANCE_MIN_CENTS = 100

_FREQUENCY_MONTHLY_MULTIPLIER = {
    "Weekly": 52 / 12,
    "Biweekly": 26 / 12,
    "Monthly": 1.0,
}

_HORIZONS = (30, 60, 90)


def evaluate_recurring_intelligence(
    db: Session,
    user_id: int,
    *,
    as_of: date | None = None,
) -> RecurringIntelligenceOut:
    calculation_date = as_of or date.today()

    active_items = _active_recurring_items(db, user_id)

    if not active_items:
        return RecurringIntelligenceOut(
            as_of=calculation_date,
            burden=_empty_burden(),
            upcoming=[],
            amount_changes=[],
            new_recurring=[],
            possibly_missing=[],
            possible_duplicates=[],
            data_quality_note="No active recurring items were found.",
        )

    merchant_groups = _user_transactions_by_merchant(db, user_id)

    amount_changes, new_recurring = _amount_changes_and_new(
        active_items, merchant_groups
    )

    return RecurringIntelligenceOut(
        as_of=calculation_date,
        burden=_burden(db, user_id, calculation_date, active_items),
        upcoming=_upcoming(active_items, calculation_date),
        amount_changes=amount_changes,
        new_recurring=new_recurring,
        possibly_missing=_possibly_missing(
            active_items, merchant_groups, calculation_date
        ),
        possible_duplicates=_possible_duplicates(active_items),
        data_quality_note=None,
    )


def _active_recurring_items(
    db: Session, user_id: int
) -> list[RecurringItem]:
    statement = (
        select(RecurringItem)
        .where(
            RecurringItem.user_id == user_id,
            RecurringItem.status == "active",
        )
        .order_by(RecurringItem.next_payment, RecurringItem.id)
    )

    return list(db.scalars(statement).all())


def _user_transactions_by_merchant(
    db: Session, user_id: int
) -> dict[str, list[Transaction]]:
    statement = select(Transaction).where(
        Transaction.user_id == user_id,
        Transaction.amount_cents < 0,
        Transaction.pending.is_(False),
    )

    groups: dict[str, list[Transaction]] = defaultdict(list)

    for transaction in db.scalars(statement).all():
        merchant = _merchant(transaction)
        if merchant:
            groups[merchant].append(transaction)

    for items in groups.values():
        items.sort(key=lambda transaction: transaction.posted_on)

    return groups


def _empty_burden() -> RecurringBurdenOut:
    return RecurringBurdenOut(
        monthly_recurring_cents=0,
        active_recurring_count=0,
        percent_of_income=None,
        percent_of_spending=None,
        next_30_days_cents=0,
        next_60_days_cents=0,
        next_90_days_cents=0,
    )


def _monthly_equivalent_cents(item: RecurringItem) -> int:
    multiplier = _FREQUENCY_MONTHLY_MULTIPLIER.get(item.frequency, 1.0)
    return round(item.amount_cents * multiplier)


def _average_monthly_spending_cents(
    db: Session, user_id: int, as_of: date
) -> int:
    transactions = list(
        db.scalars(
            select(Transaction).where(
                Transaction.user_id == user_id,
                Transaction.amount_cents < 0,
            )
        ).all()
    )

    current_month = f"{as_of.year:04d}-{as_of.month:02d}"
    totals: dict[str, int] = {}

    for transaction in transactions:
        month = (
            f"{transaction.posted_on.year:04d}"
            f"-{transaction.posted_on.month:02d}"
        )

        if month >= current_month:
            continue

        totals[month] = totals.get(month, 0) + abs(transaction.amount_cents)

    recent = sorted(totals)[-_TRAILING_MONTHS_FOR_SPENDING_AVERAGE:]

    if not recent:
        return 0

    return round(sum(totals[month] for month in recent) / len(recent))


def _burden(
    db: Session,
    user_id: int,
    as_of: date,
    active_items: list[RecurringItem],
) -> RecurringBurdenOut:
    monthly_cents = sum(
        _monthly_equivalent_cents(item) for item in active_items
    )

    income_cents = _average_monthly_income_cents(db, user_id, as_of)
    spending_cents = _average_monthly_spending_cents(db, user_id, as_of)

    percent_of_income = (
        round(monthly_cents / income_cents * 100, 1)
        if income_cents > 0
        else None
    )
    percent_of_spending = (
        round(monthly_cents / spending_cents * 100, 1)
        if spending_cents > 0
        else None
    )

    through_date = as_of + timedelta(days=max(_HORIZONS))
    horizon_totals = {horizon: 0 for horizon in _HORIZONS}

    for item in active_items:
        for occurrence in project_occurrences(
            item.next_payment,
            item.frequency,
            as_of=as_of,
            through_date=through_date,
        ):
            days_out = (occurrence - as_of).days
            for horizon in _HORIZONS:
                if days_out <= horizon:
                    horizon_totals[horizon] += item.amount_cents

    return RecurringBurdenOut(
        monthly_recurring_cents=monthly_cents,
        active_recurring_count=len(active_items),
        percent_of_income=percent_of_income,
        percent_of_spending=percent_of_spending,
        next_30_days_cents=horizon_totals[30],
        next_60_days_cents=horizon_totals[60],
        next_90_days_cents=horizon_totals[90],
    )


def _upcoming(
    active_items: list[RecurringItem], as_of: date
) -> list[RecurringUpcomingObligationOut]:
    obligations = [
        RecurringUpcomingObligationOut(
            recurring_item_id=item.id,
            merchant=item.merchant,
            category=item.category,
            amount_cents=item.amount_cents,
            frequency=item.frequency,
            next_payment=item.next_payment,
            days_until_due=(item.next_payment - as_of).days,
        )
        for item in active_items
    ]

    return sorted(obligations, key=lambda o: o.days_until_due)


def _amount_changes_and_new(
    active_items: list[RecurringItem],
    merchant_groups: dict[str, list[Transaction]],
) -> tuple[list[RecurringAmountChangeOut], list[NewRecurringPaymentOut]]:
    changes: list[RecurringAmountChangeOut] = []
    new_items: list[NewRecurringPaymentOut] = []

    for item in active_items:
        matches = merchant_groups.get(item.normalized_merchant, [])
        occurrences = len(matches)

        if occurrences == 0:
            # No matching transaction history at all (e.g. a manually
            # created recurring item) -- nothing deterministic to say
            # about "new" or "changed" without real data.
            continue

        if occurrences < _MIN_OCCURRENCES_FOR_BASELINE:
            new_items.append(
                NewRecurringPaymentOut(
                    recurring_item_id=item.id,
                    merchant=item.merchant,
                    category=item.category,
                    amount_cents=item.amount_cents,
                    frequency=item.frequency,
                    occurrences_seen=occurrences,
                    last_payment=matches[-1].posted_on,
                )
            )
            continue

        amounts = [abs(transaction.amount_cents) for transaction in matches]
        baseline = round(sum(amounts[:-1]) / len(amounts[:-1]))
        current = amounts[-1]

        if baseline <= 0:
            continue

        change_cents = current - baseline
        change_percent = round((change_cents / baseline) * 100, 1)

        if (
            abs(change_cents) >= _CHANGE_MIN_ABS_CENTS
            and abs(change_percent) >= _CHANGE_MIN_PERCENT
        ):
            changes.append(
                RecurringAmountChangeOut(
                    recurring_item_id=item.id,
                    merchant=item.merchant,
                    category=item.category,
                    status="increased" if change_cents > 0 else "decreased",
                    current_amount_cents=current,
                    baseline_amount_cents=baseline,
                    change_cents=change_cents,
                    change_percent=change_percent,
                    occurrences_considered=occurrences,
                    last_payment=matches[-1].posted_on,
                )
            )

    return changes, new_items


def _matches_expected_amount(
    transaction_amount_cents: int, expected_amount_cents: int
) -> bool:
    tolerance_cents = max(
        _PAYMENT_MATCH_AMOUNT_TOLERANCE_MIN_CENTS,
        round(
            expected_amount_cents
            * _PAYMENT_MATCH_AMOUNT_TOLERANCE_PERCENT
        ),
    )

    return (
        abs(transaction_amount_cents - expected_amount_cents)
        <= tolerance_cents
    )


def _possibly_missing(
    active_items: list[RecurringItem],
    merchant_groups: dict[str, list[Transaction]],
    as_of: date,
) -> list[MissingRecurringPaymentOut]:
    missing: list[MissingRecurringPaymentOut] = []

    for item in active_items:
        grace_days = _GRACE_DAYS.get(item.frequency, _DEFAULT_GRACE_DAYS)
        deadline = item.next_payment + timedelta(days=grace_days)

        if as_of <= deadline:
            continue

        matches = merchant_groups.get(item.normalized_merchant, [])
        # A transaction posted on/after the expected date, for
        # roughly the expected amount, means the payment DID happen
        # -- `next_payment` is just stale and needs a refresh, not a
        # genuinely missing payment. A same-merchant transaction for a
        # wildly different amount is NOT evidence this specific bill
        # was paid (e.g. a one-off purchase from the same merchant).
        already_paid = any(
            transaction.posted_on >= item.next_payment
            and _matches_expected_amount(
                abs(transaction.amount_cents), item.amount_cents
            )
            for transaction in matches
        )

        if already_paid:
            continue

        missing.append(
            MissingRecurringPaymentOut(
                recurring_item_id=item.id,
                merchant=item.merchant,
                category=item.category,
                amount_cents=item.amount_cents,
                frequency=item.frequency,
                expected_date=item.next_payment,
                days_overdue=(as_of - item.next_payment).days,
                message=(
                    f"FinSight has not seen the expected {item.merchant} "
                    f"payment yet -- it was due "
                    f"{item.next_payment.isoformat()}."
                ),
            )
        )

    return missing


def _tokens(normalized_merchant: str) -> set[str]:
    return set(normalized_merchant.split())


def _is_duplicate_pair(a: RecurringItem, b: RecurringItem) -> bool:
    if a.frequency != b.frequency:
        return False

    tokens_a, tokens_b = _tokens(a.normalized_merchant), _tokens(
        b.normalized_merchant
    )

    if not tokens_a or not tokens_b:
        return False

    shorter, longer = (
        (tokens_a, tokens_b)
        if len(tokens_a) <= len(tokens_b)
        else (tokens_b, tokens_a)
    )

    if not shorter.issubset(longer):
        return False

    tolerance_cents = max(
        _DUPLICATE_AMOUNT_TOLERANCE_MIN_CENTS,
        round(
            max(a.amount_cents, b.amount_cents)
            * _DUPLICATE_AMOUNT_TOLERANCE_PERCENT
        ),
    )

    return abs(a.amount_cents - b.amount_cents) <= tolerance_cents


def _possible_duplicates(
    active_items: list[RecurringItem],
) -> list[DuplicateRecurringPairOut]:
    pairs: list[DuplicateRecurringPairOut] = []

    for index, item_a in enumerate(active_items):
        for item_b in active_items[index + 1 :]:
            if item_a.normalized_merchant == item_b.normalized_merchant:
                # Impossible under the DB's unique (user, normalized
                # merchant) constraint, but guarded defensively.
                continue

            if not _is_duplicate_pair(item_a, item_b):
                continue

            pairs.append(
                DuplicateRecurringPairOut(
                    recurring_item_id_a=item_a.id,
                    recurring_item_id_b=item_b.id,
                    merchant_a=item_a.merchant,
                    merchant_b=item_b.merchant,
                    amount_a_cents=item_a.amount_cents,
                    amount_b_cents=item_b.amount_cents,
                    frequency=item_a.frequency,
                    reason=(
                        f"{item_a.merchant} and {item_b.merchant} have "
                        "very similar names, similar amounts, and the "
                        f"same {item_a.frequency.lower()} cadence -- "
                        "this may be the same subscription tracked "
                        "twice."
                    ),
                )
            )

    return pairs
