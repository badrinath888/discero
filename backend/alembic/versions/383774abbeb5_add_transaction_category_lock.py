"""add transaction category lock

Revision ID: 383774abbeb5
Revises: ac2645f928d0
Create Date: 2026-07-30 14:52:10.718151
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "383774abbeb5"
down_revision: Union[str, None] = "ac2645f928d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "category_locked",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.drop_column("category_locked")
