"""Response models for the cross-country comparison endpoint."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from reim.core.constants import Frequency
from reim.repositories.comparison import SeriesSummary
from reim.schemas.common import PageMeta


def assess_comparability(summaries: list[SeriesSummary]) -> tuple[bool, list[str]]:
    """Decide whether these series may be read against each other, and why not.

    Comparability turns on **unit and currency only**. Differing sources are
    reported but do not make series incomparable: two publishers measuring the
    same thing in the same unit is ordinary, and conflating that with a unit
    mismatch would cry wolf. Having no data at all is a gap to report, not an
    incomparability.

    Args:
        summaries: One per requested country, empty series included.

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


class ComparisonRow(BaseModel):
    """One period, with an entry for every requested country."""

    period_start: date
    period_end: date
    period_label: str
    values: dict[str, Decimal | None] = Field(
        description="Country ISO-3 to value. Null where that country has no figure."
    )


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
    comparability_notes: list[str]
    series: list[ComparisonSeries]
    data: list[ComparisonRow]
