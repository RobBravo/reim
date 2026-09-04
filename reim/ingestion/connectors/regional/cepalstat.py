"""The CEPALSTAT protocol, shared by every connector that reads it.

``api-cepalstat.cepal.org`` serves an undocumented REST API. There is no
published documentation and no interactive schema: the base URL and the route
names were recovered from the portal's own JavaScript —
``statistics.cepal.org/portal/databank/config.js`` declares ``API_BASE_URL``
and ``ENDPOINT_THEMATIC_TREE``, and ``.../cepalstat/dash/scripts/config.js``
declares the per-indicator data, dimensions, sources and notes routes. That
search is recorded here so nobody repeats it.

Three properties of the source are common to every indicator family and live
here; everything else belongs to the connector that reads its family.

1. **One request returns an indicator's whole matrix** — every country by every
   period, no pagination and no window to compute. A rebuild is therefore
   complete by default, as with Banguat and SIECA.
2. **Dimensions are addressed by numeric id, never by name.** Row keys embed
   the id (``dim_208``, ``dim_29117``) and the names are language-dependent:
   ``Years__ESTANDAR`` in English is ``Años__ESTANDAR`` in Spanish.
3. **The envelope carries its own status, and it can disagree with the HTTP
   code.** An unknown indicator id answers ``500`` with ``success: false``, not
   ``404``, so every ``extract`` reads ``header.success`` rather than trusting
   the status line alone.

This base class is deliberately not a generic CEPALSTAT engine. It holds the
protocol — the envelope, the JSON decode, a dimension's member table, a row's
label and a row's value — and nothing about any indicator family's shape. Each
connector still names its own dimensions and writes its own ``extract``,
``transform`` and ``validate``: GDP reads a country-by-year matrix, the monetary
aggregates carry a third period-within-year dimension, and public debt carries
four. Merging those transforms was rejected in design and stays rejected.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from reim.core.exceptions import ExtractionError, TransformationError
from reim.ingestion.base import BaseConnector

#: Dimension ids, identical across every indicator family read so far.
#: Addressed by id because the row keys embed it and the names change with
#: ``lang``.
COUNTRY_DIMENSION = 208
YEARS_DIMENSION = 29117


class CepalstatConnector(BaseConnector):
    """What every CEPALSTAT connector needs before it reads its own series."""

    def _ensure_envelope_ok(self, text: str, cepal_id: int, url: str) -> None:
        """Read CEPAL's own status, which can disagree with the HTTP code.

        An unknown indicator id answers ``500`` with ``success: false``, so the
        envelope is the authority on whether a response is usable.

        Raises:
            ExtractionError: The envelope reports failure or carries no rows.
        """
        try:
            document = json.loads(text)
            header = document["header"]
            rows = document["body"]["data"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            msg = f"CEPALSTAT returned an unreadable envelope for indicator {cepal_id}: {exc}"
            raise ExtractionError(msg, source_key=self.source.key, url=url) from exc

        if not header.get("success", False):
            detail = str(header.get("message") or "no message").strip()
            code = header.get("code", "?")
            msg = f"CEPALSTAT reported failure {code} for indicator {cepal_id}: {detail}"
            raise ExtractionError(msg, source_key=self.source.key, url=url)

        if not rows:
            msg = f"CEPALSTAT returned no rows for indicator {cepal_id}"
            raise ExtractionError(msg, source_key=self.source.key, url=url)

    def _decode(self, text: str, cepal_id: int) -> Any:
        """Decode JSON, keeping published decimals exact."""
        try:
            return json.loads(text, parse_float=Decimal)
        except json.JSONDecodeError as exc:
            msg = f"CEPALSTAT returned malformed JSON for indicator {cepal_id}: {exc}"
            raise TransformationError(msg, source_key=self.source.key) from exc

    def _members_of(self, body: Any, dimension_id: int, name: str, cepal_id: int) -> dict[int, str]:
        """Build the ``member id -> label`` map from the response itself.

        Never computed from the id arithmetically. For the years dimension
        ``year = id - 27170`` holds only inside the 1990-2025 window; across
        the full dimension it breaks for 130 of 201 members — id 68109 maps to
        "1900", 29118 to "1951", 29119 to "1950" — with six distinct offsets
        overall. The period dimension is worse: its members are not even in
        calendar order. Nothing about an id is a documented or reliable
        contract.

        Raises:
            TransformationError: The dimension is absent.
        """
        for dimension in body.get("dimensions", []):
            if dimension.get("id") == dimension_id:
                return {member["id"]: str(member["name"]) for member in dimension["members"]}
        msg = f"CEPALSTAT returned no {name} dimension for indicator {cepal_id}"
        raise TransformationError(msg, source_key=self.source.key)

    def _label_of(
        self, row: Any, labels: dict[int, str], dimension_id: int, name: str, cepal_id: int
    ) -> str:
        """Resolve a row's label for one dimension.

        Raises:
            TransformationError: The row names a member that does not exist.
        """
        member = row.get(f"dim_{dimension_id}")
        label = labels.get(member)
        if label is None:
            msg = (
                f"CEPALSTAT row for indicator {cepal_id} names an unknown {name} member {member!r}"
            )
            raise TransformationError(msg, source_key=self.source.key)
        return label

    def _value_of(self, row: Any, cepal_id: int) -> Decimal:
        """Read a published figure exactly.

        Raises:
            TransformationError: The value is absent or not a number.
        """
        try:
            return Decimal(str(row["value"]))
        except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
            msg = f"CEPALSTAT returned an unreadable value for indicator {cepal_id}: {exc}"
            raise TransformationError(msg, source_key=self.source.key) from exc
