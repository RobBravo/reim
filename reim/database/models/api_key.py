"""API keys: what raises a caller's rate allowance."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from reim.database.base import Base, UUIDPrimaryKeyMixin


class ApiKey(UUIDPrimaryKeyMixin, Base):
    """One issued key, stored only as a hash.

    The raw token exists in the operator's hands and nowhere else: it is shown
    once at creation and cannot be recovered. Lookup hashes the presented token
    and selects by hash, so nothing is ever compared against a stored secret.

    A revoked key is retained rather than deleted — an operator asking "when was
    this revoked" deserves an answer — so ``revoked_at`` is the active/inactive
    switch and no row is ever removed.
    """

    __tablename__ = "api_keys"

    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    label: Mapped[str] = mapped_column(String(120), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_api_keys_created_at", "created_at"),)
