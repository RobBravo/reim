"""Issuing, finding and revoking API keys."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from reim.database.models import ApiKey

#: Marks a REIM token in logs and configuration without revealing it.
TOKEN_PREFIX = "reim_"


def generate_token() -> str:
    """Return a new random token. Never stored; shown once."""
    return f"{TOKEN_PREFIX}{secrets.token_urlsafe(32)}"


def hash_token(token: str) -> str:
    """Return the SHA-256 hex digest a token is stored and looked up by."""
    return hashlib.sha256(token.encode()).hexdigest()


def create_key(session: Session, *, label: str, now: datetime) -> tuple[ApiKey, str]:
    """Issue a key, returning the row and the raw token.

    The token is returned exactly once. Nothing stores it, so a caller who
    loses it creates another and revokes this one.
    """
    token = generate_token()
    record = ApiKey(token_hash=hash_token(token), label=label, created_at=now)
    session.add(record)
    session.flush()
    return record, token


def find_by_token(session: Session, token: str) -> ApiKey | None:
    """Return the active key this token belongs to, if any.

    Hashes and selects; nothing is compared against a stored secret. A revoked
    key is not found, which is what makes revocation immediate.
    """
    return session.scalar(
        select(ApiKey).where(
            ApiKey.token_hash == hash_token(token),
            ApiKey.revoked_at.is_(None),
        )
    )


def list_keys(session: Session) -> list[ApiKey]:
    """Return every key ever issued, newest first, revoked ones included."""
    return list(session.scalars(select(ApiKey).order_by(ApiKey.created_at.desc())))


def revoke_key(session: Session, *, key_id: uuid.UUID, now: datetime) -> bool:
    """Revoke a key. Returns False if it does not exist or was already revoked."""
    record = session.scalar(select(ApiKey).where(ApiKey.id == key_id, ApiKey.revoked_at.is_(None)))
    if record is None:
        return False
    record.revoked_at = now
    session.flush()
    return True
