"""add copilot audit events

Revision ID: d8c4a1f6b3e2
Revises: b3f1c7a9d2e4
Create Date: 2026-08-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d8c4a1f6b3e2"
down_revision: Union[str, None] = "b3f1c7a9d2e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "copilot_audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("tool_name", sa.String(64), nullable=True),
        sa.Column("intent", sa.String(64), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=True),
        sa.Column("error_code", sa.String(32), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("model", sa.String(64), nullable=True),
        sa.Column("tool_call_count", sa.Integer(), nullable=True),
        sa.Column("response_kind", sa.String(32), nullable=True),
        sa.Column("provenance", sa.String(16), nullable=True),
        sa.Column("event_metadata", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_copilot_audit_events_user_id",
        "copilot_audit_events",
        ["user_id"],
    )
    op.create_index(
        "ix_copilot_audit_events_created_at",
        "copilot_audit_events",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_copilot_audit_events_created_at",
        table_name="copilot_audit_events",
    )
    op.drop_index(
        "ix_copilot_audit_events_user_id",
        table_name="copilot_audit_events",
    )
    op.drop_table("copilot_audit_events")
