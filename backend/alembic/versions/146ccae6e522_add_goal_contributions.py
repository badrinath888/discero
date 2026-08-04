"""add goal contributions

Revision ID: 146ccae6e522
Revises: 8adb0528864c
Create Date: 2026-08-04 12:52:51.293315
"""

from datetime import date, datetime, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "146ccae6e522"
down_revision: Union[str, None] = "8adb0528864c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "goal_contributions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("goal_id", sa.Integer(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column(
            "contribution_type",
            sa.String(length=16),
            nullable=False,
        ),
        sa.Column("contributed_on", sa.Date(), nullable=False),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["goal_id"],
            ["savings_goals.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        op.f("ix_goal_contributions_contributed_on"),
        "goal_contributions",
        ["contributed_on"],
        unique=False,
    )
    op.create_index(
        op.f("ix_goal_contributions_contribution_type"),
        "goal_contributions",
        ["contribution_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_goal_contributions_goal_id"),
        "goal_contributions",
        ["goal_id"],
        unique=False,
    )

    connection = op.get_bind()

    existing_goals = connection.execute(
        sa.text(
            """
            SELECT id, saved_cents, created_at
            FROM savings_goals
            WHERE saved_cents > 0
            """
        )
    ).mappings()

    now = datetime.now(timezone.utc)

    for goal in existing_goals:
        created_at = goal["created_at"]

        if isinstance(created_at, datetime):
            contributed_on = created_at.date()
            recorded_at = created_at
        elif isinstance(created_at, date):
            contributed_on = created_at
            recorded_at = now
        else:
            contributed_on = now.date()
            recorded_at = now

        connection.execute(
            sa.text(
                """
                INSERT INTO goal_contributions (
                    goal_id,
                    amount_cents,
                    contribution_type,
                    contributed_on,
                    note,
                    created_at,
                    updated_at
                )
                VALUES (
                    :goal_id,
                    :amount_cents,
                    :contribution_type,
                    :contributed_on,
                    :note,
                    :created_at,
                    :updated_at
                )
                """
            ),
            {
                "goal_id": goal["id"],
                "amount_cents": goal["saved_cents"],
                "contribution_type": "deposit",
                "contributed_on": contributed_on,
                "note": "Opening balance",
                "created_at": recorded_at,
                "updated_at": recorded_at,
            },
        )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_goal_contributions_goal_id"),
        table_name="goal_contributions",
    )
    op.drop_index(
        op.f("ix_goal_contributions_contribution_type"),
        table_name="goal_contributions",
    )
    op.drop_index(
        op.f("ix_goal_contributions_contributed_on"),
        table_name="goal_contributions",
    )
    op.drop_table("goal_contributions")