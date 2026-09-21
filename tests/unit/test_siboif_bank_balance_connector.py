"""Unit tests for the SIBOIF banking-system balance sheet connector.

Every payload replayed here is a real recording; see tests/fixtures/.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from decimal import Decimal

import openpyxl
import pytest

from reim.core.constants import CheckSeverity, CheckStatus
from reim.core.exceptions import TransformationError
from reim.domain.pipelines.models import RawDataset
from reim.domain.sources.catalog import load_catalog
from reim.ingestion.connectors.nicaragua.siboif_bank_balance import (
    EXPECTED_UNIT_NOTE,
    IDENTITY_TOLERANCE,
    SIBOIFBankBalanceConnector,
)
from tests.conftest import REPO_ROOT

INDICATOR_CODES = {
    "assets": "ni_bank_system_total_assets_monthly",
    "liabilities": "ni_bank_system_total_liabilities_monthly",
    "equity": "ni_bank_system_total_equity_monthly",
}

#: What the recording actually holds, measured on 2026-09-21 by reading the
#: fixture directly with openpyxl, independent of the connector: 92 dated
#: columns on SISTEMA_BANCARIO, 31/01/2019 through 31/08/2026, three rows read.
MONTHS = 92
OBSERVATIONS = MONTHS * 3
FIRST_PERIOD = "2019-01"
LAST_PERIOD = "2026-08"

#: SISTEMA_BANCARIO!B11 in the recording, in the source's own thousands of NIO.
FIRST_ASSETS_THOUSANDS = Decimal("222581300.2105")

#: The identity is checked in whole córdobas here (observations are already
#: scaled by 1000 from the source's own thousands-of-NIO figures), so the
#: connector's own thousands-scale tolerance is scaled up to match.
OBSERVATION_TOLERANCE = IDENTITY_TOLERANCE * 1000


def build_connector() -> SIBOIFBankBalanceConnector:
    catalog = load_catalog(REPO_ROOT / "sources" / "catalog.yml")
    return SIBOIFBankBalanceConnector(catalog.get("siboif_bank_balance"))


def build_raw(payload: bytes) -> RawDataset:
    return RawDataset(
        source_key="siboif_bank_balance",
        retrieved_at=datetime(2026, 9, 21, 12, 0, tzinfo=UTC),
        source_url=(
            "https://www.siboif.gob.ni/sites/default/files/documentos/"
            "serie-informes-excel/bancos/ib_balance_general_0.xlsx"
        ),
        payload=payload,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        http_status=200,
        metadata={"sheet": "SISTEMA_BANCARIO"},
    )


@pytest.fixture
def raw(siboif_balance_general_xlsx: bytes) -> RawDataset:
    return build_raw(siboif_balance_general_xlsx)


def test_every_month_yields_three_observations(raw: RawDataset) -> None:
    observations = build_connector().transform(raw)
    by_indicator: dict[str, int] = {}
    for obs in observations:
        by_indicator[obs.indicator_code] = by_indicator.get(obs.indicator_code, 0) + 1
    counts = set(by_indicator.values())
    assert len(counts) == 1, f"indicators disagree on month count: {by_indicator}"
    assert set(by_indicator) == set(INDICATOR_CODES.values())


def test_the_whole_recorded_coverage_is_read_and_aligned(raw: RawDataset) -> None:
    """Exactly 92 months become exactly 276 observations, over exactly 2019-01 to 2026-08.

    The balance identity cannot stand in for this: it is invariant to a
    column shift and to dropped columns, because all three rows move
    together. ``_month_columns`` keeps only header cells that are ``str``, so
    a republication rendering the dates as real date cells would silently
    shrink the series while every other test here still passed. The exact
    count, the exact range and one known month-to-value pair are what make
    that visible, and they are the same numbers ``docs/sources.md`` publishes.
    """
    observations = build_connector().transform(raw)

    assert len(observations) == OBSERVATIONS
    periods = {obs.period.label for obs in observations}
    assert len(periods) == MONTHS
    assert min(periods) == FIRST_PERIOD
    assert max(periods) == LAST_PERIOD

    first_assets = next(
        obs
        for obs in observations
        if obs.indicator_code == INDICATOR_CODES["assets"] and obs.period.label == FIRST_PERIOD
    )
    assert first_assets.value_numeric == FIRST_ASSETS_THOUSANDS * 1000
    assert first_assets.raw_metadata["siboif_value_thousands_nio"] == str(FIRST_ASSETS_THOUSANDS)


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


def test_the_real_rounding_deviations_do_not_fail_the_identity(raw: RawDataset) -> None:
    """The recorded history must pass the check the connector runs in production.

    20 of the 92 published months break bit-exact equality by up to 0.0002 in
    the source's own thousands scale; the tolerance clears that, and this
    pins that it does over the real recording rather than in the abstract.
    """
    connector = build_connector()

    results = connector.validate(connector.transform(raw))

    assert len(results) == 1
    assert results[0].check_name == "siboif_balance_identity"
    assert results[0].status is CheckStatus.PASSED


def test_a_deviation_beyond_the_tolerance_fails(raw: RawDataset) -> None:
    """One doctored córdoba past the tolerance and the check must say so."""
    connector = build_connector()
    observations = connector.transform(raw)
    # NormalizedObservation is a mutable dataclass, not a Pydantic model:
    # there is no model_copy, so the doctored value is assigned in place.
    target = next(
        obs
        for obs in observations
        if obs.indicator_code == INDICATOR_CODES["equity"] and obs.period.label == LAST_PERIOD
    )
    assert target.value_numeric is not None
    target.value_numeric += OBSERVATION_TOLERANCE * 10

    results = connector.validate(observations)

    assert len(results) == 1
    assert results[0].status is CheckStatus.FAILED
    assert results[0].severity is CheckSeverity.ERROR
    assert LAST_PERIOD in results[0].message


def build_workbook(unit_note: str | None) -> bytes:
    """A minimal stand-in for the real sheet's layout, with the unit note under test.

    Built in memory rather than by mutating the real fixture, the same way
    ``test_row_selection_is_by_text_not_position`` does.
    """
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "SISTEMA_BANCARIO"
    sheet["A6"] = "Balances de Situación"
    sheet["A7"] = "Al 31 de Enero del 2019"
    if unit_note is not None:
        sheet["A8"] = unit_note
    sheet["A9"] = "SISTEMA BANCARIO"
    sheet["A10"], sheet["B10"] = "Descripción", "31/01/2019"
    sheet["A11"], sheet["B11"] = "Activo", 150
    sheet["A12"], sheet["B12"] = "Pasivo", 100
    sheet["A13"], sheet["B13"] = "PATRIMONIO", 50
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


@pytest.mark.parametrize(
    "unit_note",
    [
        None,
        "(Expresado en Córdobas)",
        "(Expresado en millones de Córdobas)",
    ],
)
def test_a_sheet_that_stops_declaring_thousands_raises(unit_note: str | None) -> None:
    """The x1000 conversion rests on the sheet's own note, so the note is checked.

    ``validate()`` cannot catch this: the accounting identity holds under any
    uniform rescaling, so a republication in whole or in millions of córdobas
    would be wrong by 1000x in every stored value while passing every check.
    """
    with pytest.raises(TransformationError, match=EXPECTED_UNIT_NOTE):
        build_connector().transform(build_raw(build_workbook(unit_note)))


def test_the_same_layout_with_the_note_intact_transforms() -> None:
    """Positive control: the note is the only thing the test above varies."""
    observations = build_connector().transform(
        build_raw(build_workbook(f"(Expresado en {EXPECTED_UNIT_NOTE})"))
    )

    assert len(observations) == 3
    assert {obs.period.label for obs in observations} == {FIRST_PERIOD}
