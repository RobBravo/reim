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

This base class is deliberately not a generic CEPALSTAT engine. It holds two
things. The first is the protocol — the envelope, the JSON decode, a
dimension's member table, a row's label and a row's value. The second is
behaviour that is about periods rather than about any family's shape:
``_check_monthly_continuity`` walks each country's own span looking for holes
and would read identically in every monthly connector, so it lives here rather
than being copied. Dimension 3981 is the one exception, and it earns it: the
period-within-year member table is a property of the dimension, not of a
family. Two families carry it — the monetary aggregates and the interest
rates — with the same seventeen members, the same out-of-order ids and the
same untranslated English names, so ``_months_of_period_dimension`` and
``_month_of_period_dimension`` live here rather than being copied. Everything
else about a family's dimensions still
belongs to its own connector. Each connector still names its own dimensions
and writes its own ``extract``, ``transform`` and ``validate``: GDP reads a
country-by-year matrix, public debt carries four dimensions, and the exchange
rate carries a twelve-member month dimension of its own. Merging those
transforms was rejected in design and stays rejected.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from reim.core.constants import CheckSeverity, CheckType
from reim.core.exceptions import ExtractionError, TransformationError
from reim.domain.pipelines.models import NormalizedObservation, QualityResult
from reim.ingestion.base import BaseConnector

#: Dimension ids, identical across every indicator family read so far.
#: Addressed by id because the row keys embed it and the names change with
#: ``lang``.
COUNTRY_DIMENSION = 208
YEARS_DIMENSION = 29117

#: The period-within-year dimension. Belongs to the dimension rather than to
#: any family: the monetary aggregates and the interest rates both carry it,
#: with the same seventeen members and the same ids.
PERIOD_DIMENSION = 3981

#: The only member names that become observations. Read from the Spanish
#: dimensions response, because ``lang=en`` returns all seventeen members as
#: the untranslated string ``descripcion_ingles`` and the ids run 3982-3998
#: out of calendar order, with September at 3993 and July at 3994.
MONTHS_BY_SPANISH_NAME = {
    "Enero": 1,
    "Febrero": 2,
    "Marzo": 3,
    "Abril": 4,
    "Mayo": 5,
    "Junio": 6,
    "Julio": 7,
    "Agosto": 8,
    "Septiembre": 9,
    "Octubre": 10,
    "Noviembre": 11,
    "Diciembre": 12,
}

#: The only period members that are legitimately not months. Together with
#: ``MONTHS_BY_SPANISH_NAME`` this makes the label classification total: any
#: label in neither set is a contract break (a rename or an unannounced new
#: member) and must raise rather than silently fall out as "not a month".
#:
#: What these members *mean* differs by family, and neither connector stores
#: them either way: for the monetary aggregates they restate a period-end
#: stock exactly, and for the interest rates they are means of their months.
NON_MONTH_MEMBERS = frozenset({"Anual", "Trimestre 1", "Trimestre 2", "Trimestre 3", "Trimestre 4"})


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

    def _assert_member_names(
        self,
        body: Any,
        dimension_id: int,
        name: str,
        expected: Mapping[int, str],
        cepal_id: int,
    ) -> None:
        """Confirm each selected member id in ``expected`` still carries its name.

        Rows are filtered by member id, which is silent when CEPAL relabels a
        member: the filter keeps matching and REIM stores a different series
        under the same indicator code. Reading the dimension's member table
        back turns that into a message naming the first id that changed.

        Raises:
            TransformationError: The dimension is absent, or a member in
                ``expected`` no longer carries the name it meant.
        """
        members = self._members_of(body, dimension_id, name, cepal_id)
        for member_id, expected_name in expected.items():
            actual = members.get(member_id)
            if actual != expected_name:
                msg = (
                    f"CEPALSTAT {name} member {member_id} for indicator {cepal_id} "
                    f"is now {actual!r}, not {expected_name!r}; the stored series "
                    f"would change meaning silently"
                )
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

    def _months_of_period_dimension(
        self, dimensions_document: Any, cepal_id: int
    ) -> dict[int, int | None]:
        """Map each period member id to a month number, or ``None`` to skip.

        Shared by every family that carries dimension 3981.

        ``None`` marks the annual and quarterly members, which restate a month
        exactly and are not stored. The classification is total: a label that
        is neither a known month nor a known non-month member means CEPAL
        renamed or added one, which is a contract break, not a row to drop.

        Raises:
            TransformationError: The period dimension is absent, or one of its
                members carries a label that is neither in
                ``MONTHS_BY_SPANISH_NAME`` nor in ``NON_MONTH_MEMBERS``.
        """
        members = self._members_of(
            dimensions_document["body"], PERIOD_DIMENSION, "period", cepal_id
        )
        months: dict[int, int | None] = {}
        for member_id, label in members.items():
            if label in MONTHS_BY_SPANISH_NAME:
                months[member_id] = MONTHS_BY_SPANISH_NAME[label]
            elif label in NON_MONTH_MEMBERS:
                months[member_id] = None
            else:
                msg = (
                    f"CEPALSTAT period dimension for indicator {cepal_id} names an "
                    f"unrecognized member {label!r}: neither a known month nor a known "
                    f"non-month member. CEPAL renamed or added a period member."
                )
                raise TransformationError(msg, source_key=self.source.key)
        return months

    def _month_of_period_dimension(
        self, row: Any, months: dict[int, int | None], cepal_id: int
    ) -> int | None:
        """Resolve a row's month, or ``None`` when it is a restatement.

        Raises:
            TransformationError: The row names a period member id that is not
                in ``months`` at all, which means the id itself does not
                exist in the dimension's member table.
        """
        member = row.get(f"dim_{PERIOD_DIMENSION}")
        if member not in months:
            msg = (
                f"CEPALSTAT row for indicator {cepal_id} names an unknown period member {member!r}"
            )
            raise TransformationError(msg, source_key=self.source.key)
        return months[member]

    def _check_country_coverage(
        self,
        observations: list[NormalizedObservation],
        expected: Mapping[str, frozenset[str]],
        check_name: str,
    ) -> QualityResult:
        """Each series carries exactly the countries it is expected to.

        An expectation rather than a floor, so that a country **arriving** is
        reported as loudly as one disappearing: a new country means the
        publisher changed something, which is worth a human reading.

        Named for what it does rather than reusing ``_check_expected_countries``,
        which two sibling connectors already define for a single-indicator
        family with a different signature. Reusing that name here would have
        those subclasses silently shadow this method.

        This only works if the connector's ``transform`` lets unexpected
        countries through. A row filtered out before it becomes an observation
        is invisible here, so a family that excludes a country must condition
        that exclusion on something other than the country itself — see
        ``cepalstat_rates.SeriesSpec.is_artifact``.

        Args:
            observations: Everything ``transform`` produced, all series.
            expected: The country set each indicator code should carry.
            check_name: The result's name. Passed rather than derived, because
                the shipped names do not follow one pattern and changing them
                would break continuity with runs already recorded.
        """
        seen: dict[str, set[str]] = {code: set() for code in expected}
        for obs in observations:
            if obs.indicator_code in seen:
                seen[obs.indicator_code].add(obs.country_iso3)

        problems: list[str] = []
        for code, countries in expected.items():
            for iso3 in sorted(countries - seen[code]):
                problems.append(f"{code} lost {iso3}")
            for iso3 in sorted(seen[code] - countries):
                problems.append(f"{code} gained {iso3}")

        total_expected = str(sum(len(v) for v in expected.values()))
        total_seen = str(sum(len(v) for v in seen.values()))

        if not problems:
            return QualityResult.passed(
                check_name,
                CheckType.COMPLETENESS,
                "Every series carries exactly the countries it is expected to",
                expected_value=total_expected,
                actual_value=total_seen,
            )

        return QualityResult.failure(
            check_name,
            CheckType.COMPLETENESS,
            CheckSeverity.CRITICAL,
            f"{len(problems)} change(s) in country coverage: {', '.join(problems[:5])}",
            expected_value=total_expected,
            actual_value=total_seen,
        )

    def _check_monthly_continuity(self, observations: list[NormalizedObservation]) -> QualityResult:
        """Holes inside each country's own span, per indicator.

        Walked per country and per series: pooling them would hide a hole
        whenever another country published that month, and six of the seven
        usually did.
        """
        spans: dict[tuple[str, str], set[tuple[int, int]]] = {}
        for obs in observations:
            year, month = obs.period.label.split("-")
            spans.setdefault((obs.indicator_code, obs.country_iso3), set()).add(
                (int(year), int(month))
            )

        missing: list[str] = []
        expected = present = 0
        for (code, iso3), months in sorted(spans.items()):
            if len(months) < 2:
                continue
            first, last = min(months), max(months)
            width = (last[0] - first[0]) * 12 + (last[1] - first[1]) + 1
            expected += width
            present += len(months)
            cursor = first
            for _ in range(width):
                if cursor not in months:
                    missing.append(f"{iso3} {cursor[0]}-{cursor[1]:02d} ({code})")
                cursor = (cursor[0] + 1, 1) if cursor[1] == 12 else (cursor[0], cursor[1] + 1)

        if not missing:
            return QualityResult.passed(
                "cepalstat_monthly_continuity",
                CheckType.COMPLETENESS,
                f"No gaps in any of the {len(spans)} country-series",
                expected_value=str(expected),
                actual_value=str(present),
            )

        shown = ", ".join(missing[:5])
        suffix = f" (+{len(missing) - 5} more)" if len(missing) > 5 else ""
        return QualityResult.failure(
            "cepalstat_monthly_continuity",
            CheckType.COMPLETENESS,
            CheckSeverity.WARNING,
            f"{len(missing)} month(s) missing: {shown}{suffix}",
            expected_value=str(expected),
            actual_value=str(present),
        )
