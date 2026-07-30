from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
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

    id: Mapped[int] = mapped_column(primary_key=True)

    plaid_item_id: Mapped[int] = mapped_column(
        ForeignKey("plaid_items.id", ondelete="CASCADE"),
        index=True,
    )

    provider_account_id: Mapped[str] = mapped_column(
        String(255),
        unique=True,
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
