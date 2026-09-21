"""Unit tests for the SIBOIF banking-system balance sheet connector.

Every payload replayed here is a real recording; see tests/fixtures/.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from reim.core.exceptions import TransformationError
from reim.domain.pipelines.models import RawDataset
from reim.domain.sources.catalog import load_catalog
from reim.ingestion.connectors.nicaragua.siboif_bank_balance import (
    IDENTITY_TOLERANCE,
    SIBOIFBankBalanceConnector,
)
from tests.conftest import REPO_ROOT

INDICATOR_CODES = {
    "assets": "ni_bank_system_total_assets_monthly",
    "liabilities": "ni_bank_system_total_liabilities_monthly",
    "equity": "ni_bank_system_total_equity_monthly",
}

#: The identity is checked in whole córdobas here (observations are already
#: scaled by 1000 from the source's own thousands-of-NIO figures), so the
#: connector's own thousands-scale tolerance is scaled up to match.
OBSERVATION_TOLERANCE = IDENTITY_TOLERANCE * 1000


def build_connector() -> SIBOIFBankBalanceConnector:
    catalog = load_catalog(REPO_ROOT / "sources" / "catalog.yml")
    return SIBOIFBankBalanceConnector(catalog.get("siboif_bank_balance"))


@pytest.fixture
def raw(siboif_balance_general_xlsx: bytes) -> RawDataset:
    return RawDataset(
        source_key="siboif_bank_balance",
        retrieved_at=datetime(2026, 9, 21, 12, 0, tzinfo=UTC),
        source_url=(
            "https://www.siboif.gob.ni/sites/default/files/documentos/"
            "serie-informes-excel/bancos/ib_balance_general_0.xlsx"
        ),
        payload=siboif_balance_general_xlsx,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        http_status=200,
        metadata={"sheet": "SISTEMA_BANCARIO"},
    )


def test_every_month_yields_three_observations(raw: RawDataset) -> None:
    observations = build_connector().transform(raw)
    by_indicator: dict[str, int] = {}
    for obs in observations:
        by_indicator[obs.indicator_code] = by_indicator.get(obs.indicator_code, 0) + 1
    counts = set(by_indicator.values())
    assert len(counts) == 1, f"indicators disagree on month count: {by_indicator}"
    assert set(by_indicator) == set(INDICATOR_CODES.values())


def test_the_accounting_identity_holds_for_every_month(raw: RawDataset) -> None:
    """Activo == Pasivo + Patrimonio, within tolerance, for every period this connector produces.

    This is the load-bearing test: the connector's whole justification is
    that these three figures are genuine, reconciled totals, not an
    assumption made from their row labels.

    The real fixture does not satisfy bit-exact equality here: 20 of the 92
    published months differ from the identity by up to 0.0002 (in the
    source's own thousands-of-córdobas scale) -- a rounding artifact in
    SIBOIF's own published figures, not a defect in how this connector reads
    them. This is confirmed by re-deriving the same 20 mismatches directly
    from the raw workbook, independent of this connector's code. The
    tolerance below is the same one the connector's own ``validate()``
    quality check uses, so this test and that check agree on what "holds"
    means.
    """
    observations = build_connector().transform(raw)
    by_period_and_indicator: dict[tuple[str, str], Decimal] = {
        (obs.period.label, obs.indicator_code): obs.value_numeric
        for obs in observations
        if obs.value_numeric is not None
    }
    periods = {label for label, _ in by_period_and_indicator}
    assert len(periods) > 0

    for period in periods:
        assets = by_period_and_indicator[(period, INDICATOR_CODES["assets"])]
        liabilities = by_period_and_indicator[(period, INDICATOR_CODES["liabilities"])]
        equity = by_period_and_indicator[(period, INDICATOR_CODES["equity"])]
        assert abs(assets - liabilities - equity) <= OBSERVATION_TOLERANCE, (
            f"{period}: {assets} != {liabilities} + {equity}"
        )


def test_row_selection_is_by_text_not_position() -> None:
    """A future SIBOIF republication that inserts a row above these three must not break this.

    Verified by construction against a small in-memory workbook, not by
    mutating the real fixture: proves the lookup searches by column-A text
    rather than reading a hardcoded row index, regardless of what row the
    label actually sits on.
    """
    import openpyxl

    from reim.ingestion.connectors.nicaragua.siboif_bank_balance import _find_row_by_label

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["Some Other Label", 1, 2, 3])
    sheet.append(["Activo", 100, 200, 300])
    sheet.append(["Pasivo", 40, 50, 60])

    row = _find_row_by_label(sheet, "Activo")
    assert row[0] == "Activo"
    assert row[1] == 100

    with pytest.raises(TransformationError):
        _find_row_by_label(sheet, "Does Not Exist")


def test_values_convert_thousands_to_whole_cordobas(raw: RawDataset) -> None:
    observations = build_connector().transform(raw)
    assets = next(o for o in observations if o.indicator_code == INDICATOR_CODES["assets"])
    # The raw fixture's own most-recent-month value is in thousands of NIO;
    # the stored value must be exactly 1000x that, and raw_metadata must
    # carry the original.
    assert assets.value_numeric == Decimal(assets.raw_metadata["siboif_value_thousands_nio"]) * 1000
    assert assets.currency_code == "NIO"
    assert assets.unit == "current NIO"
