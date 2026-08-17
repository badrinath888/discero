"""add decision outcome tracking

Revision ID: fcca0ee66f34
Revises: d8c4a1f6b3e2
Create Date: 2026-08-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "fcca0ee66f34"
down_revision: Union[str, None] = "d8c4a1f6b3e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "saved_decisions",
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="saved",
        ),
    )
    op.add_column(
        "saved_decisions",
        sa.Column(
            "acted_on_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_saved_decisions_status",
        "saved_decisions",
        ["status"],
    )

    op.create_table(
        "decision_outcomes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "decision_id",
            sa.Integer(),
            sa.ForeignKey("saved_decisions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "evaluated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("current_result_snapshot", sa.JSON(), nullable=False),
        sa.Column("comparison_snapshot", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_decision_outcomes_decision_id",
        "decision_outcomes",
        ["decision_id"],
    )
    op.create_index(
        "ix_decision_outcomes_user_id",
        "decision_outcomes",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_decision_outcomes_user_id",
        table_name="decision_outcomes",
    )
    op.drop_index(
        "ix_decision_outcomes_decision_id",
        table_name="decision_outcomes",
    )
    op.drop_table("decision_outcomes")

    op.drop_index(
        "ix_saved_decisions_status",
        table_name="saved_decisions",
    )
    op.drop_column("saved_decisions", "acted_on_at")
    op.drop_column("saved_decisions", "status")
