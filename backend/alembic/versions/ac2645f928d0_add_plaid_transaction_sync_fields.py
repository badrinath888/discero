"""add plaid transaction sync fields

Revision ID: ac2645f928d0
Revises: f77d39a9c4e0
Create Date: 2026-07-30 14:18:17.562656
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "ac2645f928d0"
down_revision: Union[str, None] = "f77d39a9c4e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FK_NAME = "fk_transactions_financial_account_id"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    columns = {
        column["name"]
        for column in inspector.get_columns("transactions")
    }

    if "financial_account_id" not in columns:
        op.add_column(
            "transactions",
            sa.Column(
                "financial_account_id",
                sa.Integer(),
                nullable=True,
            ),
        )

    if "provider_transaction_id" not in columns:
        op.add_column(
            "transactions",
            sa.Column(
                "provider_transaction_id",
                sa.String(length=255),
                nullable=True,
            ),
        )

    if "merchant_name" not in columns:
        op.add_column(
            "transactions",
            sa.Column(
                "merchant_name",
                sa.String(length=255),
                nullable=True,
            ),
        )

    if "source" not in columns:
        op.add_column(
            "transactions",
            sa.Column(
                "source",
                sa.String(length=16),
                server_default="csv",
                nullable=False,
            ),
        )

    if "pending" not in columns:
        op.add_column(
            "transactions",
            sa.Column(
                "pending",
                sa.Boolean(),
                server_default="0",
                nullable=False,
            ),
        )

    inspector = sa.inspect(bind)
    indexes = {
        index["name"]
        for index in inspector.get_indexes("transactions")
    }

    if "ix_transactions_financial_account_id" not in indexes:
        op.create_index(
            "ix_transactions_financial_account_id",
            "transactions",
            ["financial_account_id"],
            unique=False,
        )

    if "ix_transactions_provider_transaction_id" not in indexes:
        op.create_index(
            "ix_transactions_provider_transaction_id",
            "transactions",
            ["provider_transaction_id"],
            unique=True,
        )

    if "ix_transactions_source" not in indexes:
        op.create_index(
            "ix_transactions_source",
            "transactions",
            ["source"],
            unique=False,
        )

    inspector = sa.inspect(bind)
    foreign_keys = inspector.get_foreign_keys("transactions")

    has_account_foreign_key = any(
        foreign_key["constrained_columns"]
        == ["financial_account_id"]
        and foreign_key["referred_table"]
        == "financial_accounts"
        for foreign_key in foreign_keys
    )

    if not has_account_foreign_key:
        with op.batch_alter_table(
            "transactions",
            recreate="always",
        ) as batch_op:
            batch_op.create_foreign_key(
                FK_NAME,
                "financial_accounts",
                ["financial_account_id"],
                ["id"],
                ondelete="SET NULL",
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    foreign_keys = inspector.get_foreign_keys("transactions")

    has_account_foreign_key = any(
        foreign_key["constrained_columns"]
        == ["financial_account_id"]
        and foreign_key["referred_table"]
        == "financial_accounts"
        for foreign_key in foreign_keys
    )

    if has_account_foreign_key:
        with op.batch_alter_table(
            "transactions",
            recreate="always",
        ) as batch_op:
            batch_op.drop_constraint(
                FK_NAME,
                type_="foreignkey",
            )

    inspector = sa.inspect(bind)
    indexes = {
        index["name"]
        for index in inspector.get_indexes("transactions")
    }

    if "ix_transactions_source" in indexes:
        op.drop_index(
            "ix_transactions_source",
            table_name="transactions",
        )

    if "ix_transactions_provider_transaction_id" in indexes:
        op.drop_index(
            "ix_transactions_provider_transaction_id",
            table_name="transactions",
        )

    if "ix_transactions_financial_account_id" in indexes:
        op.drop_index(
            "ix_transactions_financial_account_id",
            table_name="transactions",
        )

    inspector = sa.inspect(bind)
    columns = {
        column["name"]
        for column in inspector.get_columns("transactions")
    }

    with op.batch_alter_table("transactions") as batch_op:
        if "pending" in columns:
            batch_op.drop_column("pending")

        if "source" in columns:
            batch_op.drop_column("source")

        if "merchant_name" in columns:
            batch_op.drop_column("merchant_name")

        if "provider_transaction_id" in columns:
            batch_op.drop_column("provider_transaction_id")

        if "financial_account_id" in columns:
            batch_op.drop_column("financial_account_id")
