"""scope financial account provider_account_id uniqueness per plaid item

Revision ID: b3f1c7a9d2e4
Revises: 9019a64f6fa2
Create Date: 2026-08-12

Plaid's account_id is stable per Item but is not guaranteed globally
unique across items/users -- Sandbox in particular returns identical
account_id values for identical test credentials connected by different
users, which made the previous global-unique index a real multi-user
correctness bug (second user's account creation would fail with an
IntegrityError). This migration replaces the global unique index with a
composite (plaid_item_id, provider_account_id) unique constraint, which
is the correct scope and is strictly weaker than the old constraint, so
no existing data can violate it.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "b3f1c7a9d2e4"
down_revision: Union[str, None] = "9019a64f6fa2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("financial_accounts") as batch_op:
        batch_op.drop_index("ix_financial_accounts_provider_account_id")
        batch_op.create_index(
            "ix_financial_accounts_provider_account_id",
            ["provider_account_id"],
            unique=False,
        )
        batch_op.create_unique_constraint(
            "uq_financial_account_item_provider_account_id",
            ["plaid_item_id", "provider_account_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("financial_accounts") as batch_op:
        batch_op.drop_constraint(
            "uq_financial_account_item_provider_account_id",
            type_="unique",
        )
        batch_op.drop_index("ix_financial_accounts_provider_account_id")
        batch_op.create_index(
            "ix_financial_accounts_provider_account_id",
            ["provider_account_id"],
            unique=True,
        )
