"""add api_keys

Revision ID: f4d56214628a
Revises: e831f3829f6e
Create Date: 2026-09-14 06:13:49.758645+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f4d56214628a"
down_revision: str | None = "e831f3829f6e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_keys")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_api_keys_token_hash")),
    )
    op.create_index("ix_api_keys_created_at", "api_keys", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_table("api_keys")
