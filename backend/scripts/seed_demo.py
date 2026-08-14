"""Deterministic, idempotent portfolio-demo data seed.

Writes ONLY to a single fixed demo user (DEMO_EMAIL below). Never looks
up "the first user" or any other arbitrary user -- every delete and
every insert is scoped to a user row found by an exact email match, so
it is impossible for this script to touch real user data by accident.

This script is never imported or invoked by the application, alembic,
or the test suite automatically -- it only runs when a human explicitly
executes it from the command line, from the `backend/` directory:

    python -m scripts.seed_demo --confirm-demo

Without --confirm-demo it only prints what it *would* do (including the
sanitized DATABASE_URL it would target) and writes nothing.

Re-running is safe: existing demo-user data is fully replaced with the
same deterministic dataset, scoped strictly to that one user_id. If a
demo user still exists under the retired portfolio-demo@local.test
email (from before the email was changed), that exact user is removed
first -- never any other user.
"""

from __future__ import annotations

import argparse
import calendar
import re
import sys
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import (
    Budget,
    FinancialAccount,
    GoalContribution,
    PlaidItem,
    RecurringItem,
    SavedDecision,
    SavingsGoal,
    Transaction,
    User,
)
from app.security import hash_password
from app.services.buy_now_vs_wait_service import (
    _BASE_ASSUMPTION,
    _LONG_HORIZON_ASSUMPTION_SUFFIX,
    _currency as _bnw_currency,
)

DEMO_EMAIL = "portfolio-demo@discero-app.vercel.app"
# Prior fixed demo email, retired because "local.test" doesn't pass the
# app's real EmailStr validation (used by both registration and
# login). Kept only so seeding can find and remove that exact old user
# -- never any other user -- on machines/environments where it was
# already seeded before this change.
_LEGACY_DEMO_EMAIL = "portfolio-demo@finsigh.vercel.app"
# Local/manual portfolio-demo login only -- never treated as a real
# secret, and only ever printed once, explicitly, at the very end of a
# --confirm-demo run.
DEMO_PASSWORD = "PortfolioDemo!2026"

# PlaidItem.access_token_ciphertext is a non-nullable column, so this
# can't be None without a schema change -- instead it's a plain string
# that is NOT valid Fernet ciphertext. app.token_encryption.decrypt_token
# (the only code path that ever reads this column) always raises
# TokenEncryptionError on it, so a sync attempt fails at the decryption
# step itself, before any network call to Plaid could happen. This is
# deliberately NOT run through encrypt_token() -- encrypting a fake
# payload would still "pretend" to be a valid stored token; failing to
# decrypt at all is the stronger guarantee. See
# test_demo_plaid_token_is_not_decryptable for proof.
DEMO_PLAID_TOKEN_PLACEHOLDER = "not-a-plaid-token::demo-user-has-no-real-connection"

_UNCATEGORIZED_TARGET_RATIO = 0.07  # -> ~6.5% of total spend


def _add_months(start: date, offset: int) -> date:
    month_index = start.month - 1 + offset
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def _day(year: int, month: int, day: int) -> date:
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last_day))


def _normalize_merchant(name: str) -> str:
    # Mirrors app.recurring._merchant's normalization exactly, so
    # seeded RecurringItem.normalized_merchant values line up with
    # what the live recurring-detection cross-reference computes.
    normalized = re.sub(r"\d+", "", name.upper())
    normalized = re.sub(r"[^A-Z ]", " ", normalized)
    return " ".join(normalized.split())


def _sanitized_database_url(url: str) -> str:
    # Only rewrite the string when there's actually a password to mask
    # -- round-tripping a credential-less URL (e.g. local sqlite)
    # through urlsplit/urlunsplit can mangle its exact form, and the
    # whole point of printing this is to show the real target.
    parts = urlsplit(url)
    if not parts.password:
        return url
    netloc = parts.netloc.replace(f":{parts.password}", ":***")
    return urlunsplit(parts._replace(netloc=netloc))


def _find_demo_user(db: Session) -> User | None:
    return db.scalar(select(User).where(User.email == DEMO_EMAIL))


def _wipe_demo_user_data(db: Session, user: User) -> None:
    """Delete every row owned by `user`, and only `user`."""
    uid = user.id

    goal_ids = [
        g.id
        for g in db.scalars(
            select(SavingsGoal).where(SavingsGoal.user_id == uid)
        )
    ]
    if goal_ids:
        db.query(GoalContribution).filter(
            GoalContribution.goal_id.in_(goal_ids)
        ).delete(synchronize_session=False)

    plaid_item_ids = [
        p.id
        for p in db.scalars(select(PlaidItem).where(PlaidItem.user_id == uid))
    ]
    if plaid_item_ids:
        db.query(FinancialAccount).filter(
            FinancialAccount.plaid_item_id.in_(plaid_item_ids)
        ).delete(synchronize_session=False)

    db.query(Transaction).filter(Transaction.user_id == uid).delete(
        synchronize_session=False
    )
    db.query(SavingsGoal).filter(SavingsGoal.user_id == uid).delete(
        synchronize_session=False
    )
    db.query(Budget).filter(Budget.user_id == uid).delete(
        synchronize_session=False
    )
    db.query(RecurringItem).filter(RecurringItem.user_id == uid).delete(
        synchronize_session=False
    )
    db.query(SavedDecision).filter(SavedDecision.user_id == uid).delete(
        synchronize_session=False
    )
    db.query(PlaidItem).filter(PlaidItem.user_id == uid).delete(
        synchronize_session=False
    )
    db.flush()


def _purge_legacy_demo_user(db: Session) -> None:
    """Remove the retired portfolio-demo@local.test user, if present.

    Scoped to that exact email only, same as every other operation in
    this script -- this can never touch a different user.
    """
    legacy_user = db.scalar(
        select(User).where(User.email == _LEGACY_DEMO_EMAIL)
    )
    if legacy_user is None:
        return

    _wipe_demo_user_data(db, legacy_user)
    db.query(User).filter(User.id == legacy_user.id).delete(
        synchronize_session=False
    )
    db.flush()


def seed_demo_user(db: Session, as_of: date | None = None) -> dict:
    """Create/replace the demo user's data. Returns a summary dict."""
    as_of = as_of or date.today()

    _purge_legacy_demo_user(db)

    user = _find_demo_user(db)
    if user is not None:
        _wipe_demo_user_data(db, user)
        user.password_hash = hash_password(DEMO_PASSWORD)
        user.email_verified = True
    else:
        user = User(
            email=DEMO_EMAIL,
            password_hash=hash_password(DEMO_PASSWORD),
            email_verified=True,
        )
        db.add(user)
        db.flush()

    plaid_item = PlaidItem(
        user_id=user.id,
        provider_item_id="demo-portfolio-plaid-item",
        institution_id="demo_portfolio_bank",
        institution_name="Portfolio Demo Bank",
        access_token_ciphertext=DEMO_PLAID_TOKEN_PLACEHOLDER,
        status="active",
        sync_status="succeeded",
        last_synced_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    db.add(plaid_item)
    db.flush()

    checking = FinancialAccount(
        plaid_item_id=plaid_item.id,
        provider_account_id="demo-checking-001",
        name="Demo Checking",
        official_name="Demo Bank Total Checking",
        account_type="depository",
        account_subtype="checking",
        mask="0001",
        current_balance_cents=850_000,
        available_balance_cents=850_000,
    )
    savings = FinancialAccount(
        plaid_item_id=plaid_item.id,
        provider_account_id="demo-savings-001",
        name="Demo Savings",
        official_name="Demo Bank Online Savings",
        account_type="depository",
        account_subtype="savings",
        mask="0002",
        current_balance_cents=2_200_000,
        available_balance_cents=2_200_000,
    )
    credit_card = FinancialAccount(
        plaid_item_id=plaid_item.id,
        provider_account_id="demo-credit-001",
        name="Demo Rewards Card",
        official_name="Demo Bank Rewards Visa",
        account_type="credit",
        account_subtype="credit card",
        mask="4242",
        current_balance_cents=42_000,
        available_balance_cents=458_000,
    )
    db.add_all([checking, savings, credit_card])
    db.flush()

    transactions: list[Transaction] = []

    def txn(d: date, amount_cents: int, description: str, merchant: str, category: str) -> None:
        if d > as_of:
            return
        transactions.append(
            Transaction(
                user_id=user.id,
                financial_account_id=checking.id,
                posted_on=d,
                description=description,
                merchant_name=merchant,
                amount_cents=amount_cents,
                category=category,
                source="csv",
            )
        )

    month_starts = [_add_months(date(as_of.year, as_of.month, 1), -i) for i in range(5, -1, -1)]

    electric_cents = [8420, 8710, 9150, 8890, 8330, 8975]
    grocery_base = [6200, 7800, 5400, 6900, 8100, 5000, 7200, 6600]
    grocery_days = [2, 6, 9, 13, 17, 21, 24, 28]
    grocery_merchants = [
        "Trader Joe's", "Whole Foods Market", "Safeway", "Trader Joe's",
        "Whole Foods Market", "Safeway", "Trader Joe's", "Whole Foods Market",
    ]
    dining_items = [
        (4, 1450, "Chipotle"), (8, 1320, "Sweetgreen"), (11, 650, "Blue Bottle Coffee"),
        (13, 675, "Starbucks"), (15, 1520, "Chipotle"), (17, 590, "Starbucks"),
        (18, 6200, "Local Bistro"), (21, 3450, "Thai Kitchen"), (22, 720, "Blue Bottle Coffee"),
        (24, 2840, "Pizzeria Napoli"), (27, 2460, "Sunday Brunch Cafe"),
    ]
    transport_items = [
        (3, 1240, "Uber"), (9, 1580, "Uber"), (16, 960, "Uber"), (23, 1820, "Uber"),
        (6, 4850, "Shell Gas Station"), (20, 5230, "Shell Gas Station"),
        (1, 10000, "Metro Transit Pass"),
    ]

    for i, month_start in enumerate(month_starts):
        y, m = month_start.year, month_start.month

        txn(_day(y, m, 1), 310_000, "ACME Software Inc Payroll", "ACME Software Inc", "Income")
        txn(_day(y, m, 16), 310_000, "ACME Software Inc Payroll", "ACME Software Inc", "Income")

        txn(_day(y, m, 1), -185_000, "Skyline Ridge Apartments Rent", "Skyline Ridge Apartments", "Housing")

        txn(_day(y, m, 5), -electric_cents[i], "Metro Electric Co", "Metro Electric Co", "Utilities")
        txn(_day(y, m, 6), -7_000, "Xfinity Internet", "Xfinity", "Utilities")
        txn(_day(y, m, 7), -6_500, "Verizon Wireless", "Verizon Wireless", "Utilities")
        # No "Insurance" category exists anywhere in this app's
        # supported vocabulary (frontend filter list or backend
        # mapping) -- adding one is a product-wide change out of scope
        # here, so Geico is filed under Utilities like the other fixed
        # monthly bills, and the Utilities budget below is sized to
        # account for it.
        txn(_day(y, m, 8), -14_200, "Geico Insurance Premium", "Geico", "Utilities")

        txn(_day(y, m, 3), -4_500, "Equinox Fitness Membership", "Equinox", "Subscriptions")
        netflix_cents = 1549 if i < 4 else 1799
        txn(_day(y, m, 10), -netflix_cents, "Netflix Subscription", "Netflix", "Subscriptions")
        txn(_day(y, m, 12), -1_199, "Spotify Premium", "Spotify", "Subscriptions")
        txn(_day(y, m, 20), -1_499, "Amazon Prime Membership", "Amazon Prime", "Subscriptions")

        for day, base_cents, merchant in zip(grocery_days, grocery_base, grocery_merchants):
            cents = base_cents + (45 if day == grocery_days[0] else 0) * i
            txn(_day(y, m, day), -cents, merchant, merchant, "Groceries")

        for day, cents, merchant in dining_items:
            txn(_day(y, m, day), -cents, merchant, merchant, "Dining")

        for day, cents, merchant in transport_items:
            txn(_day(y, m, day), -cents, merchant, merchant, "Transport")

        txn(_day(y, m, 25), -4_230, "Target", "Target", "Shopping")
        txn(_day(y, m, 26), -5_890, "Amazon.com", "Amazon", "Shopping")

        if i == 3:
            # Believable duplicate-charge anomaly: same merchant, same
            # amount, one day apart -- the pattern
            # spending_anomaly_service looks for.
            txn(_day(y, m, 14), -6_430, "REI Co-op", "REI", "Shopping")
            txn(_day(y, m, 15), -6_430, "REI Co-op", "REI", "Shopping")

    categorized_spend = sum(-t.amount_cents for t in transactions if t.amount_cents < 0)
    uncategorized_total = round(categorized_spend * _UNCATEGORIZED_TARGET_RATIO)
    per_month = uncategorized_total // 6
    for i, month_start in enumerate(month_starts):
        amount = per_month + (uncategorized_total - per_month * 6 if i == 5 else 0)
        if amount <= 0:
            continue
        txn(
            _day(month_start.year, month_start.month, 19),
            -amount,
            "POS DEBIT UNKNOWN MERCHANT",
            None,
            "Uncategorized",
        )

    db.add_all(transactions)
    db.flush()

    recurring_items = [
        RecurringItem(
            user_id=user.id,
            merchant="Skyline Ridge Apartments",
            normalized_merchant=_normalize_merchant("Skyline Ridge Apartments"),
            category="Housing",
            amount_cents=185_000,
            frequency="Monthly",
            last_payment=_day(month_starts[-1].year, month_starts[-1].month, 1),
            next_payment=_add_months(month_starts[-1], 1),
            status="active",
            confidence_score=97.0,
        ),
        RecurringItem(
            user_id=user.id,
            merchant="Netflix",
            normalized_merchant=_normalize_merchant("Netflix"),
            category="Subscriptions",
            amount_cents=1799,
            frequency="Monthly",
            last_payment=_day(month_starts[-1].year, month_starts[-1].month, 10),
            next_payment=_add_months(month_starts[-1], 1),
            status="active",
            confidence_score=93.0,
            price_change_percent=round((1799 - 1549) / 1549 * 100, 1),
            price_change_warning=True,
        ),
        RecurringItem(
            user_id=user.id,
            merchant="Spotify",
            normalized_merchant=_normalize_merchant("Spotify"),
            category="Subscriptions",
            amount_cents=1199,
            frequency="Monthly",
            last_payment=_day(month_starts[-1].year, month_starts[-1].month, 12),
            next_payment=_add_months(month_starts[-1], 1),
            status="active",
            confidence_score=95.0,
        ),
        RecurringItem(
            user_id=user.id,
            merchant="Equinox",
            normalized_merchant=_normalize_merchant("Equinox"),
            category="Subscriptions",
            amount_cents=4500,
            frequency="Monthly",
            last_payment=_day(month_starts[-1].year, month_starts[-1].month, 3),
            next_payment=_add_months(month_starts[-1], 1),
            status="active",
            confidence_score=90.0,
        ),
        RecurringItem(
            user_id=user.id,
            merchant="Geico",
            normalized_merchant=_normalize_merchant("Geico"),
            category="Utilities",
            amount_cents=14200,
            frequency="Monthly",
            last_payment=_day(month_starts[-1].year, month_starts[-1].month, 8),
            next_payment=_add_months(month_starts[-1], 1),
            status="active",
            confidence_score=91.0,
        ),
    ]
    db.add_all(recurring_items)

    current_month = f"{as_of.year:04d}-{as_of.month:02d}"
    budgets = [
        Budget(user_id=user.id, category="Groceries", month=current_month, limit_cents=60_000),
        Budget(user_id=user.id, category="Dining", month=current_month, limit_cents=30_000),
        Budget(user_id=user.id, category="Transport", month=current_month, limit_cents=30_000),
        # There's no supported "Insurance" category in this app (see
        # Geico's category below), so its ~$142/mo premium is folded
        # into Utilities like the other fixed bills. $300 undersized
        # that bucket against its real ~$361-369/mo total and produced
        # an artificial ~122% overage; $340 keeps a mild, realistic
        # overage (warning-tier, not critical) instead of one created
        # by an undersized budget.
        Budget(user_id=user.id, category="Utilities", month=current_month, limit_cents=34_000),
        Budget(user_id=user.id, category="Subscriptions", month=current_month, limit_cents=9_000),
        Budget(user_id=user.id, category="Shopping", month=current_month, limit_cents=20_000),
    ]
    db.add_all(budgets)

    emergency_fund = SavingsGoal(
        user_id=user.id,
        name="Emergency Fund",
        target_cents=1_200_000,
        saved_cents=0,
        target_date=_add_months(month_starts[-1], 10),
    )
    laptop_fund = SavingsGoal(
        user_id=user.id,
        name="New Laptop",
        target_cents=220_000,
        saved_cents=0,
        target_date=_add_months(month_starts[-1], 4),
    )
    db.add_all([emergency_fund, laptop_fund])
    db.flush()

    goal_contributions: list[GoalContribution] = []
    ef_total = 0
    lf_total = 0
    for i, month_start in enumerate(month_starts):
        y, m = month_start.year, month_start.month
        ef_day = _day(y, m, 3)
        if ef_day <= as_of:
            goal_contributions.append(
                GoalContribution(
                    goal_id=emergency_fund.id,
                    amount_cents=50_000,
                    contribution_type="deposit",
                    contributed_on=ef_day,
                    note="Monthly emergency fund transfer",
                )
            )
            ef_total += 50_000
        lf_day = _day(y, m, 5)
        if lf_day <= as_of:
            goal_contributions.append(
                GoalContribution(
                    goal_id=laptop_fund.id,
                    amount_cents=15_000,
                    contribution_type="deposit",
                    contributed_on=lf_day,
                    note="Laptop savings transfer",
                )
            )
            lf_total += 15_000
    db.add_all(goal_contributions)
    emergency_fund.saved_cents = ef_total
    laptop_fund.saved_cents = lf_total

    decision_created_at = datetime(
        as_of.year, as_of.month, max(as_of.day - 10, 1), 14, 30, tzinfo=timezone.utc
    )
    bnw_wait_until_date = as_of + timedelta(days=75)
    # Waiting preserves more safe-to-spend buffer than buying now (the
    # Major Purchase decision above already shows the "buy now" side:
    # safe_to_spend_after_purchase_cents=190_000) -- roughly 2 more
    # months of the demo's own laptop-fund contribution pace ($150/mo)
    # plus continued safe-to-spend headroom. Above the service's own
    # $5,000 materiality floor but not an implausible swing for a
    # 61-day gap.
    bnw_buffer_difference_cents = 45_000
    bnw_confidence_difference = 6.0
    # recommended_timing="wait" / key_driver="buffer" matches
    # evaluate_buy_now_vs_wait's own decision rule: both scenarios
    # affordable, and a materially positive buffer_difference_cents
    # (waiting preserves more of it) selects "wait".
    bnw_reason = (
        f"Waiting until {bnw_wait_until_date.isoformat()} gives you "
        f"{_bnw_currency(bnw_buffer_difference_cents)} more room"
    )
    bnw_assumption = _BASE_ASSUMPTION + _LONG_HORIZON_ASSUMPTION_SUFFIX

    saved_decisions = [
        SavedDecision(
            user_id=user.id,
            decision_type="major_purchase",
            title="New Laptop Purchase",
            input_snapshot={
                "purchase_name": "New Laptop",
                "purchase_amount_cents": 220_000,
                "purchase_date": (as_of + timedelta(days=14)).isoformat(),
                "safety_reserve_cents": 200_000,
                "essential_spending_cents": 300_000,
                "horizon_days": 30,
            },
            result_snapshot={
                "purchase_name": "New Laptop",
                "purchase_amount_cents": 220_000,
                "affordability_status": "affordable",
                "safe_to_spend_before_purchase_cents": 410_000,
                "safe_to_spend_after_purchase_cents": 190_000,
                "shortfall_after_purchase_cents": 0,
                "confidence_score": 82.0,
                "explanation": (
                    "This purchase fits within your safe-to-spend balance "
                    "after accounting for upcoming obligations and your "
                    "safety reserve."
                ),
            },
            created_at=decision_created_at,
        ),
        SavedDecision(
            user_id=user.id,
            decision_type="buy_now_vs_wait",
            title="Buy Now vs Wait: New Laptop",
            input_snapshot={
                "purchase_name": "New Laptop",
                "purchase_amount_cents": 220_000,
                "buy_now_date": (as_of + timedelta(days=14)).isoformat(),
                "wait_until_date": bnw_wait_until_date.isoformat(),
                "safety_reserve_cents": 200_000,
                "essential_spending_cents": 300_000,
                "horizon_days": 30,
            },
            # Top-level BuyNowVsWaitOut fields only (see
            # BuyNowVsWaitOut in app/schemas.py) -- the nested
            # now/wait MajorPurchaseSimulationOut objects aren't
            # populated since nothing reads them today and fabricating
            # their many sub-fields (breakdown, alternatives, etc.)
            # would risk inventing numbers with no real basis.
            result_snapshot={
                "purchase_name": "New Laptop",
                "purchase_amount_cents": 220_000,
                "buy_now_date": (as_of + timedelta(days=14)).isoformat(),
                "wait_until_date": bnw_wait_until_date.isoformat(),
                "recommended_timing": "wait",
                "reason": bnw_reason,
                "key_driver": "buffer",
                "buffer_difference_cents": bnw_buffer_difference_cents,
                "goal_impact_note": None,
                "confidence_difference": bnw_confidence_difference,
                "assumption": bnw_assumption,
                "caveat": None,
            },
            created_at=decision_created_at + timedelta(minutes=6),
        ),
    ]
    db.add_all(saved_decisions)
    db.flush()

    return {
        "user_id": user.id,
        "transactions": len(transactions),
        "recurring_items": len(recurring_items),
        "budgets": len(budgets),
        "goals": 2,
        "goal_contributions": len(goal_contributions),
        "saved_decisions": len(saved_decisions),
        "financial_accounts": 3,
        "categorized_spend_cents": categorized_spend,
        "uncategorized_spend_cents": uncategorized_total,
        "uncategorized_share": (
            uncategorized_total / (categorized_spend + uncategorized_total)
            if (categorized_spend + uncategorized_total) > 0
            else 0.0
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm-demo",
        action="store_true",
        help="Required to actually write. Without it, this is a dry run.",
    )
    args = parser.parse_args()

    sanitized = _sanitized_database_url(settings.database_url)
    print(f"Target DATABASE_URL: {sanitized}")
    print(f"Target demo user:    {DEMO_EMAIL}")

    if not args.confirm_demo:
        print(
            "Dry run only -- no data written. Re-run with --confirm-demo "
            "to seed/replace this user's demo data."
        )
        return 0

    db = SessionLocal()
    try:
        summary = seed_demo_user(db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    print("Seed complete:")
    for key, value in summary.items():
        print(f"  {key}: {value}")
    print()
    print(f"Demo login -> email: {DEMO_EMAIL}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
