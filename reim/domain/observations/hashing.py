"""Deterministic hashing used for change detection and duplicate detection.

Two distinct identities matter:

``natural_key``
    Which datapoint this is — country, indicator, source and reporting period.
    Enforced by a database ``UNIQUE`` constraint, so idempotency never depends
    on a hash collision assumption.

``content_hash``
    What the datapoint currently says. A second arrival with the same natural
    key but a different content hash is an upstream *revision*, not a duplicate.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal
from typing import Any

HASH_ALGORITHM = "sha256"


def normalize_decimal(value: Decimal | None) -> str | None:
    """Render a decimal canonically so ``1.50`` and ``1.5`` hash identically."""
    if value is None:
        return None
    normalized = value.normalize()
    # normalize() yields exponent notation for integers (1E+3); expand it back.
    if normalized == normalized.to_integral_value():
        normalized = normalized.quantize(Decimal(1))
    return format(normalized, "f")


def natural_key(
    *,
    country_iso3: str,
    indicator_code: str,
    source_key: str,
    period_start: date,
    period_end: date,
) -> tuple[str, str, str, str, str]:
    """Return the tuple that uniquely identifies an observation."""
    return (
        country_iso3.upper(),
        indicator_code.lower(),
        source_key.lower(),
        period_start.isoformat(),
        period_end.isoformat(),
    )


def natural_key_digest(**kwargs: Any) -> str:
    """Return a stable hex digest of :func:`natural_key`.

    Handy as a log/correlation identifier; the database constraint remains the
    authority on uniqueness.
    """
    payload = "|".join(natural_key(**kwargs))
    return hashlib.new(HASH_ALGORITHM, payload.encode("utf-8")).hexdigest()


def content_hash(
    *,
    country_iso3: str,
    indicator_code: str,
    source_key: str,
    period_start: date,
    period_end: date,
    value_numeric: Decimal | None,
    value_text: str | None = None,
    unit: str,
    currency_code: str | None = None,
) -> str:
    """Return the SHA-256 digest of an observation's canonical payload.

    Deliberately excludes ``retrieved_at``, ``connector_version`` and
    ``pipeline_version``: re-running the same pipeline against unchanged data
    must produce the same hash, otherwise every run would look like a revision.
    """
    payload: dict[str, Any] = {
        "country": country_iso3.upper(),
        "indicator": indicator_code.lower(),
        "source": source_key.lower(),
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "value_numeric": normalize_decimal(value_numeric),
        "value_text": value_text,
        "unit": unit.strip(),
        "currency_code": currency_code.upper() if currency_code else None,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.new(HASH_ALGORITHM, canonical.encode("utf-8")).hexdigest()
