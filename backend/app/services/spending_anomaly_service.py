"""Deterministic spending-anomaly detection.

Every anomaly is a user-RELATIVE statistical comparison against the
user's own real transaction history -- never a fixed dollar rule, an ML
model, or a guess. Robust statistics (median / median-absolute-deviation,
a.k.a. MAD) are preferred over mean/stdev because a handful of large
transactions shouldn't distort the baseline used to judge whether
another transaction is unusual. Fixed-dollar amounts appear only as a
minimum-noise floor (e.g. "don't call a $3 deviation unusual even if
it's statistically large"), never as the primary rule.

Every signal requires a minimum sample size before it can fire, and
every threshold is a fixed, documented constant -- there is no learned
model and no hidden state, so the same transaction history always
produces the same anomalies.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Transaction
from app.recurring import _merchant
from app.schemas import SpendingAnomalyOut, SpendingAnomaliesOut
from app.services.goal_impact_service import _add_months

# Nothing runs until there's at least this much overall transaction
# history -- below this, any "anomaly" would just be noise.
_MIN_TOTAL_TRANSACTIONS = 10

# Anomaly candidates are restricted to recent activity so the same
# months-old outlier doesn't resurface forever.
_RECENT_WINDOW_DAYS = 30

# --- A. Merchant-level unusual spend ------------------------------------
_MERCHANT_MIN_HISTORY = 5
_MERCHANT_Z_WARNING = 3.5
_MERCHANT_Z_HIGH = 5.0
# Fallback for the (rare) case every prior charge was identical, so MAD
# is 0 and a z-score can't be computed.
_MERCHANT_FALLBACK_MIN_PERCENT = 50.0
_MERCHANT_FALLBACK_MIN_ABS_CENTS = 2000

# --- B. Category-level spike ---------------------------------------------
_CATEGORY_TRAILING_MONTHS = 3
_CATEGORY_MIN_COMPLETED_MONTHS = 2
_CATEGORY_SPIKE_MIN_PERCENT = 50.0
_CATEGORY_SPIKE_MIN_ABS_CENTS = 5000
# A pace-based projection from the first couple of days of a month, or
# from a single transaction, is too noisy to justify a warning/high
# signal -- one early large purchase can multiply into an enormous
# "projected" total. Both guards are deliberately small/deterministic.
_CATEGORY_MIN_ELAPSED_DAYS = 3
_CATEGORY_MIN_CURRENT_TRANSACTIONS = 2

# --- C. Large individual transaction --------------------------------------
_LARGE_TXN_MIN_SAMPLE = 10
_LARGE_TXN_Z_WARNING = 4.0
_LARGE_TXN_Z_HIGH = 6.0
# Minimum-noise floor only -- a transaction below this is never flagged
# as "large" no matter its z-score against a low-spending user.
_LARGE_TXN_MIN_FLOOR_CENTS = 5000

# --- D. Repeated-charge anomaly -------------------------------------------
# Deliberately tight (same day or the next calendar day only) -- a
# customer legitimately revisiting the same merchant every couple of
# days (e.g. groceries) is normal and must never be flagged. A window
# this narrow is what actually distinguishes a likely double-charge
# (POS glitch, duplicate submission) from routine repeat spending.
_REPEATED_CHARGE_WINDOW_DAYS = 1
_REPEATED_CHARGE_TOLERANCE_PERCENT = 0.05
_REPEATED_CHARGE_TOLERANCE_MIN_CENTS = 100

_SEVERITY_WEIGHT = {"high": 3, "warning": 2, "info": 1}


def detect_spending_anomalies(
    db: Session,
    user_id: int,
    *,
    as_of: date | None = None,
    lookback_months: int = 6,
    limit: int = 20,
) -> SpendingAnomaliesOut:
    calculation_date = as_of or date.today()
    cutoff = _add_months(calculation_date, -lookback_months)

    transactions = _user_debit_transactions(
        db, user_id, cutoff, calculation_date
    )

    if len(transactions) < _MIN_TOTAL_TRANSACTIONS:
        return SpendingAnomaliesOut(
            as_of=calculation_date,
            lookback_months=lookback_months,
            anomalies=[],
            data_quality_note=(
                "Not enough transaction history yet to reliably detect "
                "spending anomalies."
            ),
        )

    anomalies: list[SpendingAnomalyOut] = []
    anomalies.extend(
        _merchant_unusual_spend(transactions, calculation_date)
    )
    anomalies.extend(
        _category_spike(db, user_id, calculation_date, lookback_months)
    )
    anomalies.extend(_large_transactions(transactions, calculation_date))
    anomalies.extend(_repeated_charges(transactions))

    anomalies.sort(
        key=lambda a: (
            -_SEVERITY_WEIGHT[a.severity],
            -abs(a.difference_cents or 0),
        )
    )

    return SpendingAnomaliesOut(
        as_of=calculation_date,
        lookback_months=lookback_months,
        anomalies=anomalies[:limit],
        data_quality_note=None,
    )


def _user_debit_transactions(
    db: Session, user_id: int, start: date, end: date
) -> list[Transaction]:
    statement = (
        select(Transaction)
        .where(
            Transaction.user_id == user_id,
            Transaction.amount_cents < 0,
            Transaction.pending.is_(False),
            Transaction.posted_on >= start,
            Transaction.posted_on <= end,
        )
        .order_by(Transaction.posted_on)
    )

    return list(db.scalars(statement).all())


def _mad(values: list[int], center: float) -> float:
    return median(abs(value - center) for value in values)


def _modified_z_score(value: int, baseline: list[int]) -> float | None:
    """0.6745 * (x - median) / MAD -- None if MAD is 0 (no spread)."""
    center = median(baseline)
    spread = _mad(baseline, center)

    if spread == 0:
        return None

    return 0.6745 * (value - center) / spread


def _confidence_for_sample(count: int) -> str:
    if count >= 10:
        return "high"
    if count >= 5:
        return "medium"
    return "low"


def _currency(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    return f"{sign}${abs(cents) / 100:,.2f}"


# --- A. Merchant-level unusual spend --------------------------------------


def _merchant_unusual_spend(
    transactions: list[Transaction], as_of: date
) -> list[SpendingAnomalyOut]:
    groups: dict[str, list[Transaction]] = defaultdict(list)

    for transaction in transactions:
        merchant = _merchant(transaction)
        if merchant:
            groups[merchant].append(transaction)

    recent_cutoff = as_of - timedelta(days=_RECENT_WINDOW_DAYS)
    anomalies: list[SpendingAnomalyOut] = []

    for merchant, items in groups.items():
        items.sort(key=lambda t: t.posted_on)

        for index, candidate in enumerate(items):
            if candidate.posted_on < recent_cutoff:
                continue

            baseline_transactions = items[:index]
            if len(baseline_transactions) < _MERCHANT_MIN_HISTORY:
                continue

            baseline_amounts = [
                abs(t.amount_cents) for t in baseline_transactions
            ]
            current_amount = abs(candidate.amount_cents)
            baseline_center = round(median(baseline_amounts))

            z_score = _modified_z_score(current_amount, baseline_amounts)

            flagged = False
            severity = "warning"

            if z_score is not None:
                if current_amount > baseline_center and z_score >= (
                    _MERCHANT_Z_HIGH
                ):
                    flagged, severity = True, "high"
                elif current_amount > baseline_center and z_score >= (
                    _MERCHANT_Z_WARNING
                ):
                    flagged, severity = True, "warning"
            elif baseline_center > 0:
                diff = current_amount - baseline_center
                percent = abs(diff) / baseline_center * 100
                if (
                    diff > 0
                    and percent >= _MERCHANT_FALLBACK_MIN_PERCENT
                    and diff >= _MERCHANT_FALLBACK_MIN_ABS_CENTS
                ):
                    flagged = True
                    severity = (
                        "high" if percent >= 100 else "warning"
                    )

            if not flagged:
                continue

            difference_cents = current_amount - baseline_center
            percent_difference = (
                round(difference_cents / baseline_center * 100, 1)
                if baseline_center > 0
                else None
            )

            anomalies.append(
                SpendingAnomalyOut(
                    id=(
                        f"merchant_unusual_spend:{candidate.id}"
                    ),
                    type="merchant_unusual_spend",
                    severity=severity,
                    title=(
                        f"Unusual charge at {candidate.merchant_name or merchant.title()}"
                    ),
                    merchant=merchant.title(),
                    category=candidate.category,
                    transaction_id=candidate.id,
                    date=candidate.posted_on,
                    current_amount_cents=current_amount,
                    baseline_amount_cents=baseline_center,
                    difference_cents=difference_cents,
                    percent_difference=percent_difference,
                    reason=(
                        f"{_currency(current_amount)} is well above the "
                        f"typical {_currency(baseline_center)} charge from "
                        f"this merchant, based on "
                        f"{len(baseline_transactions)} prior charges."
                    ),
                    confidence=_confidence_for_sample(
                        len(baseline_transactions)
                    ),
                )
            )

    return anomalies


# --- B. Category-level spike -----------------------------------------------


def _category_spike(
    db: Session,
    user_id: int,
    as_of: date,
    lookback_months: int,
) -> list[SpendingAnomalyOut]:
    from calendar import monthrange

    history_start = _add_months(
        as_of, -max(lookback_months, _CATEGORY_TRAILING_MONTHS)
    )

    transactions = list(
        db.scalars(
            select(Transaction).where(
                Transaction.user_id == user_id,
                Transaction.amount_cents < 0,
                Transaction.pending.is_(False),
                Transaction.posted_on >= history_start,
                Transaction.posted_on <= as_of,
            )
        ).all()
    )

    current_month = f"{as_of.year:04d}-{as_of.month:02d}"
    by_month_category: dict[tuple[str, str], int] = defaultdict(int)
    count_by_month_category: dict[tuple[str, str], int] = defaultdict(int)

    for transaction in transactions:
        month = (
            f"{transaction.posted_on.year:04d}"
            f"-{transaction.posted_on.month:02d}"
        )
        key = (month, transaction.category)
        by_month_category[key] += abs(transaction.amount_cents)
        count_by_month_category[key] += 1

    categories = {category for _, category in by_month_category}
    days_elapsed = as_of.day
    days_in_month = monthrange(as_of.year, as_of.month)[1]

    # Too early in the month for a pace-based projection to mean
    # anything -- a day or two of data can multiply into a wildly
    # overstated "projected" total.
    if days_elapsed < _CATEGORY_MIN_ELAPSED_DAYS:
        return []

    anomalies: list[SpendingAnomalyOut] = []

    for category in categories:
        current_total = by_month_category.get(
            (current_month, category), 0
        )
        current_count = count_by_month_category.get(
            (current_month, category), 0
        )

        if current_total <= 0:
            continue

        # A single early transaction shouldn't be prorated into a
        # month-end projection on its own -- wait for at least a
        # second data point in the category this month.
        if current_count < _CATEGORY_MIN_CURRENT_TRANSACTIONS:
            continue

        projected_total = round(
            current_total / days_elapsed * days_in_month
        )

        prior_months = sorted(
            month
            for (month, cat) in by_month_category
            if cat == category and month < current_month
        )[-_CATEGORY_TRAILING_MONTHS:]

        if len(prior_months) < _CATEGORY_MIN_COMPLETED_MONTHS:
            continue

        prior_totals = [
            by_month_category[(month, category)] for month in prior_months
        ]
        baseline_avg = round(sum(prior_totals) / len(prior_totals))

        if baseline_avg <= 0:
            continue

        difference_cents = projected_total - baseline_avg
        percent_difference = round(
            difference_cents / baseline_avg * 100, 1
        )

        if (
            difference_cents < _CATEGORY_SPIKE_MIN_ABS_CENTS
            or percent_difference < _CATEGORY_SPIKE_MIN_PERCENT
        ):
            continue

        severity = "high" if percent_difference >= 100 else "warning"

        anomalies.append(
            SpendingAnomalyOut(
                id=f"category_spike:{category}:{current_month}",
                type="category_spike",
                severity=severity,
                title=(
                    f"At your current pace, {category} is tracking "
                    "above your recent monthly baseline"
                ),
                merchant=None,
                category=category,
                transaction_id=None,
                date=as_of,
                # A pace-based PROJECTION, not the actual amount spent
                # so far -- kept distinct from `current_total` (real,
                # actual spend-to-date) below, which only appears in
                # the reason text and is never claimed as "spent".
                current_amount_cents=projected_total,
                baseline_amount_cents=baseline_avg,
                difference_cents=difference_cents,
                percent_difference=percent_difference,
                reason=(
                    f"At your current pace, {category} is tracking "
                    "above your recent monthly baseline. You've spent "
                    f"{_currency(current_total)} so far this month "
                    f"({current_count} transactions over {days_elapsed} "
                    "day(s)), which projects to about "
                    f"{_currency(projected_total)} by month-end -- "
                    f"roughly {percent_difference:.0f}% above your "
                    f"{_currency(baseline_avg)}/month average over the "
                    f"last {len(prior_months)} completed month(s). This "
                    "is a projection, not a final total."
                ),
                confidence=_confidence_for_sample(len(prior_months) * 4),
            )
        )

    return anomalies


# --- C. Large individual transaction ---------------------------------------


def _large_transactions(
    transactions: list[Transaction], as_of: date
) -> list[SpendingAnomalyOut]:
    ordered = sorted(transactions, key=lambda t: t.posted_on)
    recent_cutoff = as_of - timedelta(days=_RECENT_WINDOW_DAYS)
    anomalies: list[SpendingAnomalyOut] = []

    for index, candidate in enumerate(ordered):
        if candidate.posted_on < recent_cutoff:
            continue

        current_amount = abs(candidate.amount_cents)
        if current_amount < _LARGE_TXN_MIN_FLOOR_CENTS:
            continue

        baseline_transactions = ordered[:index]
        if len(baseline_transactions) < _LARGE_TXN_MIN_SAMPLE:
            continue

        baseline_amounts = [
            abs(t.amount_cents) for t in baseline_transactions
        ]
        baseline_center = round(median(baseline_amounts))
        z_score = _modified_z_score(current_amount, baseline_amounts)

        if z_score is None or current_amount <= baseline_center:
            continue

        if z_score >= _LARGE_TXN_Z_HIGH:
            severity = "high"
        elif z_score >= _LARGE_TXN_Z_WARNING:
            severity = "warning"
        else:
            continue

        difference_cents = current_amount - baseline_center
        percent_difference = (
            round(difference_cents / baseline_center * 100, 1)
            if baseline_center > 0
            else None
        )

        anomalies.append(
            SpendingAnomalyOut(
                id=f"large_transaction:{candidate.id}",
                type="large_transaction",
                severity=severity,
                title="Unusually large transaction",
                merchant=candidate.merchant_name,
                category=candidate.category,
                transaction_id=candidate.id,
                date=candidate.posted_on,
                current_amount_cents=current_amount,
                baseline_amount_cents=baseline_center,
                difference_cents=difference_cents,
                percent_difference=percent_difference,
                reason=(
                    f"{_currency(current_amount)} is much larger than "
                    f"your typical recent transaction of around "
                    f"{_currency(baseline_center)}."
                ),
                confidence=_confidence_for_sample(
                    len(baseline_transactions)
                ),
            )
        )

    return anomalies


# --- D. Repeated-charge anomaly ---------------------------------------------


def _repeated_charges(
    transactions: list[Transaction],
) -> list[SpendingAnomalyOut]:
    groups: dict[str, list[Transaction]] = defaultdict(list)

    for transaction in transactions:
        merchant = _merchant(transaction)
        if merchant:
            groups[merchant].append(transaction)

    anomalies: list[SpendingAnomalyOut] = []

    for merchant, items in groups.items():
        items.sort(key=lambda t: t.posted_on)

        for previous, current in zip(items, items[1:]):
            gap_days = (current.posted_on - previous.posted_on).days

            if gap_days > _REPEATED_CHARGE_WINDOW_DAYS:
                continue

            amount_a = abs(previous.amount_cents)
            amount_b = abs(current.amount_cents)
            tolerance_cents = max(
                _REPEATED_CHARGE_TOLERANCE_MIN_CENTS,
                round(
                    max(amount_a, amount_b)
                    * _REPEATED_CHARGE_TOLERANCE_PERCENT
                ),
            )

            if abs(amount_a - amount_b) > tolerance_cents:
                continue

            severity = "high" if amount_a == amount_b else "warning"
            difference_cents = amount_b - amount_a
            percent_difference = (
                round(difference_cents / amount_a * 100, 1)
                if amount_a > 0
                else None
            )
            day_word = "day" if gap_days in (0, 1) else "days"

            anomalies.append(
                SpendingAnomalyOut(
                    id=f"repeated_charge:{previous.id}:{current.id}",
                    type="repeated_charge",
                    severity=severity,
                    title=f"Possible duplicate charge at {merchant.title()}",
                    merchant=merchant.title(),
                    category=current.category,
                    transaction_id=current.id,
                    date=current.posted_on,
                    current_amount_cents=amount_b,
                    baseline_amount_cents=amount_a,
                    difference_cents=difference_cents,
                    percent_difference=percent_difference,
                    reason=(
                        f"Two charges of {_currency(amount_a)} and "
                        f"{_currency(amount_b)} from {merchant.title()} "
                        f"posted {gap_days} {day_word} apart "
                        f"({previous.posted_on.isoformat()} and "
                        f"{current.posted_on.isoformat()})."
                    ),
                    confidence="high",
                )
            )

    return anomalies
