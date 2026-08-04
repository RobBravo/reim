"""Reusable column types.

Enums are persisted as their *values* (``"daily"``, not ``"DAILY"``) in a
``VARCHAR`` column guarded by a ``CHECK`` constraint. Non-native enums keep
Alembic migrations trivial: adding a member is a constraint change, not a
PostgreSQL ``TYPE`` mutation.
"""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import Enum as SAEnum
from sqlalchemy import Numeric

#: Type used for every economic magnitude.
#:
#: Deliberately **unconstrained** ``NUMERIC``: PostgreSQL then stores the value
#: with arbitrary precision and exact semantics. A fixed scale cannot serve this
#: data — the same table holds balance-of-payments aggregates in the billions and
#: pre-redenomination exchange rates around ``2.06064418965517E-9``. An earlier
#: ``NUMERIC(30, 10)`` silently rounded the latter to ``2.1E-9`` and clipped CPI
#: figures to ten decimals, so precision is never traded for a declared width.
EconomicNumeric = Numeric(asdecimal=True)


def enum_column(enum_cls: type[StrEnum], name: str) -> SAEnum:
    """Return a value-persisting, non-native SQL enum for ``enum_cls``.

    Args:
        enum_cls: The :class:`~enum.StrEnum` to persist.
        name: Constraint name used in the generated schema.
    """
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=False,
        length=32,
        validate_strings=True,
        values_callable=lambda cls: [member.value for member in cls],
    )
