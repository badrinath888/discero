from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)

    email: Mapped[str] = mapped_column(
        String(320),
        unique=True,
        index=True,
    )

    password_hash: Mapped[str] = mapped_column(String(255))

    token_version: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
    )

    email_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="0",
    )

    password_reset_token_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        unique=True,
        index=True,
    )

    password_reset_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    email_verification_token_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        unique=True,
        index=True,
    )

    email_verification_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
    )

    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

    budgets: Mapped[list["Budget"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

    recurring_items: Mapped[list["RecurringItem"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

    savings_goals: Mapped[list["SavingsGoal"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

    plaid_items: Mapped[list["PlaidItem"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )

    financial_account_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "financial_accounts.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    provider_transaction_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        unique=True,
        index=True,
    )

    posted_on: Mapped[date] = mapped_column(
        Date,
        index=True,
    )

    description: Mapped[str] = mapped_column(String(512))

    merchant_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    amount_cents: Mapped[int] = mapped_column(Integer)

    category: Mapped[str] = mapped_column(
        String(64),
        default="Uncategorized",
        index=True,
    )

    category_locked: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="0",
    )

    source: Mapped[str] = mapped_column(
        String(16),
        default="csv",
        server_default="csv",
        index=True,
    )

    pending: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="0",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
    )

    user: Mapped["User"] = relationship(
        back_populates="transactions",
    )

    financial_account: Mapped[
        "FinancialAccount | None"
    ] = relationship(
        back_populates="transactions",
    )

    @property
    def account_name(self) -> str | None:
        if self.financial_account is None:
            return None

        return self.financial_account.name

    @property
    def institution_name(self) -> str | None:
        if self.financial_account is None:
            return None

        return self.financial_account.plaid_item.institution_name


class Budget(Base):
    __tablename__ = "budgets"

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "category",
            "month",
            name="uq_budget_user_category_month",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )

    category: Mapped[str] = mapped_column(String(64))

    month: Mapped[str] = mapped_column(
        String(7),
        index=True,
    )

    limit_cents: Mapped[int] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
    )

    user: Mapped["User"] = relationship(
        back_populates="budgets",
    )


class RecurringItem(Base):
    __tablename__ = "recurring_items"

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "normalized_merchant",
            name="uq_recurring_item_user_merchant",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )

    merchant: Mapped[str] = mapped_column(
        String(255),
    )

    normalized_merchant: Mapped[str] = mapped_column(
        String(255),
        index=True,
    )

    category: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    amount_cents: Mapped[int] = mapped_column(Integer)

    frequency: Mapped[str] = mapped_column(
        String(32),
        index=True,
    )

    last_payment: Mapped[date] = mapped_column(Date)

    next_payment: Mapped[date] = mapped_column(
        Date,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        String(32),
        default="suggested",
        server_default="suggested",
        index=True,
    )

    confidence_score: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        server_default="0",
    )

    price_change_percent: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        server_default="0",
    )

    price_change_warning: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="0",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
    )

    user: Mapped["User"] = relationship(
        back_populates="recurring_items",
    )


class SavingsGoal(Base):
    __tablename__ = "savings_goals"

    id: Mapped[int] = mapped_column(primary_key=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )

    name: Mapped[str] = mapped_column(
        String(120),
        index=True,
    )

    target_cents: Mapped[int] = mapped_column(Integer)

    saved_cents: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
    )

    target_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
    )

    user: Mapped["User"] = relationship(
        back_populates="savings_goals",
    )

    contributions: Mapped[list["GoalContribution"]] = relationship(
        back_populates="goal",
        cascade="all, delete-orphan",
        order_by="GoalContribution.contributed_on.desc()",
    )


class GoalContribution(Base):
    __tablename__ = "goal_contributions"

    id: Mapped[int] = mapped_column(primary_key=True)

    goal_id: Mapped[int] = mapped_column(
        ForeignKey(
            "savings_goals.id",
            ondelete="CASCADE",
        ),
        index=True,
    )

    amount_cents: Mapped[int] = mapped_column(Integer)

    contribution_type: Mapped[str] = mapped_column(
        String(16),
        index=True,
    )

    contributed_on: Mapped[date] = mapped_column(
        Date,
        default=date.today,
        index=True,
    )

    note: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
    )

    goal: Mapped["SavingsGoal"] = relationship(
        back_populates="contributions",
    )


class PlaidItem(Base):
    __tablename__ = "plaid_items"

    id: Mapped[int] = mapped_column(primary_key=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )

    provider_item_id: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
    )

    institution_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    institution_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    access_token_ciphertext: Mapped[str] = mapped_column(
        String(2048),
    )

    status: Mapped[str] = mapped_column(
        String(32),
        default="active",
        index=True,
    )

    sync_cursor: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )

    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_sync_attempted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    sync_status: Mapped[str] = mapped_column(
        String(32),
        default="idle",
        server_default="idle",
        index=True,
    )

    sync_error: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
    )

    user: Mapped["User"] = relationship(
        back_populates="plaid_items",
    )

    accounts: Mapped[list["FinancialAccount"]] = relationship(
        back_populates="plaid_item",
        cascade="all, delete-orphan",
    )


class FinancialAccount(Base):
    __tablename__ = "financial_accounts"

    __table_args__ = (
        # Plaid account IDs are scoped to an Item, not globally unique.
        UniqueConstraint(
            "plaid_item_id",
            "provider_account_id",
            name="uq_financial_account_item_provider_account_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    plaid_item_id: Mapped[int] = mapped_column(
        ForeignKey(
            "plaid_items.id",
            ondelete="CASCADE",
        ),
        index=True,
    )

    provider_account_id: Mapped[str] = mapped_column(
        String(255),
        index=True,
    )

    name: Mapped[str] = mapped_column(String(255))

    official_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    account_type: Mapped[str] = mapped_column(
        String(64),
        index=True,
    )

    account_subtype: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    mask: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
    )

    current_balance_cents: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    available_balance_cents: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    currency: Mapped[str] = mapped_column(
        String(3),
        default="USD",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
    )

    plaid_item: Mapped["PlaidItem"] = relationship(
        back_populates="accounts",
    )

    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="financial_account",
    )


class SavedDecision(Base):
    __tablename__ = "saved_decisions"

    id: Mapped[int] = mapped_column(primary_key=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )

    decision_type: Mapped[str] = mapped_column(
        String(32),
        index=True,
    )

    title: Mapped[str] = mapped_column(String(120))

    input_snapshot: Mapped[dict] = mapped_column(JSON)

    result_snapshot: Mapped[dict] = mapped_column(JSON)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        index=True,
    )
