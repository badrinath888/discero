"""harden plaid sync lifecycle

Revision ID: 7d9c2a4e6b10
Revises: e7b1c9d4a2f6
Create Date: 2026-08-03
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7d9c2a4e6b10"
down_revision: Union[str, None] = "e7b1c9d4a2f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("plaid_items") as batch_op:
        batch_op.add_column(
            sa.Column(
                "last_sync_attempted_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "sync_status",
                sa.String(length=32),
                server_default="idle",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "sync_error",
                sa.String(length=255),
                nullable=True,
            )
        )
        batch_op.create_index(
            "ix_plaid_items_sync_status",
            ["sync_status"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("plaid_items") as batch_op:
        batch_op.drop_index("ix_plaid_items_sync_status")
        batch_op.drop_column("sync_error")
        batch_op.drop_column("sync_status")
        batch_op.drop_column("last_sync_attempted_at")
