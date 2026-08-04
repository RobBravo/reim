"""Canonical indicator definitions for the MVP.

An indicator is a *concept* (``ni_cpi_inflation_annual``), independent of the
organization that publishes it. Several sources may feed the same indicator; the
observation keeps the source so competing series stay distinguishable.

Codes follow ``{country_iso2_lower}_{concept}_{qualifier}``. Region-wide or
country-agnostic indicators would drop the prefix.
"""

from __future__ import annotations

from dataclasses import dataclass

from reim.core.constants import (
    Frequency,
    IndicatorCategory,
    SeasonalAdjustment,
    ValueType,
)


@dataclass(frozen=True, slots=True)
class IndicatorDefinition:
    """Static description of a tracked economic concept."""

    code: str
    name: str
    description: str
    category: IndicatorCategory
    frequency: Frequency
    unit: str
    value_type: ValueType
    methodology_url: str
    seasonal_adjustment: SeasonalAdjustment = SeasonalAdjustment.NOT_ADJUSTED
    is_active: bool = True


_WB_METHODOLOGY = "https://datahelpdesk.worldbank.org/knowledgebase/articles/889392"

INDICATORS: tuple[IndicatorDefinition, ...] = (
    IndicatorDefinition(
        code="ni_exchange_rate_official_daily",
        name="Nicaragua — official exchange rate (daily)",
        description=(
            "Official NIO/USD exchange rate published by the Banco Central de "
            "Nicaragua for a specific calendar day."
        ),
        category=IndicatorCategory.EXCHANGE_RATE,
        frequency=Frequency.DAILY,
        unit="NIO per USD",
        value_type=ValueType.RATE,
        methodology_url="https://www.bcn.gob.ni/tipo-de-cambio",
    ),
    IndicatorDefinition(
        code="ni_exchange_rate_official_annual_avg",
        name="Nicaragua — official exchange rate (annual average)",
        description=(
            "Official exchange rate, local currency units per US dollar, "
            "period average. World Bank series PA.NUS.FCRF."
        ),
        category=IndicatorCategory.EXCHANGE_RATE,
        frequency=Frequency.ANNUAL,
        unit="NIO per USD",
        value_type=ValueType.RATE,
        methodology_url=_WB_METHODOLOGY,
    ),
    IndicatorDefinition(
        code="ni_cpi_inflation_annual",
        name="Nicaragua — consumer price inflation (annual)",
        description=(
            "Annual percentage change in the consumer price index. "
            "World Bank series FP.CPI.TOTL.ZG."
        ),
        category=IndicatorCategory.PRICES,
        frequency=Frequency.ANNUAL,
        unit="percent",
        value_type=ValueType.PERCENT_CHANGE,
        methodology_url=_WB_METHODOLOGY,
    ),
    IndicatorDefinition(
        code="ni_cpi_index_monthly",
        name="Nicaragua — consumer price index (monthly, 2006=100)",
        description=(
            "National consumer price index published monthly by INIDE, base "
            "year 2006 = 100. This is the national aggregate; INIDE also "
            "publishes Managua and rest-of-country breakdowns."
        ),
        category=IndicatorCategory.PRICES,
        frequency=Frequency.MONTHLY,
        unit="index (2006=100)",
        value_type=ValueType.INDEX,
        methodology_url="https://www.inide.gob.ni/Home/ipc",
    ),
    IndicatorDefinition(
        code="ni_cpi_inflation_monthly",
        name="Nicaragua — consumer price inflation (month-on-month)",
        description=(
            "Percentage change of the national consumer price index versus the "
            "previous month, as published by INIDE."
        ),
        category=IndicatorCategory.PRICES,
        frequency=Frequency.MONTHLY,
        unit="percent",
        value_type=ValueType.PERCENT_CHANGE,
        methodology_url="https://www.inide.gob.ni/Home/ipc",
    ),
    IndicatorDefinition(
        code="ni_cpi_inflation_yoy",
        name="Nicaragua — consumer price inflation (year-on-year)",
        description=(
            "Percentage change of the national consumer price index versus the "
            "same month of the previous year ('variación interanual'), as "
            "published by INIDE. Monthly counterpart of the annual World Bank "
            "series ni_cpi_inflation_annual."
        ),
        category=IndicatorCategory.PRICES,
        frequency=Frequency.MONTHLY,
        unit="percent",
        value_type=ValueType.PERCENT_CHANGE,
        methodology_url="https://www.inide.gob.ni/Home/ipc",
    ),
    IndicatorDefinition(
        code="ni_remittances_received",
        name="Nicaragua — personal remittances received",
        description=(
            "Personal remittances received, current US dollars. "
            "World Bank series BX.TRF.PWKR.CD.DT."
        ),
        category=IndicatorCategory.EXTERNAL_SECTOR,
        frequency=Frequency.ANNUAL,
        unit="current USD",
        value_type=ValueType.LEVEL,
        methodology_url=_WB_METHODOLOGY,
    ),
    IndicatorDefinition(
        code="ni_international_reserves",
        name="Nicaragua — total international reserves",
        description=(
            "Total reserves including gold, current US dollars. World Bank series FI.RES.TOTL.CD."
        ),
        category=IndicatorCategory.EXTERNAL_SECTOR,
        frequency=Frequency.ANNUAL,
        unit="current USD",
        value_type=ValueType.LEVEL,
        methodology_url=_WB_METHODOLOGY,
    ),
    IndicatorDefinition(
        code="ni_exports_goods_services",
        name="Nicaragua — exports of goods and services",
        description=(
            "Exports of goods and services, current US dollars. World Bank series NE.EXP.GNFS.CD."
        ),
        category=IndicatorCategory.EXTERNAL_SECTOR,
        frequency=Frequency.ANNUAL,
        unit="current USD",
        value_type=ValueType.LEVEL,
        methodology_url=_WB_METHODOLOGY,
    ),
    IndicatorDefinition(
        code="ni_imports_goods_services",
        name="Nicaragua — imports of goods and services",
        description=(
            "Imports of goods and services, current US dollars. World Bank series NE.IMP.GNFS.CD."
        ),
        category=IndicatorCategory.EXTERNAL_SECTOR,
        frequency=Frequency.ANNUAL,
        unit="current USD",
        value_type=ValueType.LEVEL,
        methodology_url=_WB_METHODOLOGY,
    ),
)

INDICATORS_BY_CODE: dict[str, IndicatorDefinition] = {i.code: i for i in INDICATORS}
