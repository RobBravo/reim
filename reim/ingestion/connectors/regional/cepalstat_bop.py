"""Central America — the quarterly balance of payments published through CEPALSTAT.

The API, its lack of documentation and the way its routes were recovered are
documented in ``cepalstat.py``, which this connector's base class comes from;
only what differs is recorded here.

**One request, and no Spanish fetch.** Like the consumer price index and
unlike the interest rates and the monetary aggregates, this indicator's item
names are real translations in ``lang=en``, so no second request in Spanish is
needed to read a member table.

**CEPAL declares the fifth Balance of Payments Manual; six of the seven
countries contradict it.** ``metadata.calculation_methodology`` states the
data is "disaggregated according to the analytical components of the fifth
edition of the Balance of Payments Manual published by the IMF in 1993", yet
footnote 10138 — "Analytical presentation based on the official figures of
the countries according to the 6th version of the IMF Balance of Payments
Manual" — is attached to every row for Belize, Costa Rica, Honduras,
Nicaragua, Panama and El Salvador; only Guatemala carries no such footnote.
Checked against IMF documentation, BPM5 and BPM6 do not disagree on any of
the 25 stored items' definitions closely enough to matter here, so no
``methodology_varies_by_country`` flag is declared: doing so for a
contradiction that does not change what a number means would manufacture a
warning nobody could act on. The footnote is still stored, in
``cepalstat_notes_ids``, for whoever wants to check that judgment.

**The response is 20.3 MB with no server-side filtering** — every one of 145
countries, all 201 years and all 66 items in one matrix, the largest single
response read by any CEPALSTAT connector so far. There is no window to
request narrower and no pagination to walk; the whole cube arrives every run
and is filtered client-side, as with every other family this base class
serves.

**41 of the 66 item members are discarded.** The dimension mixes headline
balances with alternate analytical presentations — "Net capital inflows",
"Effect of terms of trade of goods and services", six-way splits of other
investment by sector — that are recombinations of the 25 stored items rather
than additional primary data. Only the six headline balances (current,
capital, financial, errors and omissions, global, reserves and related
items), four sub-balances (goods; goods and services; income; current
transfers) and fifteen components (exports and imports of goods; the four
credit/debit splits of services, income and current transfers; the six
components of the financial account; reserve assets) are kept.

Values are published in millions of dollars and stored in whole dollars,
matching the debt and GDP totals so every dollar figure in the database means
the same thing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from reim.core.constants import Frequency
from reim.core.exceptions import TransformationError
from reim.domain.observations.periods import parse_period
from reim.domain.pipelines.models import NormalizedObservation, QualityResult, RawDataset
from reim.ingestion.connectors.regional.cepalstat import (
    YEARS_DIMENSION,
    CepalstatConnector,
)
from reim.ingestion.http import ensure_ok, fetch, http_client

CEPAL_ID = 547

#: This family's own dimensions; country and years come from the base module.
QUARTERS_DIMENSION = 510
ITEM_DIMENSION = 1272

#: Quarter member ids are contiguous and in calendar order, unlike the
#: monthly families' period dimension.
QUARTERS: dict[int, int] = {511: 1, 512: 2, 513: 3, 514: 4}

#: Published in millions of dollars, stored in whole dollars, matching the debt
#: and GDP totals so every dollar figure in the database means the same thing.
MILLIONS = Decimal("1000000")

CENTRAL_AMERICA = frozenset({"NIC", "GTM", "SLV", "HND", "CRI", "PAN", "BLZ"})

#: The 25 item members REIM stores, of 66. Selected by id and asserted by name
#: in ``_assert_selected_items``: filtering by id is silent when CEPAL relabels
#: a member, and the series would change meaning under an unchanged code.
ITEMS: dict[int, str] = {
    1274: "bop_current_account_quarterly",
    1275: "bop_capital_account_quarterly",
    1276: "bop_financial_account_quarterly",
    1273: "bop_errors_omissions_quarterly",
    1277: "bop_global_balance_quarterly",
    1278: "bop_reserves_related_quarterly",
    1282: "bop_balance_goods_quarterly",
    1286: "bop_balance_goods_services_quarterly",
    1290: "bop_balance_income_quarterly",
    1285: "bop_balance_current_transfers_quarterly",
    1279: "bop_exports_goods_fob_quarterly",
    1281: "bop_imports_goods_fob_quarterly",
    1291: "bop_services_credit_quarterly",
    1284: "bop_services_debit_quarterly",
    1287: "bop_income_credit_quarterly",
    1289: "bop_income_debit_quarterly",
    1280: "bop_current_transfers_credit_quarterly",
    1283: "bop_current_transfers_debit_quarterly",
    1308: "bop_direct_investment_abroad_quarterly",
    1309: "bop_direct_investment_inward_quarterly",
    1310: "bop_portfolio_investment_assets_quarterly",
    1311: "bop_portfolio_investment_liabilities_quarterly",
    1312: "bop_other_investment_assets_quarterly",
    1313: "bop_other_investment_liabilities_quarterly",
    1326: "bop_reserve_assets_quarterly",
}

#: The published name each stored id must still carry. Read back on every run.
ITEM_NAMES: dict[int, str] = {
    1274: "I.  BALANCE ON CURRENT ACCOUNT",
    1275: "II.  BALANCE ON CAPITAL ACCOUNT",
    1276: "III.  BALANCE ON FINANCIAL ACCOUNT",
    1273: "IV.  ERRORS AND OMISSIONS",
    1277: "V.  GLOBAL BALANCE",
    1278: "VI.  RESERVES AND RELATED ITEMS",
    1282: "Balance on goods",
    1286: "Balance on goods and services",
    1290: "Balance on income",
    1285: "Balance on current transfers",
    1279: "Exports of goods, f.o.b.",
    1281: "Imports of goods, f.o.b.",
    1291: "Services (credit)",
    1284: "Services (debit)",
    1287: "Income (credit)",
    1289: "Income (debit)",
    1280: "Current transfers (credit)",
    1283: "Current transfers (debit)",
    1308: "Direct investment abroad",
    1309: "Direct investment in reporting economy",
    1310: "Portfolio investment assets",
    1311: "Portfolio investment liabilities",
    1312: "Other investment assets",
    1313: "Other investment liabilities",
    1326: "Reserve assets",
}


class CepalstatBopConnector(CepalstatConnector):
    """Quarterly balance of payments for the seven Central American countries."""

    connector_key = "cepalstat_bop_quarterly"
    version = "1.0.0"
    expected_frequency = Frequency.QUARTERLY

    async def extract(self) -> RawDataset:
        """Fetch the whole matrix in English. One request.

        No Spanish request: this family's English item names are real
        translations, unlike the monetary family's.

        Raises:
            ExtractionError: The API was unreachable, answered with something
                other than JSON, reported ``success: false`` in its envelope,
                or returned an empty data array.
        """
        base = str(self.source.base_url).rstrip("/")
        retrieved_at = datetime.now(UTC)

        async with http_client() as client:
            url = f"{base}/indicator/{CEPAL_ID}/data"
            response = await fetch(client, url, params={"lang": "en"})
            ensure_ok(response, expected_content_type="json")
            self._ensure_envelope_ok(response.text, CEPAL_ID, url)

        return RawDataset(
            source_key=self.source.key,
            retrieved_at=retrieved_at,
            source_url=base,
            payload={"data": response.text},
            content_type=response.headers.get("content-type"),
            http_status=response.status_code,
            metadata={"indicator_id": CEPAL_ID, "lang": "en"},
        )

    def transform(self, raw: RawDataset) -> list[NormalizedObservation]:
        """Filter the 145-country, 66-item matrix down to 25 series for seven.

        Pure function of ``raw``. Values are stored exactly as published, then
        scaled by ``MILLIONS`` with no rounding: CEPAL declares zero decimals
        and publishes up to 22.

        Raises:
            TransformationError: The payload is not the expected mapping, a
                dimension is missing, a selected item has been renamed, or a
                row names a quarter or year member that does not exist.
        """
        payload = raw.payload
        if not isinstance(payload, dict) or "data" not in payload:
            msg = "CEPALSTAT payload must carry a 'data' mapping"
            raise TransformationError(msg, source_key=self.source.key)

        body = self._decode(str(payload["data"]), CEPAL_ID)["body"]
        self._assert_selected_items(body)
        years = self._members_of(body, YEARS_DIMENSION, "years", CEPAL_ID)
        published_unit = str(body["metadata"]["unit"])
        sources = {source["id"]: source["organization_name"] for source in body["sources"]}

        observations: list[NormalizedObservation] = []
        for row in body["data"]:
            iso3 = row.get("iso3")
            if iso3 not in CENTRAL_AMERICA:
                continue
            item_id = row.get(f"dim_{ITEM_DIMENSION}")
            indicator_code = ITEMS.get(item_id)
            if indicator_code is None:
                continue
            quarter = self._quarter_of(row)
            year = self._label_of(row, years, YEARS_DIMENSION, "year", CEPAL_ID)
            label = f"{year}-Q{quarter}"
            value = self._value_of(row, CEPAL_ID)
            notes_ids = [part for part in str(row.get("notes_ids") or "").split(",") if part]
            observations.append(
                NormalizedObservation(
                    country_iso3=str(iso3),
                    indicator_code=indicator_code,
                    source_key=self.source.key,
                    period=parse_period(label, Frequency.QUARTERLY),
                    unit="current USD",
                    currency_code="USD",
                    value_numeric=value * MILLIONS,
                    retrieved_at=raw.retrieved_at,
                    source_url=f"{raw.source_url}/indicator/{CEPAL_ID}/data",
                    source_record_id=f"cepalstat:{CEPAL_ID}:{iso3}:{item_id}:{label}",
                    raw_metadata={
                        "cepalstat_indicator_id": CEPAL_ID,
                        "cepalstat_item_id": item_id,
                        "cepalstat_published_value": format(value.normalize(), "f"),
                        "cepalstat_published_unit": published_unit,
                        "cepalstat_scale_applied": "1e6",
                        "cepalstat_source": sources.get(row.get("source_id"), ""),
                        "cepalstat_notes_ids": notes_ids,
                        "contract_status": "verified",
                    },
                )
            )
        observations.sort(key=lambda obs: (obs.indicator_code, obs.country_iso3, obs.period.start))
        return observations

    def validate(self, observations: list[NormalizedObservation]) -> list[QualityResult]:
        """No-op: ``BaseConnector.validate`` is abstract with no default.

        This override only makes the class instantiable. Task 5 replaces it
        with the real CEPALSTAT-specific checks.
        """
        return []

    def _quarter_of(self, row: Any) -> int:
        """Resolve a row's quarter number.

        Raises:
            TransformationError: The row names a quarter member id that is not
                in ``QUARTERS``.
        """
        member = row.get(f"dim_{QUARTERS_DIMENSION}")
        quarter = QUARTERS.get(member)
        if quarter is None:
            msg = (
                f"CEPALSTAT row for indicator {CEPAL_ID} names an unknown quarter member {member!r}"
            )
            raise TransformationError(msg, source_key=self.source.key)
        return quarter

    def _assert_selected_items(self, body: Any) -> None:
        """Confirm each of the 25 selected item ids still means what it meant.

        Rows are filtered by member id, which is silent when CEPAL relabels a
        member: the filter would keep matching and REIM would store a
        different series under the same indicator code. Reading the names
        back turns that into a message that says which id changed.

        Raises:
            TransformationError: The item dimension is absent or a selected
                member has been renamed.
        """
        members = self._members_of(body, ITEM_DIMENSION, "item", CEPAL_ID)
        for item_id, expected in ITEM_NAMES.items():
            actual = members.get(item_id)
            if actual != expected:
                msg = (
                    f"CEPALSTAT item member {item_id} for indicator {CEPAL_ID} is now "
                    f"{actual!r}, not {expected!r}; the stored series would change "
                    f"meaning silently"
                )
                raise TransformationError(msg, source_key=self.source.key)
