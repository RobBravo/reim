# SIBOIF Bank Balance Sheet Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give REIM its first data from Nicaragua's banking supervisor (SIBOIF) — three verified, system-wide balance-sheet totals (assets, liabilities, equity), monthly since January 2019.

**Architecture:** No schema change. This fits REIM's existing `Country` × `Indicator` × `Period` shape exactly — the only new pieces are a connector, a new `openpyxl` dependency (the file is `.xlsx`, which the existing `xlrd>=2.0` dependency cannot read), three indicator definitions, and one catalog entry.

**Tech Stack:** Python 3.12, `openpyxl` (new), pytest, PostgreSQL 16.

**Spec:** `docs/superpowers/specs/2026-09-21-siboif-bank-balance-design.md`

## Global Constraints

- The gate, from the repository root, is
  `.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps && .venv/bin/pytest -q`.
  Integration tests need `REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim`
  (start it with `make db-up CONTAINER_ENGINE=podman` if not already running); without it most
  tests skip silently.
- No Docker daemon; use `podman`. No `pip` in `.venv`; use `.venv/bin/<tool>` (after adding the new
  dependency to `pyproject.toml`, install it into the venv the same way the project's own setup
  does — check `make setup`'s target if unsure, rather than guessing a bare `pip install`).
- `ruff format` silently rewrites any ` ```python ` block in Markdown that is not a valid
  standalone module — this exact trap has bitten this project's own plan documents twice before
  (see `docs/superpowers/plans/2026-09-20-inec-panama-provincial.md`'s own history). Fence any
  non-module Python fragment in this plan or in `docs/sources.md` as ` ```text `.
- Every measurement names its rival hypothesis before it runs.
- Never write a real password, token, webhook URL, or personal email address into any file.
- **Current baseline, confirmed 2026-09-21 against the real catalog/registry (not assumed):**
  24 sources (10 open: 6 `CC-BY-4.0` + 4 `public_official_data`; 14 not-open), 66 indicators,
  1098 tests passed / 7 deselected. After this plan: 25 sources (11 open: 6 + 5), 69 indicators.
  A prior plan's final review found stale hardcoded versions of these counts scattered across
  `README.md`, `reim/domain/sources/catalog.py`, `apps/web/templates/catalog.html`,
  `apps/web/routes.py`, `reim/cli/main.py` and two test files — Task 2 of this plan greps for
  every occurrence rather than trusting a fixed list, to not repeat that gap.
- Follow this codebase's existing patterns exactly — the task below names the specific files
  whose shape to copy (`sieca_services_trade.py` for the connector and its identity check,
  `inide_cpi_monthly.py`'s catalog entry for `access_type: file_download`).

---

### Task 1: The connector

**Files:**
- Modify: `pyproject.toml`
- Create: `reim/ingestion/connectors/nicaragua/siboif_bank_balance.py`
- Modify: `reim/domain/indicators/registry.py`
- Modify: `sources/catalog.yml`
- Modify: `sources/quality_rules.yml`
- Create: `tests/fixtures/siboif_balance_general.xlsx.gz`
- Modify: `tests/conftest.py`
- Create: `tests/unit/test_siboif_bank_balance_connector.py`

**Interfaces:**
- Consumes: nothing new from elsewhere in the codebase — `SIBOIF` is already registered in
  `reim/domain/sources/organizations.py`, Nicaragua is already seeded.
- Produces: `SIBOIFBankBalanceConnector` (`connector_key = "siboif_bank_balance"`), three new
  indicator codes (`ni_bank_system_total_assets_monthly`,
  `ni_bank_system_total_liabilities_monthly`, `ni_bank_system_total_equity_monthly`).

- [ ] **Step 1: Record the real fixture, verified again, not trusted from a prior session**

```bash
curl -s -A "REIM-fixture/1.0" \
  "https://www.siboif.gob.ni/sites/default/files/documentos/serie-informes-excel/bancos/ib_balance_general_0.xlsx" \
  -o /tmp/siboif_balance.xlsx
```

Verify it's real before trusting it:

```bash
file /tmp/siboif_balance.xlsx
```

Expected: `Microsoft Excel 2007+` (genuine OOXML, not an error page). Fetch it a second time and
confirm the two are byte-identical (`sha256sum`) — this file is known to be reproducible (fetched
twice on 2026-09-21 and confirmed identical then), so a mismatch now means something changed and
is worth investigating before proceeding, not fixing by re-running until it matches.

Gzip it into the fixtures directory:

```bash
gzip -c /tmp/siboif_balance.xlsx > tests/fixtures/siboif_balance_general.xlsx.gz
```

- [ ] **Step 2: Confirm the sheet shape you're about to build against**

Before writing any code, confirm the fixture actually has what the spec describes — the
`SISTEMA_BANCARIO` sheet, three rows whose column-A text is exactly `Activo`, `Pasivo` and
`PATRIMONIO`, and that `Pasivo + PATRIMONIO == Activo` for at least the most recent month in the
file (a fresh read, not trusting the spec's own recorded 2026-08 figures, since a month has
passed since the spec was written and the file refreshes in place). Use whatever tool is
convenient (a throwaway Python script with `openpyxl` once it's installed in Step 3, or manual
inspection) — this is a correctness check on your own understanding before you build the
connector around it, not a step that ships any code.

- [ ] **Step 3: Add the `openpyxl` dependency**

In `pyproject.toml`'s `dependencies` list (currently lines 22-42), add, next to `xlrd`'s own
entry and following its comment convention:

```text
    # INIDE publishes the IPC only as legacy BIFF .xls; xlrd is the reader.
    "xlrd>=2.0",
    # SIBOIF publishes its banking statistics as modern OOXML .xlsx, which
    # xlrd 2.0+ deliberately cannot read (it dropped .xlsx support entirely).
    "openpyxl>=3.1",
```

Install it into the project's virtualenv the way this project's own setup does (check
`make setup`'s target in the `Makefile` for the exact command — likely
`.venv/bin/pip install -e ".[dev]"` or an equivalent `uv` invocation; this project has no `pip`
available as a bare command per the Global Constraints, so use whatever the Makefile's own
target uses).

Run `.venv/bin/mypy --strict reim/ingestion/connectors/nicaragua/` once you've written the
connector in Step 6 and confirm whether `openpyxl`'s own type stubs are sufficient. If mypy
complains about missing stubs for `openpyxl.*`, add a `[[tool.mypy.overrides]]` block following
the existing `xlrd.*` one (currently around line 127-131) — but only if the error actually
appears; don't add it speculatively.

- [ ] **Step 4: Register the three indicators**

In `reim/domain/indicators/registry.py`, add three entries, following the existing shape exactly
(check the real `IndicatorCategory`/`Frequency`/`ValueType` imports already at the top of the
file):

```text
    IndicatorDefinition(
        code="ni_bank_system_total_assets_monthly",
        name="Nicaragua — banking system total assets",
        description=(
            "Total assets of Nicaragua's banking system (SISTEMA BANCARIO), monthly, from "
            "SIBOIF's published balance sheet. Verified to satisfy Activo = Pasivo + Patrimonio "
            "against the published liabilities and equity figures for the same period."
        ),
        category=IndicatorCategory.FINANCIAL,
        frequency=Frequency.MONTHLY,
        unit="current NIO",
        value_type=ValueType.LEVEL,
        methodology_url="https://www.siboif.gob.ni/consultas/informes",
        currency_convertible=False,
    ),
    IndicatorDefinition(
        code="ni_bank_system_total_liabilities_monthly",
        name="Nicaragua — banking system total liabilities",
        description=(
            "Total liabilities of Nicaragua's banking system (SISTEMA BANCARIO), monthly, from "
            "SIBOIF's published balance sheet."
        ),
        category=IndicatorCategory.FINANCIAL,
        frequency=Frequency.MONTHLY,
        unit="current NIO",
        value_type=ValueType.LEVEL,
        methodology_url="https://www.siboif.gob.ni/consultas/informes",
        currency_convertible=False,
    ),
    IndicatorDefinition(
        code="ni_bank_system_total_equity_monthly",
        name="Nicaragua — banking system total equity",
        description=(
            "Total equity (PATRIMONIO) of Nicaragua's banking system (SISTEMA BANCARIO), "
            "monthly, from SIBOIF's published balance sheet."
        ),
        category=IndicatorCategory.FINANCIAL,
        frequency=Frequency.MONTHLY,
        unit="current NIO",
        value_type=ValueType.LEVEL,
        methodology_url="https://www.siboif.gob.ni/consultas/informes",
        currency_convertible=False,
    ),
```

- [ ] **Step 5: Add the catalog entry**

In `sources/catalog.yml`, following `inide_cpi_monthly`'s exact shape for `access_type` and
`format` (currently around lines 159-179 — a static Excel download, not a queryable API):

```yaml
  # ------------------------------------------------------------------------
  # Nicaragua — SIBOIF banking system balance sheet
  #
  # Static .xlsx, refreshed in place, no session or query parameters. Holds
  # 14 named banks plus two system-wide aggregate sheets; only the
  # system-wide SISTEMA_BANCARIO sheet is read. Verified live 2026-09-21:
  # Activo = Pasivo + Patrimonio to four decimal places.
  # ------------------------------------------------------------------------
  - key: siboif_bank_balance
    name: Nicaragua banking system balance sheet (monthly)
    description: >-
      System-wide total assets, liabilities and equity for Nicaragua's
      banking system, from SIBOIF's published balance sheet. Verified to
      satisfy Activo = Pasivo + Patrimonio for every period.
    country: NI
    organization: SIBOIF
    category: financial
    access_type: file_download
    frequency: monthly
    format: xlsx
    base_url: https://www.siboif.gob.ni
    documentation_url: https://www.siboif.gob.ni/consultas/informes
    connector: reim.ingestion.connectors.nicaragua.siboif_bank_balance
    indicators:
      - ni_bank_system_total_assets_monthly
      - ni_bank_system_total_liabilities_monthly
      - ni_bank_system_total_equity_monthly
    license: public_official_data
    official: true
    enabled: true
```

- [ ] **Step 6: Write the failing connector tests**

Create `tests/unit/test_siboif_bank_balance_connector.py`. Read `tests/unit/test_sieca_connector.py`
first (the `build_connector()`/`build_raw()` fixture-loading pattern) and follow its shape, not a
reinvention of it:

```text
"""Unit tests for the SIBOIF banking-system balance sheet connector.

Every payload replayed here is a real recording; see tests/fixtures/.
"""

from __future__ import annotations

import gzip
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from reim.core.exceptions import TransformationError
from reim.domain.pipelines.models import RawDataset
from reim.domain.sources.catalog import load_catalog
from reim.ingestion.connectors.nicaragua.siboif_bank_balance import (
    SIBOIFBankBalanceConnector,
)
from tests.conftest import REPO_ROOT

INDICATOR_CODES = {
    "assets": "ni_bank_system_total_assets_monthly",
    "liabilities": "ni_bank_system_total_liabilities_monthly",
    "equity": "ni_bank_system_total_equity_monthly",
}


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
    """Activo == Pasivo + Patrimonio for every period this connector produces.

    This is the load-bearing test: the connector's whole justification is
    that these three figures are genuine, reconciled totals, not an
    assumption made from their row labels.
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
        assert assets == liabilities + equity, (
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
    assets = next(
        o for o in observations if o.indicator_code == INDICATOR_CODES["assets"]
    )
    # The raw fixture's own most-recent-month value is in thousands of NIO;
    # the stored value must be exactly 1000x that, and raw_metadata must
    # carry the original.
    assert assets.value_numeric == Decimal(assets.raw_metadata["siboif_value_thousands_nio"]) * 1000
    assert assets.currency_code == "NIO"
    assert assets.unit == "current NIO"
```

`test_row_selection_is_by_text_not_position` imports `_find_row_by_label` from the connector
module written in Step 9 — this test will fail to collect until that step is done, which is
expected and matches this plan's own TDD ordering (Step 8 confirms failure, Step 9 implements,
Step 10 confirms all four tests pass genuinely).

- [ ] **Step 7: Register the fixture loader**

In `tests/conftest.py`, following the `sieca_*_json`/`inec_*_json` fixtures' exact shape:

```text
@pytest.fixture(scope="session")
def siboif_balance_general_xlsx() -> bytes:
    """Real SIBOIF banking-system balance sheet, gzipped to keep the repo small."""
    with gzip.open(FIXTURES / "siboif_balance_general.xlsx.gz", "rb") as f:
        return f.read()
```

Add `import gzip` at the top of the file if it isn't already imported (check first).

- [ ] **Step 8: Run the tests to verify they fail**

```bash
.venv/bin/pytest tests/unit/test_siboif_bank_balance_connector.py -v
```

Expected: collection error or `ModuleNotFoundError` — `siboif_bank_balance.py` doesn't exist yet.

- [ ] **Step 9: Write the connector**

Create `reim/ingestion/connectors/nicaragua/siboif_bank_balance.py`. Read
`reim/ingestion/connectors/regional/sieca_services_trade.py`'s imports, `extract()`, and
`_check_balance_identity` once more before writing this — this codebase does not call `httpx`
directly from a connector (confirmed convention across every connector in this codebase); use
`reim.ingestion.http`'s `http_client`/`fetch`/`ensure_ok`, and `QualityResult`'s
`.passed()`/`.failure()` factory classmethods, not the raw constructor:

```text
"""SIBOIF — Nicaragua banking system balance sheet.

Three system-wide totals (assets, liabilities, equity), monthly, read from
the SISTEMA_BANCARIO sheet of SIBOIF's published balance sheet workbook.
Verified to satisfy Activo = Pasivo + Patrimonio for every period this
connector produces.

See docs/sources.md's SIBOIF entry and
docs/superpowers/specs/2026-09-21-siboif-bank-balance-design.md for the
research this is built from.
"""

from __future__ import annotations

import io
from datetime import datetime
from decimal import Decimal
from typing import Any

import openpyxl

from reim.core.constants import CheckSeverity, CheckType, Frequency
from reim.core.exceptions import TransformationError
from reim.domain.observations.periods import parse_period
from reim.domain.pipelines.models import NormalizedObservation, QualityResult, RawDataset
from reim.ingestion.base import BaseConnector
from reim.ingestion.http import ensure_ok, fetch, http_client

SHEET_NAME = "SISTEMA_BANCARIO"

#: Column-A text -> REIM indicator code. Order doesn't matter; this is the
#: authority on which three of the sheet's 95 rows this connector reads.
ROW_INDICATORS: dict[str, str] = {
    "Activo": "ni_bank_system_total_assets_monthly",
    "Pasivo": "ni_bank_system_total_liabilities_monthly",
    "PATRIMONIO": "ni_bank_system_total_equity_monthly",
}

#: Tolerance for the accounting identity, in the source's own thousands-of-NIO
#: scale (matching its own four-decimal precision) -- not the whole-córdoba
#: scale the connector stores.
IDENTITY_TOLERANCE = Decimal("0.01")


class SIBOIFBankBalanceConnector(BaseConnector):
    """System-wide balance-sheet totals for Nicaragua's banking sector."""

    connector_key = "siboif_bank_balance"
    version = "1.0.0"
    expected_frequency = Frequency.MONTHLY

    async def extract(self) -> RawDataset:
        """Fetch the static balance-sheet workbook.

        One request. The file is refreshed in place by SIBOIF (no date or
        version in the URL), so each run re-reads the full history.

        Raises:
            ExtractionError: The file was unreachable or not the expected
                content type.
        """
        url = (
            f"{str(self.source.base_url).rstrip('/')}/sites/default/files/documentos/"
            "serie-informes-excel/bancos/ib_balance_general_0.xlsx"
        )
        retrieved_at = self.now()

        async with http_client(user_agent=self.source.user_agent) as client:
            response = await fetch(client, url)
            ensure_ok(
                response,
                expected_content_type=(
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                ),
            )
            content = response.content

        return RawDataset(
            source_key=self.connector_key,
            retrieved_at=retrieved_at,
            source_url=url,
            payload=content,
            content_type=response.headers.get("content-type"),
            http_status=response.status_code,
            metadata={"sheet": SHEET_NAME},
        )

    def transform(self, raw: RawDataset) -> list[NormalizedObservation]:
        workbook = openpyxl.load_workbook(
            io.BytesIO(raw.payload), read_only=True, data_only=True
        )
        try:
            sheet = workbook[SHEET_NAME]
        except KeyError as exc:
            msg = f"Sheet {SHEET_NAME!r} not found in workbook"
            raise TransformationError(msg) from exc

        header_row = _find_header_row(sheet)
        month_columns = _month_columns(sheet, header_row)

        observations: list[NormalizedObservation] = []
        for label, indicator_code in ROW_INDICATORS.items():
            row_cells = _find_row_by_label(sheet, label)
            for column_index, date_str in month_columns:
                value = row_cells[column_index]
                if value is None:
                    continue
                period = parse_period(_to_monthly_label(date_str), Frequency.MONTHLY)
                thousands_value = Decimal(str(value))
                observations.append(
                    NormalizedObservation(
                        country_iso3="NIC",
                        indicator_code=indicator_code,
                        source_key=self.connector_key,
                        period=period,
                        unit="current NIO",
                        retrieved_at=raw.retrieved_at,
                        source_url=raw.source_url,
                        value_numeric=thousands_value * 1000,
                        currency_code="NIO",
                        raw_metadata={"siboif_value_thousands_nio": str(thousands_value)},
                    )
                )

        if not observations:
            msg = "SIBOIF connector produced zero observations"
            raise TransformationError(msg)

        return observations

    def validate(self, observations: list[NormalizedObservation]) -> list[QualityResult]:
        """Assert Activo == Pasivo + Patrimonio for every period produced."""
        by_period: dict[str, dict[str, Decimal]] = {}
        for obs in observations:
            if obs.value_numeric is None:
                continue
            by_period.setdefault(obs.period.label, {})[obs.indicator_code] = obs.value_numeric

        broken = []
        for period, values in sorted(by_period.items()):
            assets = values.get("ni_bank_system_total_assets_monthly")
            liabilities = values.get("ni_bank_system_total_liabilities_monthly")
            equity = values.get("ni_bank_system_total_equity_monthly")
            if assets is None or liabilities is None or equity is None:
                continue
            if abs(assets - liabilities - equity) > IDENTITY_TOLERANCE * 1000:
                broken.append(period)

        if not broken:
            return [
                QualityResult.passed(
                    "siboif_balance_identity",
                    CheckType.CONSISTENCY,
                    f"Activo = Pasivo + Patrimonio holds for all {len(by_period)} period(s)",
                    expected_value="0 beyond tolerance",
                    actual_value="0",
                )
            ]
        return [
            QualityResult.failure(
                "siboif_balance_identity",
                CheckType.CONSISTENCY,
                CheckSeverity.ERROR,
                f"{len(broken)} period(s) break the balance identity: {', '.join(broken[:5])}",
                expected_value="0 beyond tolerance",
                actual_value=str(len(broken)),
            )
        ]

def _find_header_row(sheet: Any) -> int:
    """Return the row index whose first cell is 'Descripción'."""
    for row in sheet.iter_rows(min_row=1, max_row=20):
        if row[0].value == "Descripción":
            return row[0].row
    msg = "Could not find the 'Descripción' header row"
    raise TransformationError(msg)


def _month_columns(sheet: Any, header_row: int) -> list[tuple[int, str]]:
    """Return (0-based column index, date string) for every dated column."""
    columns = []
    for cell in sheet[header_row]:
        if cell.column == 1:
            continue
        if isinstance(cell.value, str) and "/" in cell.value:
            columns.append((cell.column - 1, cell.value))
    return columns


def _find_row_by_label(sheet: Any, label: str) -> list[Any]:
    """Return the full row of values whose column-A text exactly matches ``label``."""
    for row in sheet.iter_rows(values_only=True):
        if row and row[0] == label:
            return list(row)
    msg = f"Could not find a row labelled {label!r} in {SHEET_NAME}"
    raise TransformationError(msg)


def _to_monthly_label(date_str: str) -> str:
    """Convert a day-first 'DD/MM/YYYY' string to REIM's 'YYYY-MM' monthly label."""
    parsed = datetime.strptime(date_str, "%d/%m/%Y")
    return f"{parsed.year:04d}-{parsed.month:02d}"
```

This is complete, working code as far as the design was verified — but two things in it were not
independently re-confirmed while writing this plan and must be checked against the real fixture
in Step 2/10, not assumed: (a) `_find_header_row`'s assumption that `"Descripción"` is the exact
literal header text in column A of the header row (this matches what was extracted during the
spike, but re-confirm against your own fresh read), and (b) that `openpyxl`'s `read_only=True`
worksheet supports both `sheet[header_row]` (row-by-index access, used in `_month_columns`) and
`.iter_rows(values_only=True)` (used in `_find_row_by_label`) — read-only mode in `openpyxl` has
some access-pattern restrictions that differ from normal mode; verify both patterns actually work
against the real fixture before trusting this code, and adjust if `openpyxl`'s read-only API
doesn't support one of them (e.g. `sheet[header_row]` may need to become
`next(sheet.iter_rows(min_row=header_row, max_row=header_row))[0]` instead, since read-only
worksheets may not support direct row-slicing).

- [ ] **Step 10: Run the tests, fix what the real fixture reveals, iterate to green**

```bash
.venv/bin/pytest tests/unit/test_siboif_bank_balance_connector.py -v
```

Expect failures the first time — this connector's code above was written from the spec's research,
not from running it against the real fixture. `test_row_selection_is_by_text_not_position` doesn't
depend on the real fixture at all (it builds its own tiny workbook) and should pass as soon as
`_find_row_by_label` exists with the right signature; the other three tests depend on the real
`Descripción` header text and the real column layout matching what §3 of the spec recorded — fix
whatever the real fixture reveals differs from that (per the two open concerns just above) until
all 4 tests pass genuinely, not until they merely stop erroring.

- [ ] **Step 11: Confirm the catalog and quality-rules changes validate**

```bash
make catalog-validate
```

Expected: no exception, output confirming the catalog and quality rules are valid. (This will
fail until Step 12 adds a `quality_rules.yml` entry for the new indicators, if that entry is
required for validation to pass — check whether an indicator with no quality rule entry is
actually rejected or just silently uses defaults, by reading `reim/domain/quality/rules.py`
briefly, before assuming Step 12 must come first.)

- [ ] **Step 12: Add quality-rule entries**

In `sources/quality_rules.yml`, under `indicators:`, add three entries. Values must be positive
(a bank's total assets/liabilities/equity cannot be negative or zero), and the freshness
threshold should reflect genuine monthly publication — SIBOIF's own file title states the most
recent month, and this data has been published monthly and on time going back to 2019, so a
tighter threshold than the loose ones this codebase uses for uncertain-cadence sources (INEC
Panama's 1200-day threshold, justified there by having only one observed reference year) is
appropriate here — but confirm the actual publication lag (how many days after month-end does the
file typically update?) before picking an exact number rather than guessing; a reasonable starting
point given a monthly series is 60-90 days, tightened once a real lag is observed across a few
runs.

```yaml
  # Nicaragua — SIBOIF banking system balance sheet -------------------------
  # Positive values only: none of these three totals can be zero or negative
  # for an operating banking system. Freshness threshold reflects genuine
  # monthly publication (unlike INEC Panama's loose threshold, justified
  # there by having only one observed reference year) -- confirm the actual
  # publication lag before trusting the number below unchanged.
  ni_bank_system_total_assets_monthly:
    min_value: 0
    max_value: null
    allow_negative: false
    allow_zero: false
    freshness_max_age_days: 75

  ni_bank_system_total_liabilities_monthly:
    min_value: 0
    max_value: null
    allow_negative: false
    allow_zero: false
    freshness_max_age_days: 75

  ni_bank_system_total_equity_monthly:
    min_value: 0
    max_value: null
    allow_negative: false
    allow_zero: false
    freshness_max_age_days: 75
```

Re-run `make catalog-validate` and the connector tests to confirm both still pass.

- [ ] **Step 13: Seed and confirm an end-to-end run works against the real API**

```bash
.venv/bin/reim db seed
.venv/bin/reim pipeline run siboif_bank_balance
```

Expected: the run succeeds and reports roughly 3× the number of months the live file currently
holds (92 or more, growing by one each month since this design was written) observations, and
`validate()`'s balance-identity check is green. Note the actual counts in your task report —
don't assume they match this plan's own §3 table, which is now over a month stale by the time
this step runs.

- [ ] **Step 14: Gate and commit**

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy reim apps
REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim .venv/bin/pytest -q
```

```bash
git add pyproject.toml reim/ingestion/connectors/nicaragua/siboif_bank_balance.py \
  reim/domain/indicators/registry.py sources/catalog.yml sources/quality_rules.yml \
  tests/fixtures/siboif_balance_general.xlsx.gz tests/conftest.py \
  tests/unit/test_siboif_bank_balance_connector.py
git commit -m "feat(nicaragua): ingest SIBOIF's banking system balance sheet"
```

---

### Task 2: Documentation and the whole-suite gate

**Files:**
- Modify: `docs/sources.md`
- Modify: `README.md`
- Modify: any other file a repo-wide grep finds hardcoding the old source/indicator counts

**Interfaces:** none — documentation only, plus the final full-repo gate.

- [ ] **Step 1: Update `docs/sources.md`**

Remove the `SIBOIF` row from the "Registered but not yet implemented" table (currently around
line 2551). Add a new section for SIBOIF, matching the structure and tone of a recently-added
source's own section (read the INEC Panama section — `### INEC Panama — an open API behind a map`
region — or the SIECA section for the closest match in shape: a static-file source, not an API).
Cover: the organization, the two paths measured (the batch-export browser, rejected, and the
static file series, used — see the spec §2 for the exact reasoning to summarize, not repeat
verbatim), the three indicators shipped, the accounting-identity verification, and the two
disclosed data irregularities from the file itself (Banco Produzcamos consolidation Jan 2019,
BANCORP's 2019 dissolution). Name what's excluded and why: `SISTEMA_FINANCIERO`, per-institution
figures, the income statement (confirmed to exist, excluded on scope grounds only — say so
plainly, don't repeat the spec's own self-correction story, just state the current, correct fact).

- [ ] **Step 2: Find and fix every stale count, not just the ones already known**

The exact new counts, confirmed against the real catalog/registry after Task 1 lands:

```bash
.venv/bin/python3 -c "
from reim.domain.sources.catalog import load_catalog, OPEN_LICENCES
from reim.domain.indicators.registry import INDICATORS
cat = load_catalog()
sources = cat.sources
open_count = sum(1 for s in sources if s.license in OPEN_LICENCES)
print('sources:', len(sources), 'open:', open_count, 'not-open:', len(sources) - open_count)
print('indicators:', len(INDICATORS))
"
```

Expected: 25 sources, 11 open, 14 not-open, 69 indicators (if these don't match, something in
Task 1 didn't land as this plan expected — investigate before proceeding, don't just use whatever
number the script prints without understanding why it differs).

Grep the whole repository for the **old** numbers (24, 66, and the open/not-open breakdown
6/4/10) and fix every genuine hit — a previous plan's final review found stale copies of these
exact counts in `README.md` (the headline line, the catalog-browser description, the `/series`
page description), `reim/domain/sources/catalog.py` (the `OPEN_LICENCES` docstring's own measured
proportions), `apps/web/templates/catalog.html`, `apps/web/routes.py`, `reim/cli/main.py`, and two
test files (`tests/unit/test_catalog.py`, `tests/integration/test_web.py`). Check every one of
those specific locations, and also run a broader grep in case a new hardcoded count exists that
this list doesn't know about — this plan is deliberately not trusting that list to be exhaustive a
second time. Recompute any derived proportion (e.g. "14 of 24… the other 10 are open: 6 under
CC-BY-4.0… and 4 under public_official_data") rather than just bumping the total, the same
non-mechanical correction the prior plan's fix wave made.

Do **not** touch `ROADMAP.md`'s done-bullets that cite historical counts (e.g. "All 23 sources" in
the v0.4.0 catalog-browser bullet) — those are frozen snapshots of what a feature listed when it
shipped, not live counts, confirmed as this codebase's own established convention by the prior
plan's final review.

- [ ] **Step 3: Add a source-table row to README.md**

Follow the existing table's exact formatting (see the INEC Panama row added by a prior plan for
the most recent example of the pattern for a non-CEPALSTAT, non-World-Bank national source).

- [ ] **Step 4: Full gate, one more time, from a clean check**

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy reim apps
REIM_TEST_DATABASE_URL=postgresql+psycopg://reim:reim@localhost:55432/reim .venv/bin/pytest -q
```

Expected: everything clean, and the full suite's passed count has grown by roughly 4-6 tests over
this plan's own additions (Task 1's four connector tests, plus whatever count-assertion updates
Step 2 touched in existing tests without adding new ones).

- [ ] **Step 5: Commit**

```bash
git add docs/sources.md README.md
# plus any other files Step 2 touched -- name them explicitly in this commit,
# don't use a broad `git add -A`
git commit -m "docs: record SIBOIF's banking-system balance sheet as shipped"
```

## Deliberately not in this plan

* **`SISTEMA_FINANCIERO`** and **per-institution** figures. Same file, different scope, a later
  increment's own decision — see spec §10.
* **The income statement** (`ib_estado_resultados_0.xlsx`). Confirmed live and same-shape; a real,
  same-effort follow-up, not attempted here.
* **The other ~92 line items** of the balance sheet. Real, available, not "aggregates."
* **Currency conversion** (`currency_convertible=True`). Flag exists, decision deferred — see spec
  D6.
* **Seguros, Valores, Almacenes** — SIBOIF's other three regulated sectors, same site pattern,
  not investigated.

## Done when

* `openpyxl` is a declared dependency and reads the real fixture without error.
* Three new indicators are registered and seed cleanly.
* The connector's `validate()` proves `Activo = Pasivo + Patrimonio` for every period it produces,
  and a guard test proves this against the real fixture, not a synthetic one.
* A guard test proves row selection is genuinely by column-A text, not a hardcoded row position.
* `reim pipeline run siboif_bank_balance` succeeds against the real, live SIBOIF file.
* `docs/sources.md` reflects what actually shipped, including the two disclosed data
  irregularities and what was deliberately excluded.
* Every hardcoded source/indicator count in the repository — not just the ones already known from
  a prior plan's review — matches the real post-merge catalog and registry.
* The full gate passes: `ruff check`, `ruff format --check`, `mypy reim apps`, `pytest -q`.
