"""Confidence & Data Freshness Intelligence 1.0.

A deterministic FACTUAL-AGE read model over already-persisted
transaction/Plaid-sync timestamps -- never a new calculation-confidence
engine, and never blended into any existing engine's own confidence
score. Data freshness answers "how recent is the data behind this
analysis"; calculation confidence (already surfaced by individual
decision engines) answers a different question entirely, so the two are
always shown as separate figures, never combined into one invented
score.

Only two queries, both bounded aggregate scalars (MAX over an indexed
column) -- never a full transaction/account history load.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import PlaidItem, Transaction
from app.schemas import DataFreshnessOut, DataFreshnessStatus

# Mirrors the "stale data" target already used by
# app/services/forecast_confidence_service.py's calculation-confidence
# factor, so "stale" means the same thing in both places even though
# this is a separate, purely factual signal.
_STALE_DATA_TARGET_DAYS = 30
_CURRENT_MAX_DAYS = 2


def _as_date(value: datetime) -> date:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).date()


def _classify_status(
    days_since_transaction: int | None,
    days_since_account_update: int | None,
) -> DataFreshnessStatus:
    candidates = [
        days
        for days in (days_since_transaction, days_since_account_update)
        if days is not None
    ]

    if not candidates:
        return "unavailable"

    days = min(candidates)

    if days <= _CURRENT_MAX_DAYS:
        return "current"
    if days <= _STALE_DATA_TARGET_DAYS:
        return "recent"
    return "stale"


def _build_notices(
    *,
    latest_transaction_date: date | None,
    account_data_updated_at: datetime | None,
) -> list[str]:
    notices: list[str] = []

    if latest_transaction_date is not None:
        notices.append(
            "Transactions current through "
            f"{latest_transaction_date.isoformat()}."
        )
    else:
        notices.append("No transaction history is available yet.")

    if account_data_updated_at is not None:
        notices.append(
            "Accounts last refreshed "
            f"{_as_date(account_data_updated_at).isoformat()}."
        )
    else:
        notices.append("No linked account sync history is available.")

    return notices


def get_data_freshness(
    db: Session,
    user_id: int,
    *,
    as_of: date | None = None,
) -> DataFreshnessOut:
    evaluated_at = as_of or date.today()

    latest_transaction_date = db.scalar(
        select(func.max(Transaction.posted_on)).where(
            Transaction.user_id == user_id
        )
    )

    # Only currently active/connected items count as evidence of a
    # current account sync -- a disconnected item's historical
    # last_synced_at must never make stale/disconnected data look
    # freshly refreshed. "active" mirrors the same status check already
    # used by safe_to_spend_service/financial_resilience_service/
    # copilot_service for "is this Plaid connection currently usable".
    account_data_updated_at = db.scalar(
        select(func.max(PlaidItem.last_synced_at)).where(
            PlaidItem.user_id == user_id,
            PlaidItem.status == "active",
        )
    )

    days_since_latest_transaction = (
        max((evaluated_at - latest_transaction_date).days, 0)
        if latest_transaction_date is not None
        else None
    )
    days_since_account_update = (
        max((evaluated_at - _as_date(account_data_updated_at)).days, 0)
        if account_data_updated_at is not None
        else None
    )

    freshness_status = _classify_status(
        days_since_latest_transaction, days_since_account_update
    )

    return DataFreshnessOut(
        evaluated_at=evaluated_at,
        latest_transaction_date=latest_transaction_date,
        days_since_latest_transaction=days_since_latest_transaction,
        account_data_updated_at=account_data_updated_at,
        days_since_account_update=days_since_account_update,
        freshness_status=freshness_status,
        notices=_build_notices(
            latest_transaction_date=latest_transaction_date,
            account_data_updated_at=account_data_updated_at,
        ),
    )
