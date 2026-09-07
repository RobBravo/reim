"""Converting a published figure into dollars, beside it and never instead.

REIM stores what publishers publish. This module is the one place it derives a
number, and every rule here exists to keep that derivation from being mistaken
for a source's own figure.

Three of them matter more than the rest:

* **Conversion keys on the observation's own currency, never on its country.**
  El Salvador transacts in dollars and CEPAL still quotes it at 8.8 colones per
  dollar, twenty-four years after dollarisation. A conversion keyed on the
  country would divide El Salvador's already-dollar figures by 8.8 and look
  entirely plausible doing it.
* **A missing rate is a gap, not a fallback.** No nearest period, no
  carry-forward, no annual average standing in for a month. That would be
  imputation, which REIM does not do.
* **The result is indicative.** The rate is an average across the month while
  the series it converts are end-of-period stocks, and CEPAL publishes no
  end-of-period alternative. That mismatch cannot be fixed, so it travels with
  every figure instead.

See ``docs/superpowers/specs/2026-09-06-currency-conversion-design.md``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from reim.core.exceptions import InvalidRequestError
from reim.domain.indicators.registry import IndicatorDefinition

#: The only target. Rates are local-currency-per-USD, so any other target would
#: mean triangulating through the dollar and squaring the rate's rounding error.
TARGET_CURRENCY = "USD"

RATE_INDICATOR_CODE = "exchange_rate_nominal_monthly"

#: What the rate is, carried per cell so a client charting the converted series
#: cannot miss it.
RATE_BASIS = "monthly average"

#: Converted amounts are quantized to this. The real precision limit is the
#: rate's single published decimal, which ``CAVEATS`` states rather than
#: implying with twenty digits of division.
QUANTUM = Decimal("0.01")

CAVEATS = (
    "Converted figures are indicative. The rate is the average of the daily "
    "rates within the month, while these observations are end-of-period "
    "stocks; CEPAL publishes no end-of-period rate.",
    "The rate is published to one decimal, which is the precision limit of "
    "every figure derived from it.",
)


@dataclass(frozen=True, slots=True)
class ConvertedCell:
    """One cell's converted figure, and what produced it.

    ``rate`` and ``basis`` are ``None`` whenever no rate was applied — both
    when the cell was already at the target and when no rate existed for its
    period. ``value`` distinguishes the two: it carries the untouched figure in
    the first case and ``None`` in the second.
    """

    value: Decimal | None
    rate: Decimal | None
    basis: str | None


#: Nothing was converted and nothing is claimed. Shared because the three ways
#: to arrive here are indistinguishable to a reader of the result.
_NOTHING = ConvertedCell(value=None, rate=None, basis=None)


@dataclass(frozen=True, slots=True)
class ConversionSummary:
    """What a converted response did, and what the reader must know about it."""

    target_currency: str
    rate_indicator_code: str
    #: The source that supplied these rates, when exactly one did. ``None``
    #: when none did — an operator who has never run the rate pipeline gets a
    #: valid response with everything counted under ``no_rate``.
    rate_source_key: str | None
    basis: str
    converted: int
    already_at_target: int
    no_rate: int
    caveats: tuple[str, ...]


def ensure_convertible(definition: IndicatorDefinition) -> None:
    """Refuse an indicator whose values are not amounts in a currency.

    ``ni_exchange_rate_official_daily`` carries ``currency_code = NIO`` and
    means "36.8 NIO **per** USD". Dividing it by a rate returns a confident
    ``1.00``. An amount denominated in a currency and a ratio expressed per
    that currency are different things, and only the registry can tell them
    apart.

    Raises:
        InvalidRequestError: The indicator does not declare itself convertible.
    """
    if not definition.currency_convertible:
        msg = (
            f"Indicator {definition.code!r} does not carry amounts denominated "
            f"in a currency, so it cannot be converted to {TARGET_CURRENCY}"
        )
        raise InvalidRequestError(msg, indicator=definition.code)


def convert(
    value: Decimal | None, currency_code: str | None, rate: Decimal | None
) -> ConvertedCell:
    """Convert one cell. Total, and raises nothing.

    Args:
        value: The published figure, or ``None`` where the publisher has a gap.
        currency_code: The **observation's** currency, never the country's.
        rate: Local currency per USD for exactly this period, or ``None``.
    """
    if value is None or currency_code is None:
        return _NOTHING
    if currency_code == TARGET_CURRENCY:
        return ConvertedCell(value=value, rate=None, basis=None)
    # A zero rate is nonsense rather than a currency event, but it must not
    # become a ZeroDivisionError in the middle of rendering a page.
    if not rate:
        return _NOTHING
    return ConvertedCell(value=(value / rate).quantize(QUANTUM), rate=rate, basis=RATE_BASIS)


def summarise(
    pairs: Iterable[tuple[Decimal | None, ConvertedCell]],
    rate_source_key: str | None,
) -> ConversionSummary:
    """Count the three outcomes and attach the caveats.

    Takes the **published value alongside** each converted cell, because the
    cell alone cannot distinguish "nothing was published" from "no rate
    existed" — both are all-``None``. A cell with nothing published is counted
    in none of the three: ``/compare`` is rectangular, so most cells in a wide
    comparison are holes in the published data, and counting them as missing a
    rate would blame the rate series for the publisher's gap.
    """
    converted = already = no_rate = 0
    for published, cell in pairs:
        if published is None:
            continue
        if cell.rate is not None:
            converted += 1
        elif cell.value is not None:
            already += 1
        else:
            no_rate += 1

    return ConversionSummary(
        target_currency=TARGET_CURRENCY,
        rate_indicator_code=RATE_INDICATOR_CODE,
        rate_source_key=rate_source_key,
        basis=RATE_BASIS,
        converted=converted,
        already_at_target=already,
        no_rate=no_rate,
        caveats=CAVEATS,
    )
