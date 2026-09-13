"""add alert_states

Revision ID: e831f3829f6e
Revises: 9b55f6392677
Create Date: 2026-09-13 05:14:39.098587+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e831f3829f6e"
down_revision: str | None = "9b55f6392677"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "alert_states",
        sa.Column("condition", sa.String(length=32), nullable=False),
        sa.Column("pipeline_key", sa.String(length=120), nullable=False),
        sa.Column("first_notified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_notified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alert_states")),
    )
    op.create_index("ix_alert_states_pipeline_key", "alert_states", ["pipeline_key"], unique=False)
    op.create_index(
        "uq_alert_states_open_condition_pipeline",
        "alert_states",
        ["condition", "pipeline_key"],
        unique=True,
        postgresql_where=sa.text("resolved_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("alert_states")
