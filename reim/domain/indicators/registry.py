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
#: The IMF publishes no per-series methodology page for IMTS; its terms of use
#: are the closest stable reference, and they also state the licence.
_IMF_TERMS = "https://www.imf.org/external/terms.htm"
#: Banguat publishes no separate methodology page; the service description
#: is the closest stable reference.
_BANGUAT_WS = "https://www.banguat.gob.gt/variables/ws/TipoCambio.asmx"
#: SIECA publishes no separate methodology page; the report is its own reference.
_SIECA_REPORT = "https://www.servicios.sieca.int/ReporteGeneralServicios"
#: CEPAL publishes no separate methodology page per indicator; the dashboard
#: for the indicator is the closest stable reference, and it carries the
#: definition, the unit and the source note the API also returns.
_CEPALSTAT_DASHBOARD = "https://statistics.cepal.org/portal/cepalstat/dashboard.html"

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
        code="gt_exchange_rate_official_daily_buy",
        name="Guatemala — official exchange rate, buy (daily)",
        description=(
            "Rate at which the Banco de Guatemala buys US dollars, published "
            "for each calendar day. This is the lower of the published pair; "
            "'compra' is stated from the bank's side, so it is the rate a "
            "seller of dollars receives."
        ),
        category=IndicatorCategory.EXCHANGE_RATE,
        frequency=Frequency.DAILY,
        unit="GTQ per USD",
        value_type=ValueType.RATE,
        methodology_url=_BANGUAT_WS,
    ),
    IndicatorDefinition(
        code="gt_exchange_rate_official_daily_sell",
        name="Guatemala — official exchange rate, sell (daily)",
        description=(
            "Rate at which the Banco de Guatemala sells US dollars, published "
            "for each calendar day. This is the higher of the published pair "
            "from 1992 onward; through the 1990-91 liberalisation the buy rate "
            "sat fixed above it."
        ),
        category=IndicatorCategory.EXCHANGE_RATE,
        frequency=Frequency.DAILY,
        unit="GTQ per USD",
        value_type=ValueType.RATE,
        methodology_url=_BANGUAT_WS,
    ),
    IndicatorDefinition(
        code="ni_cpi_index_monthly",
        name="Nicaragua — consumer price index (monthly, 2006=100)",
        description=(
            "National consumer price index published monthly by INIDE, base "
            "year 2006 = 100. This is the national aggregate; the Managua and "
            "rest-of-country breakdowns are ni_cpi_index_monthly_managua and "
            "ni_cpi_index_monthly_rest_of_country."
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
        code="ni_cpi_index_monthly_managua",
        name="Nicaragua — consumer price index, Managua (monthly, 2006=100)",
        description=(
            "Consumer price index for Managua published monthly by INIDE, base "
            "year 2006 = 100. Published by INIDE in the same table as the "
            "national aggregate; not derived by REIM."
        ),
        category=IndicatorCategory.PRICES,
        frequency=Frequency.MONTHLY,
        unit="index (2006=100)",
        value_type=ValueType.INDEX,
        methodology_url="https://www.inide.gob.ni/Home/ipc",
    ),
    IndicatorDefinition(
        code="ni_cpi_inflation_monthly_managua",
        name="Nicaragua — consumer price inflation, Managua (month-on-month)",
        description=(
            "Percentage change of the Managua consumer price index versus the "
            "previous month, as published by INIDE."
        ),
        category=IndicatorCategory.PRICES,
        frequency=Frequency.MONTHLY,
        unit="percent",
        value_type=ValueType.PERCENT_CHANGE,
        methodology_url="https://www.inide.gob.ni/Home/ipc",
    ),
    IndicatorDefinition(
        code="ni_cpi_inflation_yoy_managua",
        name="Nicaragua — consumer price inflation, Managua (year-on-year)",
        description=(
            "Percentage change of the Managua consumer price index versus the "
            "same month of the previous year, as published by INIDE."
        ),
        category=IndicatorCategory.PRICES,
        frequency=Frequency.MONTHLY,
        unit="percent",
        value_type=ValueType.PERCENT_CHANGE,
        methodology_url="https://www.inide.gob.ni/Home/ipc",
    ),
    IndicatorDefinition(
        code="ni_cpi_index_monthly_rest_of_country",
        name="Nicaragua — consumer price index, rest of the country (monthly, 2006=100)",
        description=(
            "Consumer price index for Nicaragua excluding Managua ('resto del "
            "país'), published monthly by INIDE, base year 2006 = 100. "
            "Published by INIDE in the same table as the national aggregate; "
            "not derived by REIM."
        ),
        category=IndicatorCategory.PRICES,
        frequency=Frequency.MONTHLY,
        unit="index (2006=100)",
        value_type=ValueType.INDEX,
        methodology_url="https://www.inide.gob.ni/Home/ipc",
    ),
    IndicatorDefinition(
        code="ni_cpi_inflation_monthly_rest_of_country",
        name="Nicaragua — consumer price inflation, rest of the country (month-on-month)",
        description=(
            "Percentage change of the rest-of-country consumer price index "
            "versus the previous month, as published by INIDE."
        ),
        category=IndicatorCategory.PRICES,
        frequency=Frequency.MONTHLY,
        unit="percent",
        value_type=ValueType.PERCENT_CHANGE,
        methodology_url="https://www.inide.gob.ni/Home/ipc",
    ),
    IndicatorDefinition(
        code="ni_cpi_inflation_yoy_rest_of_country",
        name="Nicaragua — consumer price inflation, rest of the country (year-on-year)",
        description=(
            "Percentage change of the rest-of-country consumer price index "
            "versus the same month of the previous year, as published by INIDE."
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
    IndicatorDefinition(
        code="exports_goods_monthly",
        name="Merchandise exports FOB (monthly)",
        description=(
            "Exports of goods, free on board, compiled by the IMF from national "
            "customs data (International Merchandise Trade Statistics). Goods "
            "only: this does not replace the annual, broader "
            "ni_exports_goods_services, which also covers services. The "
            "country is carried by the observation, not the code, because "
            "every country shares this methodology."
        ),
        category=IndicatorCategory.EXTERNAL_SECTOR,
        frequency=Frequency.MONTHLY,
        unit="current USD",
        value_type=ValueType.LEVEL,
        methodology_url=_IMF_TERMS,
    ),
    IndicatorDefinition(
        code="imports_goods_monthly",
        name="Merchandise imports CIF (monthly)",
        description=(
            "Imports of goods including cost, insurance and freight, compiled "
            "by the IMF from national customs data. Goods only: this does not "
            "replace the annual, broader ni_imports_goods_services."
        ),
        category=IndicatorCategory.EXTERNAL_SECTOR,
        frequency=Frequency.MONTHLY,
        unit="current USD",
        value_type=ValueType.LEVEL,
        methodology_url=_IMF_TERMS,
    ),
    IndicatorDefinition(
        code="trade_balance_goods_monthly",
        name="Merchandise trade balance (monthly)",
        description=(
            "Merchandise exports FOB minus imports CIF, as published by the "
            "IMF. Negative in the great majority of months for every Central "
            "American country REIM covers."
        ),
        category=IndicatorCategory.EXTERNAL_SECTOR,
        frequency=Frequency.MONTHLY,
        unit="current USD",
        value_type=ValueType.LEVEL,
        methodology_url=_IMF_TERMS,
    ),
    IndicatorDefinition(
        code="exports_services_quarterly",
        name="Exports of services (quarterly)",
        description=(
            "Exports of services to the world, quarterly, from SIECA's regional "
            "compilation. Services only: this does not include merchandise, "
            "which REIM holds monthly from the IMF, and it is not the World "
            "Bank's annual goods-and-services aggregate."
        ),
        category=IndicatorCategory.EXTERNAL_SECTOR,
        frequency=Frequency.QUARTERLY,
        unit="current USD",
        value_type=ValueType.LEVEL,
        methodology_url=_SIECA_REPORT,
    ),
    IndicatorDefinition(
        code="imports_services_quarterly",
        name="Imports of services (quarterly)",
        description=(
            "Imports of services from the world, quarterly, from SIECA's "
            "regional compilation. Services only; see exports_services_quarterly."
        ),
        category=IndicatorCategory.EXTERNAL_SECTOR,
        frequency=Frequency.QUARTERLY,
        unit="current USD",
        value_type=ValueType.LEVEL,
        methodology_url=_SIECA_REPORT,
    ),
    IndicatorDefinition(
        code="trade_balance_services_quarterly",
        name="Services trade balance (quarterly)",
        description=(
            "Exports minus imports of services, quarterly, as published by "
            "SIECA. Taken from the source rather than derived; REIM checks the "
            "identity but does not compute the figure."
        ),
        category=IndicatorCategory.EXTERNAL_SECTOR,
        frequency=Frequency.QUARTERLY,
        unit="current USD",
        value_type=ValueType.LEVEL,
        methodology_url=_SIECA_REPORT,
    ),
    IndicatorDefinition(
        code="gdp_current_usd_annual",
        name="Gross domestic product (annual, current USD)",
        description=(
            "Total annual GDP at current prices in US dollars, from CEPAL's "
            "harmonised national-accounts compilation. These are CEPAL's own "
            "estimates based on national sources, not the figure each national "
            "statistics office publishes: the series is built for "
            "cross-country comparability and need not match any country's "
            "official GDP."
        ),
        category=IndicatorCategory.REAL_SECTOR,
        frequency=Frequency.ANNUAL,
        unit="current USD",
        value_type=ValueType.LEVEL,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=2203&lang=en",
    ),
    IndicatorDefinition(
        code="gdp_constant_usd_annual",
        name="Gross domestic product (annual, constant 2018 USD)",
        description=(
            "Total annual GDP in volume terms, valued at 2018 prices and "
            "converted with CEPAL's base-year reference exchange rate, so "
            "movements reflect output rather than prices or the exchange rate. "
            "CEPAL's own estimates; see gdp_current_usd_annual."
        ),
        category=IndicatorCategory.REAL_SECTOR,
        frequency=Frequency.ANNUAL,
        unit="constant 2018 USD",
        value_type=ValueType.LEVEL,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=2204&lang=en",
    ),
    IndicatorDefinition(
        code="gdp_per_capita_current_usd_annual",
        name="GDP per inhabitant (annual, current USD)",
        description=(
            "Total annual GDP at current prices divided by total population. "
            "The population is CELADE's official estimate and projection, "
            "harmonised across countries, not each country's own census "
            "figure. REIM stores no population series, so this cannot be "
            "derived from the GDP totals it holds."
        ),
        category=IndicatorCategory.REAL_SECTOR,
        frequency=Frequency.ANNUAL,
        unit="current USD per person",
        value_type=ValueType.LEVEL,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=2205&lang=en",
    ),
    IndicatorDefinition(
        code="gdp_per_capita_constant_usd_annual",
        name="GDP per inhabitant (annual, constant 2018 USD)",
        description=(
            "Total annual GDP at 2018 prices divided by CELADE's population "
            "estimate; see gdp_per_capita_current_usd_annual."
        ),
        category=IndicatorCategory.REAL_SECTOR,
        frequency=Frequency.ANNUAL,
        unit="constant 2018 USD per person",
        value_type=ValueType.LEVEL,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=2206&lang=en",
    ),
    IndicatorDefinition(
        code="money_m1_monthly",
        name="Money (M1, end of period)",
        description=(
            "Narrow money at the close of each month: currency held by the "
            "public plus demand deposits, as compiled by CEPAL from central "
            "bank figures. Stored in whole units of each country's own "
            "currency, so values are not comparable across countries without "
            "a conversion REIM does not perform."
        ),
        category=IndicatorCategory.MONETARY,
        frequency=Frequency.MONTHLY,
        unit="units of local currency",
        value_type=ValueType.LEVEL,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=862&lang=en",
    ),
    IndicatorDefinition(
        code="money_m2_monthly",
        name="Liquidity (M2, end of period)",
        description=(
            "M1 plus savings and time deposits in local currency, at the close "
            "of each month. CEPAL's own definition; see money_m1_monthly for "
            "the currency caveat. Belize is not covered by this series."
        ),
        category=IndicatorCategory.MONETARY,
        frequency=Frequency.MONTHLY,
        unit="units of local currency",
        value_type=ValueType.LEVEL,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=868&lang=en",
    ),
    IndicatorDefinition(
        code="money_m3_monthly",
        name="Broad liquidity (M3, end of period)",
        description=(
            "M2 plus foreign-currency deposits, at the close of each month. "
            "CEPAL's own definition; see money_m1_monthly for the currency "
            "caveat. El Salvador is not covered by this series."
        ),
        category=IndicatorCategory.MONETARY,
        frequency=Frequency.MONTHLY,
        unit="units of local currency",
        value_type=ValueType.LEVEL,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=869&lang=en",
    ),
)

INDICATORS_BY_CODE: dict[str, IndicatorDefinition] = {i.code: i for i in INDICATORS}
