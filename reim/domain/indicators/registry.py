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
    #: Whether this indicator's values are amounts denominated in a currency
    #: and may therefore be converted into another one. False for rates,
    #: indices and ratios, which are expressed *per* a currency rather than
    #: *in* it — see the currency-conversion design, decision D5.
    currency_convertible: bool = False
    #: Whether the publisher defines this indicator differently in each
    #: country, so that levels may not be read against each other even when
    #: the unit and the currency match. CEPAL's interest rates declare exactly
    #: this in their own ``calculation_methodology`` field: "According to the
    #: definition from each country." ``/compare`` states it as a note and
    #: still returns the series — see the interest-rates design, decision D6.
    methodology_varies_by_country: bool = False
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
            "currency, so values are not comparable across countries as "
            "published. `/compare?convert_to=USD` returns a converted view "
            "beside the published figures, never in place of them."
        ),
        category=IndicatorCategory.MONETARY,
        frequency=Frequency.MONTHLY,
        unit="units of local currency",
        value_type=ValueType.LEVEL,
        currency_convertible=True,
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
        currency_convertible=True,
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
        currency_convertible=True,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=869&lang=en",
    ),
    IndicatorDefinition(
        code="public_debt_usd_annual",
        name="Central government public debt stock (annual, current USD)",
        description=(
            "Gross public debt stock of the central government at the close of "
            "each year, as compiled by CEPAL. Published in millions of current "
            "dollars and stored in whole dollars. This is the central "
            "government only: CEPAL also publishes wider institutional "
            "coverages, but only this one covers all seven countries."
        ),
        category=IndicatorCategory.FISCAL,
        frequency=Frequency.ANNUAL,
        unit="current USD",
        value_type=ValueType.LEVEL,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=1239&lang=en",
    ),
    IndicatorDefinition(
        code="public_debt_pct_gdp_annual",
        name="Central government public debt stock (annual, percent of GDP)",
        description=(
            "The same debt stock expressed as a share of GDP, stored exactly "
            "as published. CEPAL's denominator is each country's GDP in local "
            "currency converted at the IMF's 31 December rate, which is not "
            "REIM's gdp_current_usd_annual: dividing this series into that one "
            "does not reconcile and is not intended to."
        ),
        category=IndicatorCategory.FISCAL,
        frequency=Frequency.ANNUAL,
        unit="percent of GDP",
        value_type=ValueType.PERCENT,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=1240&lang=en",
    ),
    IndicatorDefinition(
        code="exchange_rate_nominal_monthly",
        name="Nominal exchange rate (monthly average)",
        description=(
            "Units of each country's own currency per US dollar, published by "
            "ECLAC as the average of the daily rates within the month. Being "
            "a within-period average, it does not line up exactly with a "
            "figure measured at the close of the month. The payload names "
            "Bloomberg as the underlying source while its sources array claims "
            "official figures; REIM stores the series without repeating the "
            "second claim. El Salvador is quoted in colones at its fixed "
            "conversion rate throughout, twenty-four years after it adopted "
            "the dollar, so this series carries a rate for a currency no "
            "longer in circulation."
        ),
        category=IndicatorCategory.EXCHANGE_RATE,
        frequency=Frequency.MONTHLY,
        unit="units of local currency per USD",
        value_type=ValueType.RATE,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=2179&lang=en",
    ),
    IndicatorDefinition(
        code="cpi_index_monthly",
        name="Consumer price index (monthly)",
        description=(
            "Monthly consumer price index for the seven Central American "
            "countries, compiled by ECLAC from each country's own national "
            "publisher. Every country is on its own base period and CEPAL's "
            "declared base years do not hold for three of the five it "
            "declares, so REIM states none: levels are not comparable across "
            "countries, only their movements. Guatemala's series is spliced "
            "at 2010-01 without normalisation — December 2009 reads 94.882 "
            "and January 2010 reads 54.48 — so inflation computed across that "
            "month is meaningless. Nicaragua also has ni_cpi_index_monthly "
            "from INIDE, which differs from this series by about 4% in level."
        ),
        category=IndicatorCategory.PRICES,
        frequency=Frequency.MONTHLY,
        unit="index",
        value_type=ValueType.INDEX,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=365&lang=en",
    ),
    IndicatorDefinition(
        code="lending_rate_nominal_monthly",
        name="Nominal lending rate (monthly)",
        description=(
            "Monthly nominal lending rate for the seven Central American "
            "countries, compiled by ECLAC from each country's own central "
            "bank. CEPAL defines the rate differently in each country: a "
            "weighted average in local currency for Costa Rica, Guatemala and "
            "Honduras; the basic lending rate for up to one year in El "
            "Salvador; a weighted average of short-term rates in Nicaragua; "
            "the rate on one-year trade credit in Panama; and a weighted "
            "average over personal, business, residential and other "
            "construction loans in Belize. Levels are therefore not "
            "comparable across countries, only their movements."
        ),
        category=IndicatorCategory.FINANCIAL,
        frequency=Frequency.MONTHLY,
        unit="percent per annum",
        value_type=ValueType.PERCENT,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=856&lang=en",
        methodology_varies_by_country=True,
    ),
    IndicatorDefinition(
        code="deposit_rate_nominal_monthly",
        name="Nominal deposit rate (monthly)",
        description=(
            "Monthly nominal deposit rate for the seven Central American "
            "countries, compiled by ECLAC from each country's own central "
            "bank. CEPAL defines the rate differently in each country: the "
            "average local-currency deposit rate in Costa Rica, a 180-day "
            "saving rate in El Salvador, a weighted average of term deposit "
            "rates in Honduras, 30-day local-currency passive rates in "
            "Nicaragua, six-month deposits in Panama, and a weighted average "
            "in Belize. Levels are therefore not comparable across countries, "
            "only their movements. CEPAL's own definition text calls "
            "Guatemala's series a lending rate; the data is a deposit rate, "
            "below lending_rate_nominal_monthly in all 357 shared months."
        ),
        category=IndicatorCategory.FINANCIAL,
        frequency=Frequency.MONTHLY,
        unit="percent per annum",
        value_type=ValueType.PERCENT,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=857&lang=en",
        methodology_varies_by_country=True,
    ),
    IndicatorDefinition(
        code="policy_rate_monthly",
        name="Monetary policy rate (monthly)",
        description=(
            "Monthly monetary policy rate for six Central American countries, "
            "compiled by ECLAC. CEPAL defines the rate differently in each: "
            "the yield on 180-day central bank bonds in Nicaragua, a "
            "stock-exchange repo yield over 1-7 days in El Salvador, the rate "
            "on local-currency central bank operations in Costa Rica, and the "
            "Central Bank's own lending rate in Belize. Levels are therefore "
            "not comparable across countries, only their movements. Panama is "
            "absent: it is dollarised and has no central bank, and CEPAL's "
            "twelve monthly zero-valued, unattributed 2022 cells for it are an "
            "artifact REIM does not store."
        ),
        category=IndicatorCategory.FINANCIAL,
        frequency=Frequency.MONTHLY,
        unit="percent per annum",
        value_type=ValueType.PERCENT,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=1206&lang=en",
        methodology_varies_by_country=True,
    ),
    IndicatorDefinition(
        code="bop_current_account_quarterly",
        name="Current account balance (quarterly)",
        description=(
            "Quarterly balance of payments compiled by ECLAC; CEPAL declares the IMF's "
            "fifth Balance of Payments Manual while six of the seven countries carry a "
            "footnote citing the sixth. The current account: the sum of "
            "bop_balance_goods_services_quarterly, bop_balance_income_quarterly and "
            "bop_balance_current_transfers_quarterly, which foots exactly against this "
            "figure across all seven countries."
        ),
        category=IndicatorCategory.EXTERNAL_SECTOR,
        frequency=Frequency.QUARTERLY,
        unit="current USD",
        value_type=ValueType.LEVEL,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=547&lang=en",
    ),
    IndicatorDefinition(
        code="bop_capital_account_quarterly",
        name="Capital account balance (quarterly)",
        description=(
            "Quarterly balance of payments compiled by ECLAC; CEPAL declares the IMF's "
            "fifth Balance of Payments Manual while six of the seven countries carry a "
            "footnote citing the sixth. Capital transfers and the acquisition or "
            "disposal of non-produced, non-financial assets. With the current and "
            "financial accounts and errors and omissions it sums to "
            "bop_global_balance_quarterly in 782 of the 784 country-quarters measured; "
            "Panama's 2004-Q3 and 2021-Q4 are the two exceptions."
        ),
        category=IndicatorCategory.EXTERNAL_SECTOR,
        frequency=Frequency.QUARTERLY,
        unit="current USD",
        value_type=ValueType.LEVEL,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=547&lang=en",
    ),
    IndicatorDefinition(
        code="bop_financial_account_quarterly",
        name="Financial account balance (quarterly)",
        description=(
            "Quarterly balance of payments compiled by ECLAC; CEPAL declares the IMF's "
            "fifth Balance of Payments Manual while six of the seven countries carry a "
            "footnote citing the sixth. Net balance across direct, portfolio and other "
            "investment — see bop_direct_investment_abroad_quarterly, "
            "bop_direct_investment_inward_quarterly, "
            "bop_portfolio_investment_assets_quarterly, "
            "bop_portfolio_investment_liabilities_quarterly, "
            "bop_other_investment_assets_quarterly and "
            "bop_other_investment_liabilities_quarterly for the sub-accounts. Reserve "
            "assets are excluded from this balance; see bop_reserve_assets_quarterly."
        ),
        category=IndicatorCategory.EXTERNAL_SECTOR,
        frequency=Frequency.QUARTERLY,
        unit="current USD",
        value_type=ValueType.LEVEL,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=547&lang=en",
    ),
    IndicatorDefinition(
        code="bop_errors_omissions_quarterly",
        name="Errors and omissions (quarterly)",
        description=(
            "Quarterly balance of payments compiled by ECLAC; CEPAL declares the IMF's "
            "fifth Balance of Payments Manual while six of the seven countries carry a "
            "footnote citing the sixth. The balancing residual between the recorded "
            "current, capital and financial accounts and the recorded change in "
            "reserves; not a measured flow in its own right, and its size is a rough "
            "gauge of how well the other lines were measured that quarter."
        ),
        category=IndicatorCategory.EXTERNAL_SECTOR,
        frequency=Frequency.QUARTERLY,
        unit="current USD",
        value_type=ValueType.LEVEL,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=547&lang=en",
    ),
    IndicatorDefinition(
        code="bop_global_balance_quarterly",
        name="Global balance (quarterly)",
        description=(
            "Quarterly balance of payments compiled by ECLAC; CEPAL declares the IMF's "
            "fifth Balance of Payments Manual while six of the seven countries carry a "
            "footnote citing the sixth. Sum of the current, capital and financial "
            "accounts plus errors and omissions. Holds exactly for 782 of the 784 "
            "country-quarters measured; Panama's 2004-Q3 and 2021-Q4 break it. It is "
            "not the negative of bop_reserves_related_quarterly, as a textbook two-line "
            "presentation would suggest: that identity held in only 2 of the 784 "
            "country-quarters measured, so the two are not read as offsetting each "
            "other here."
        ),
        category=IndicatorCategory.EXTERNAL_SECTOR,
        frequency=Frequency.QUARTERLY,
        unit="current USD",
        value_type=ValueType.LEVEL,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=547&lang=en",
    ),
    IndicatorDefinition(
        code="bop_reserves_related_quarterly",
        name="Reserves and related items (quarterly)",
        description=(
            "Quarterly balance of payments compiled by ECLAC; CEPAL declares the IMF's "
            "fifth Balance of Payments Manual while six of the seven countries carry a "
            "footnote citing the sixth. The financing counterpart to the global "
            "balance: reserve assets (bop_reserve_assets_quarterly) plus use of IMF "
            "credit and loans and exceptional financing. It does not sum to zero "
            "against bop_global_balance_quarterly in this data; see that indicator's "
            "description."
        ),
        category=IndicatorCategory.EXTERNAL_SECTOR,
        frequency=Frequency.QUARTERLY,
        unit="current USD",
        value_type=ValueType.LEVEL,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=547&lang=en",
    ),
    IndicatorDefinition(
        code="bop_balance_goods_quarterly",
        name="Balance on goods (quarterly)",
        description=(
            "Quarterly balance of payments compiled by ECLAC; CEPAL declares the IMF's "
            "fifth Balance of Payments Manual while six of the seven countries carry a "
            "footnote citing the sixth. The merchandise trade balance: the sum of "
            "bop_exports_goods_fob_quarterly and bop_imports_goods_fob_quarterly, which "
            "foots exactly against this figure across all seven countries because "
            "imports are stored with a negative sign."
        ),
        category=IndicatorCategory.EXTERNAL_SECTOR,
        frequency=Frequency.QUARTERLY,
        unit="current USD",
        value_type=ValueType.LEVEL,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=547&lang=en",
    ),
    IndicatorDefinition(
        code="bop_balance_goods_services_quarterly",
        name="Balance on goods and services (quarterly)",
        description=(
            "Quarterly balance of payments compiled by ECLAC; CEPAL declares the IMF's "
            "fifth Balance of Payments Manual while six of the seven countries carry a "
            "footnote citing the sixth. The sum of bop_balance_goods_quarterly, "
            "bop_services_credit_quarterly and bop_services_debit_quarterly, which "
            "foots exactly against this figure across all seven countries. REIM's other "
            "quarterly services series, exports_services_quarterly and "
            "imports_services_quarterly, come from SIECA rather than this ECLAC "
            "compilation and are not interchangeable with the two above."
        ),
        category=IndicatorCategory.EXTERNAL_SECTOR,
        frequency=Frequency.QUARTERLY,
        unit="current USD",
        value_type=ValueType.LEVEL,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=547&lang=en",
    ),
    IndicatorDefinition(
        code="bop_balance_income_quarterly",
        name="Balance on income (quarterly)",
        description=(
            "Quarterly balance of payments compiled by ECLAC; CEPAL declares the IMF's "
            "fifth Balance of Payments Manual while six of the seven countries carry a "
            "footnote citing the sixth. Balance on primary income: the sum of "
            "bop_income_credit_quarterly and bop_income_debit_quarterly."
        ),
        category=IndicatorCategory.EXTERNAL_SECTOR,
        frequency=Frequency.QUARTERLY,
        unit="current USD",
        value_type=ValueType.LEVEL,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=547&lang=en",
    ),
    IndicatorDefinition(
        code="bop_balance_current_transfers_quarterly",
        name="Balance on current transfers (quarterly)",
        description=(
            "Quarterly balance of payments compiled by ECLAC; CEPAL declares the IMF's "
            "fifth Balance of Payments Manual while six of the seven countries carry a "
            "footnote citing the sixth. The sum of "
            "bop_current_transfers_credit_quarterly and "
            "bop_current_transfers_debit_quarterly. Like both of its components, this "
            "is the whole current-transfers account, official transfers included, and "
            "is not remittances — see bop_current_transfers_credit_quarterly."
        ),
        category=IndicatorCategory.EXTERNAL_SECTOR,
        frequency=Frequency.QUARTERLY,
        unit="current USD",
        value_type=ValueType.LEVEL,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=547&lang=en",
    ),
    IndicatorDefinition(
        code="bop_exports_goods_fob_quarterly",
        name="Exports of goods, f.o.b. (quarterly, balance of payments)",
        description=(
            "Quarterly balance of payments compiled by ECLAC; CEPAL declares the IMF's "
            "fifth Balance of Payments Manual while six of the seven countries carry a "
            "footnote citing the sixth. Exports of goods, free on board. REIM already "
            "holds exports_goods_monthly, the IMF's monthly merchandise-exports series "
            "compiled from national customs data on the same free-on-board basis; the "
            "two overlap and REIM stores both without choosing between them, the same "
            "rule it applies to Nicaragua's two consumer price indices."
        ),
        category=IndicatorCategory.EXTERNAL_SECTOR,
        frequency=Frequency.QUARTERLY,
        unit="current USD",
        value_type=ValueType.LEVEL,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=547&lang=en",
    ),
    IndicatorDefinition(
        code="bop_imports_goods_fob_quarterly",
        name="Imports of goods, f.o.b. (quarterly, balance of payments)",
        description=(
            "Quarterly balance of payments compiled by ECLAC; CEPAL declares the IMF's "
            "fifth Balance of Payments Manual while six of the seven countries carry a "
            "footnote citing the sixth. Imports of goods, free on board, stored with a "
            "negative sign — bop_balance_goods_quarterly foots exactly as exports plus "
            "imports only because of that sign. REIM already holds "
            "imports_goods_monthly, the IMF's monthly merchandise-imports series "
            "compiled from national customs data, but that series is c.i.f. — cost, "
            "insurance and freight included — not f.o.b., so the two are not the same "
            "valuation basis and do not overlap the way the export pair does."
        ),
        category=IndicatorCategory.EXTERNAL_SECTOR,
        frequency=Frequency.QUARTERLY,
        unit="current USD",
        value_type=ValueType.LEVEL,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=547&lang=en",
    ),
    IndicatorDefinition(
        code="bop_services_credit_quarterly",
        name="Services, credit (quarterly)",
        description=(
            "Quarterly balance of payments compiled by ECLAC; CEPAL declares the IMF's "
            "fifth Balance of Payments Manual while six of the seven countries carry a "
            "footnote citing the sixth. Exports of services — the credit side of the "
            "services account. Sums with bop_services_debit_quarterly and "
            "bop_balance_goods_quarterly into bop_balance_goods_services_quarterly."
        ),
        category=IndicatorCategory.EXTERNAL_SECTOR,
        frequency=Frequency.QUARTERLY,
        unit="current USD",
        value_type=ValueType.LEVEL,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=547&lang=en",
    ),
    IndicatorDefinition(
        code="bop_services_debit_quarterly",
        name="Services, debit (quarterly)",
        description=(
            "Quarterly balance of payments compiled by ECLAC; CEPAL declares the IMF's "
            "fifth Balance of Payments Manual while six of the seven countries carry a "
            "footnote citing the sixth. Imports of services — the debit side of the "
            "services account, stored with a negative sign; see "
            "bop_services_credit_quarterly."
        ),
        category=IndicatorCategory.EXTERNAL_SECTOR,
        frequency=Frequency.QUARTERLY,
        unit="current USD",
        value_type=ValueType.LEVEL,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=547&lang=en",
    ),
    IndicatorDefinition(
        code="bop_income_credit_quarterly",
        name="Income, credit (quarterly)",
        description=(
            "Quarterly balance of payments compiled by ECLAC; CEPAL declares the IMF's "
            "fifth Balance of Payments Manual while six of the seven countries carry a "
            "footnote citing the sixth. Primary income received: compensation of "
            "employees and investment income earned abroad. Sums with "
            "bop_income_debit_quarterly into bop_balance_income_quarterly."
        ),
        category=IndicatorCategory.EXTERNAL_SECTOR,
        frequency=Frequency.QUARTERLY,
        unit="current USD",
        value_type=ValueType.LEVEL,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=547&lang=en",
    ),
    IndicatorDefinition(
        code="bop_income_debit_quarterly",
        name="Income, debit (quarterly)",
        description=(
            "Quarterly balance of payments compiled by ECLAC; CEPAL declares the IMF's "
            "fifth Balance of Payments Manual while six of the seven countries carry a "
            "footnote citing the sixth. Primary income paid: compensation of employees "
            "and investment income paid abroad, stored with a negative sign; see "
            "bop_income_credit_quarterly."
        ),
        category=IndicatorCategory.EXTERNAL_SECTOR,
        frequency=Frequency.QUARTERLY,
        unit="current USD",
        value_type=ValueType.LEVEL,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=547&lang=en",
    ),
    IndicatorDefinition(
        code="bop_current_transfers_credit_quarterly",
        name="Current transfers, credit (quarterly)",
        description=(
            "Quarterly balance of payments compiled by ECLAC; CEPAL declares the IMF's "
            "fifth Balance of Payments Manual while six of the seven countries carry a "
            "footnote citing the sixth. This is the whole current-transfers account, "
            "official transfers included; it is not remittances, and CEPAL's item "
            "dimension does not break personal remittances out of it. The World Bank "
            "series REIM stores annually, BX.TRF.PWKR.CD.DT, is a third definition "
            "again — personal transfers plus compensation of employees, not this "
            "account's credit side."
        ),
        category=IndicatorCategory.EXTERNAL_SECTOR,
        frequency=Frequency.QUARTERLY,
        unit="current USD",
        value_type=ValueType.LEVEL,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=547&lang=en",
    ),
    IndicatorDefinition(
        code="bop_current_transfers_debit_quarterly",
        name="Current transfers, debit (quarterly)",
        description=(
            "Quarterly balance of payments compiled by ECLAC; CEPAL declares the IMF's "
            "fifth Balance of Payments Manual while six of the seven countries carry a "
            "footnote citing the sixth. The debit side of the same whole "
            "current-transfers account described in "
            "bop_current_transfers_credit_quarterly, stored with a negative sign: "
            "outward transfers, official ones included, not remittances paid."
        ),
        category=IndicatorCategory.EXTERNAL_SECTOR,
        frequency=Frequency.QUARTERLY,
        unit="current USD",
        value_type=ValueType.LEVEL,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=547&lang=en",
    ),
    IndicatorDefinition(
        code="bop_direct_investment_abroad_quarterly",
        name="Direct investment abroad (quarterly)",
        description=(
            "Quarterly balance of payments compiled by ECLAC; CEPAL declares the IMF's "
            "fifth Balance of Payments Manual while six of the seven countries carry a "
            "footnote citing the sixth. Net direct investment by residents abroad — "
            "the assets side of the direct-investment account, paired with "
            "bop_direct_investment_inward_quarterly."
        ),
        category=IndicatorCategory.EXTERNAL_SECTOR,
        frequency=Frequency.QUARTERLY,
        unit="current USD",
        value_type=ValueType.LEVEL,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=547&lang=en",
    ),
    IndicatorDefinition(
        code="bop_direct_investment_inward_quarterly",
        name="Direct investment in the reporting economy (quarterly)",
        description=(
            "Quarterly balance of payments compiled by ECLAC; CEPAL declares the IMF's "
            "fifth Balance of Payments Manual while six of the seven countries carry a "
            "footnote citing the sixth. Net direct investment by non-residents in the "
            "reporting economy — the liabilities side of the direct-investment "
            "account, paired with bop_direct_investment_abroad_quarterly."
        ),
        category=IndicatorCategory.EXTERNAL_SECTOR,
        frequency=Frequency.QUARTERLY,
        unit="current USD",
        value_type=ValueType.LEVEL,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=547&lang=en",
    ),
    IndicatorDefinition(
        code="bop_portfolio_investment_assets_quarterly",
        name="Portfolio investment, assets (quarterly)",
        description=(
            "Quarterly balance of payments compiled by ECLAC; CEPAL declares the IMF's "
            "fifth Balance of Payments Manual while six of the seven countries carry a "
            "footnote citing the sixth. Net acquisition of portfolio-investment assets "
            "by residents abroad: equity and debt securities held, not issued, by the "
            "reporting economy. Paired with "
            "bop_portfolio_investment_liabilities_quarterly."
        ),
        category=IndicatorCategory.EXTERNAL_SECTOR,
        frequency=Frequency.QUARTERLY,
        unit="current USD",
        value_type=ValueType.LEVEL,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=547&lang=en",
    ),
    IndicatorDefinition(
        code="bop_portfolio_investment_liabilities_quarterly",
        name="Portfolio investment, liabilities (quarterly)",
        description=(
            "Quarterly balance of payments compiled by ECLAC; CEPAL declares the IMF's "
            "fifth Balance of Payments Manual while six of the seven countries carry a "
            "footnote citing the sixth. Net incurrence of portfolio-investment "
            "liabilities: equity and debt securities issued by residents and held "
            "abroad. Paired with bop_portfolio_investment_assets_quarterly."
        ),
        category=IndicatorCategory.EXTERNAL_SECTOR,
        frequency=Frequency.QUARTERLY,
        unit="current USD",
        value_type=ValueType.LEVEL,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=547&lang=en",
    ),
    IndicatorDefinition(
        code="bop_other_investment_assets_quarterly",
        name="Other investment, assets (quarterly)",
        description=(
            "Quarterly balance of payments compiled by ECLAC; CEPAL declares the IMF's "
            "fifth Balance of Payments Manual while six of the seven countries carry a "
            "footnote citing the sixth. Net other-investment assets: loans, currency "
            "and deposits, trade credit and similar claims on non-residents not "
            "classified as direct or portfolio investment. Paired with "
            "bop_other_investment_liabilities_quarterly."
        ),
        category=IndicatorCategory.EXTERNAL_SECTOR,
        frequency=Frequency.QUARTERLY,
        unit="current USD",
        value_type=ValueType.LEVEL,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=547&lang=en",
    ),
    IndicatorDefinition(
        code="bop_other_investment_liabilities_quarterly",
        name="Other investment, liabilities (quarterly)",
        description=(
            "Quarterly balance of payments compiled by ECLAC; CEPAL declares the IMF's "
            "fifth Balance of Payments Manual while six of the seven countries carry a "
            "footnote citing the sixth. Net other-investment liabilities: loans, "
            "currency and deposits, trade credit and similar obligations to "
            "non-residents not classified as direct or portfolio investment. Paired "
            "with bop_other_investment_assets_quarterly."
        ),
        category=IndicatorCategory.EXTERNAL_SECTOR,
        frequency=Frequency.QUARTERLY,
        unit="current USD",
        value_type=ValueType.LEVEL,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=547&lang=en",
    ),
    IndicatorDefinition(
        code="bop_reserve_assets_quarterly",
        name="Reserve assets, balance-of-payments flow (quarterly)",
        description=(
            "Quarterly balance of payments compiled by ECLAC; CEPAL declares the IMF's "
            "fifth Balance of Payments Manual while six of the seven countries carry a "
            "footnote citing the sixth. This is the balance-of-payments flow in "
            "reserve assets over the quarter — the change in reserves, not the stock. "
            "It is not the reserves level ROADMAP.md asks for, which is what "
            "FI.RES.TOTL.CD and the IMF's IRFCL hold."
        ),
        category=IndicatorCategory.EXTERNAL_SECTOR,
        frequency=Frequency.QUARTERLY,
        unit="current USD",
        value_type=ValueType.LEVEL,
        methodology_url=f"{_CEPALSTAT_DASHBOARD}?indicator_id=547&lang=en",
    ),
    IndicatorDefinition(
        code="pa_automobiles_per_1000_provincial_annual",
        name="Panama — automobiles in circulation per 1,000 inhabitants, by province",
        description=(
            "Registered automobiles per 1,000 inhabitants, by province and nationally, from "
            "INEC's Panamá en Cifras Digital. Sourced from municipal treasury plate-sale records."
        ),
        category=IndicatorCategory.REAL_SECTOR,
        frequency=Frequency.ANNUAL,
        unit="automóviles",
        value_type=ValueType.RATIO,
        methodology_url="https://www.inec.gob.pa",
    ),
    IndicatorDefinition(
        code="pa_residential_buildings_count_provincial_annual",
        name="Panama — count of residential buildings, by province",
        description=(
            "Count of residential building permits/constructions, by province and nationally, "
            "from INEC's Panamá en Cifras Digital."
        ),
        category=IndicatorCategory.REAL_SECTOR,
        frequency=Frequency.ANNUAL,
        unit="unidades",
        value_type=ValueType.LEVEL,
        methodology_url="https://www.inec.gob.pa",
    ),
    IndicatorDefinition(
        code="pa_nonresidential_buildings_count_provincial_annual",
        name="Panama — count of non-residential buildings, by province",
        description=(
            "Count of non-residential building permits/constructions, by province and "
            "nationally, from INEC's Panamá en Cifras Digital."
        ),
        category=IndicatorCategory.REAL_SECTOR,
        frequency=Frequency.ANNUAL,
        unit="unidades",
        value_type=ValueType.LEVEL,
        methodology_url="https://www.inec.gob.pa",
    ),
)

INDICATORS_BY_CODE: dict[str, IndicatorDefinition] = {i.code: i for i in INDICATORS}
