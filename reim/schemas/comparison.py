"""Response models for the cross-country comparison endpoint."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    model_serializer,
)

from reim.core.constants import Frequency
from reim.domain.indicators.registry import IndicatorDefinition
from reim.repositories.comparison import SeriesSummary
from reim.schemas.common import PageMeta


def levels_comparable(definition: IndicatorDefinition | None) -> bool:
    """Whether these series' **levels** may be read against each other.

    ``comparable`` answers a narrower question than its name suggests: it turns
    on unit and currency agreement. CEPAL's three interest rates share both and
    are still not comparable as levels, because the publisher measures a
    different instrument in each country — Panama's "lending rate" is the rate
    on one-year trade credit, Belize's "policy rate" is its central bank's
    lending rate. A client reading the boolean and not ``comparability_notes``
    was misled about exactly those series.

    This is the structured half of that caveat, so a consumer need not parse
    prose. It does not replace ``comparable``, whose meaning stays as every
    existing caller understands it.

    An indicator absent from the registry returns ``True``: ``/compare`` serves
    such an indicator rather than refusing it, and silence is not a claim that
    levels diverge.
    """
    return definition is None or not definition.methodology_varies_by_country


def assess_comparability(
    summaries: list[SeriesSummary],
    definition: IndicatorDefinition | None = None,
) -> tuple[bool, list[str]]:
    """Decide whether these series may be read against each other, and why not.

    Comparability turns on **unit and currency only**. Differing sources are
    reported but do not make series incomparable: two publishers measuring the
    same thing in the same unit is ordinary, and conflating that with a unit
    mismatch would cry wolf. Having no data at all is a gap to report, not an
    incomparability.

    An indicator whose publisher defines it differently in each country adds a
    note and **does not** flip the flag. CEPAL's interest rates are the case:
    they share a unit and carry no currency, so the flag is true and correct
    on the axes it measures, while their levels still are not readable against
    each other. Flipping it would widen what ``comparable`` means for every
    existing caller and would misreport comparing how two countries' rates
    *moved*, which is sound.

    Args:
        summaries: One per requested country, empty series included.
        definition: The registered indicator, when the caller has it. Only
            ``methodology_varies_by_country`` is read.

    Returns:
        ``(comparable, notes)`` — notes are human-readable and always
        populated when something differs, whether or not it flips the flag.
    """
    notes: list[str] = []

    empty = [s.country_iso3 for s in summaries if s.observations == 0]
    if empty:
        notes.append(f"No observations for this indicator: {', '.join(sorted(empty))}.")

    populated = [s for s in summaries if s.observations > 0]

    mixed_within = sorted(s.country_iso3 for s in populated if len(s.units) > 1)
    if mixed_within:
        notes.append(
            f"More than one unit within a single country's series: {', '.join(mixed_within)}."
        )

    units = {unit for s in populated for unit in s.units}
    currencies = {code for s in populated for code in s.currency_codes}
    if len(units) > 1:
        notes.append(f"Units differ across countries: {', '.join(sorted(units))}.")
    if len(currencies) > 1:
        shown = ", ".join(sorted(code or "none" for code in currencies))
        notes.append(f"Currencies differ across countries: {shown}.")

    # Keyed on the publishing organization, not the catalog key. REIM holds one
    # publisher under several entries — the IMF has one per country — and noting
    # that on every regional comparison would train readers to ignore the notes.
    publishers = {code for s in populated for code in s.organization_codes}
    if len(publishers) > 1:
        notes.append(f"Publishers differ across countries: {', '.join(sorted(publishers))}.")

    if definition is not None and definition.methodology_varies_by_country:
        notes.append(
            "The publisher defines this indicator differently in each country, "
            "so levels are not comparable; movements over time are."
        )

    comparable = len(units) <= 1 and len(currencies) <= 1 and not mixed_within
    return comparable, notes


class ComparisonIndicator(BaseModel):
    """The single indicator being compared."""

    code: str
    name: str
    frequency: Frequency


class ComparisonSeries(BaseModel):
    """What one country brings to the comparison, including nothing at all."""

    model_config = ConfigDict(from_attributes=True)

    country_iso2: str
    country_iso3: str
    country_name: str
    units: list[str]
    currency_codes: list[str | None]
    source_keys: list[str]
    organization_codes: list[str]
    observations: int = Field(description="Active observations for this indicator and country.")
    first_period: str | None
    last_period: str | None


class ConversionBlock(BaseModel):
    """What a converted response did, and what the reader must know about it."""

    model_config = ConfigDict(from_attributes=True)

    target_currency: str
    rate_indicator_code: str
    rate_source_key: str | None
    basis: str
    converted: int
    already_at_target: int
    no_rate: int
    caveats: list[str]


class ComparisonRow(BaseModel):
    """One period, with an entry for every requested country."""

    period_start: date
    period_end: date
    period_label: str
    values: dict[str, Decimal | None] = Field(
        description="Country ISO-3 to value. Null where that country has no figure."
    )
    values_converted: dict[str, Decimal | None] | None = Field(
        default=None,
        description=(
            "Country ISO-3 to the figure in the target currency, beside the published "
            "one and never in place of it. Absent unless convert_to was requested."
        ),
    )
    rates: dict[str, Decimal | None] | None = Field(
        default=None,
        description="The rate applied to each country's cell, or null where none was.",
    )
    rate_basis: dict[str, str | None] | None = Field(
        default=None,
        description="What each rate is; null where no rate was applied.",
    )

    @model_serializer(mode="wrap")
    def _drop_absent_conversion(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """Omit the conversion keys entirely when none was requested.

        A null ``values_converted`` would read as "conversion ran and produced
        nothing", which is a different claim from "conversion was not asked
        for". A blanket ``exclude_none`` is not used because it would also
        strip ``first_period`` and ``last_period`` from a country with no data.
        """
        data: dict[str, Any] = handler(self)
        if self.values_converted is None:
            for key in ("values_converted", "rates", "rate_basis"):
                data.pop(key, None)
        return data


class ComparisonResponse(BaseModel):
    """A period-aligned comparison of one indicator across countries."""

    meta: PageMeta
    indicator: ComparisonIndicator
    comparable: bool = Field(
        description=(
            "False when the series differ in unit or currency. Sources differing does "
            "not make them incomparable."
        )
    )
    levels_comparable: bool = Field(
        default=True,
        description=(
            "False when the publisher defines the indicator differently in each "
            "country, so that levels may not be read against each other even "
            "though the unit and currency match. Movements over time remain "
            "comparable. Distinct from `comparable`, which turns on unit and "
            "currency only."
        ),
    )
    comparability_notes: list[str]
    conversion: ConversionBlock | None = Field(
        default=None,
        description="Present only when convert_to was requested.",
    )
    series: list[ComparisonSeries]
    data: list[ComparisonRow]

    @model_serializer(mode="wrap")
    def _drop_absent_conversion(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """Omit ``conversion`` entirely when none was requested. See ComparisonRow."""
        data: dict[str, Any] = handler(self)
        if self.conversion is None:
            data.pop("conversion", None)
        return data
