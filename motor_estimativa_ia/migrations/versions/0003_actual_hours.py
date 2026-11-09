"""Horas realizadas por atividade de estimativa aprovada (histórico e calibração).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-09
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

TIMESTAMP = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "actual_hours",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("estimate_id", UUID(as_uuid=True), sa.ForeignKey("estimates.id"), nullable=False),
        sa.Column("task_id", sa.Text, nullable=False),
        sa.Column("activity_id", sa.Text, nullable=False),
        sa.Column("actual_hours", sa.Numeric(10, 2), nullable=False),
        sa.Column("ai_used", sa.Boolean, nullable=False),
        sa.Column("notes", sa.Text),
        sa.Column("recorded_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("recorded_at", TIMESTAMP, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TIMESTAMP, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("estimate_id", "task_id", "activity_id", name="uq_actual_hours_activity"),
        sa.CheckConstraint("actual_hours >= 0", name="ck_actual_hours_nonnegative"),
    )
    op.create_index("ix_actual_hours_estimate_id", "actual_hours", ["estimate_id"])


def downgrade() -> None:
    op.drop_table("actual_hours")
