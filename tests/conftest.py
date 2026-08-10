"""Shared pytest fixtures.

Unit tests never touch a database or a network. Integration tests need
PostgreSQL and are skipped cleanly when ``REIM_TEST_DATABASE_URL`` is unset,
so ``pytest`` always runs on a bare checkout.
"""

from __future__ import annotations

import gzip
import json
import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

# Point the application's own settings at the test database before anything
# imports them, so components that legitimately use the configured connection
# (the /ready probe, the CLI) exercise a reachable server. Done here rather than
# in a fixture because Settings is cached on first access.
if os.environ.get("REIM_TEST_DATABASE_URL") and not os.environ.get("REIM_DATABASE_URL"):
    os.environ["REIM_DATABASE_URL"] = os.environ["REIM_TEST_DATABASE_URL"]

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from reim.core.constants import Frequency
from reim.database.base import Base
from reim.domain.observations.periods import parse_period
from reim.domain.pipelines.models import NormalizedObservation
from reim.domain.quality.rules import (
    IndicatorRule,
    QualityRuleSet,
    load_quality_rules,
)
from reim.domain.sources.catalog import (
    SourceCatalog,
    SourceEntry,
    load_catalog,
)

FIXTURES = Path(__file__).parent / "fixtures"
REPO_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------
# Static data
# --------------------------------------------------------------------------
@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    """Directory holding recorded and synthetic payloads."""
    return FIXTURES


@pytest.fixture(scope="session")
def worldbank_cpi_payload() -> list[Any]:
    """Real World Bank CPI response recorded on 2026-08-04."""
    return json.loads((FIXTURES / "worldbank_ni_cpi_inflation.json").read_text())


@pytest.fixture(scope="session")
def worldbank_error_payload() -> list[Any]:
    """The documented World Bank error envelope."""
    return json.loads((FIXTURES / "worldbank_error.json").read_text())


@pytest.fixture(scope="session")
def inide_workbook_bytes() -> bytes:
    """Real INIDE IPC workbook for June 2026 (stored gzipped)."""
    return gzip.decompress((FIXTURES / "inide_ipc_junio_2026.xls.gz").read_bytes())


@pytest.fixture(scope="session")
def imf_imts_csv() -> str:
    """Real IMF IMTS response for Nicaragua, world aggregate (stored gzipped)."""
    return gzip.decompress((FIXTURES / "imf_imts_nic_g001.csv.gz").read_bytes()).decode("utf-8")


@pytest.fixture(scope="session")
def imf_imts_gtm_csv() -> str:
    """Real IMF IMTS response for Guatemala, world aggregate (stored gzipped)."""
    return gzip.decompress((FIXTURES / "imf_imts_gtm_g001.csv.gz").read_bytes()).decode("utf-8")


@pytest.fixture(scope="session")
def banguat_rango_xml() -> str:
    """Banguat's whole published history, 1990-01-01 onward (stored gzipped).

    The full response is kept rather than a sample because the tests that
    matter need history no excerpt contains: the 1990-91 rows where the buy
    rate sat above the sell rate, and the five days the source skips.
    """
    return gzip.decompress((FIXTURES / "banguat_tipocambio_rango.xml.gz").read_bytes()).decode(
        "utf-8"
    )


@pytest.fixture(scope="session")
def inide_index_html() -> str:
    """Excerpt of the INIDE IPC index page, with its real workbook links."""
    return (FIXTURES / "inide_ipc_index.html").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def sieca_filters_json() -> str:
    """Real SIECA LoadFilters response: the country list and 69 quarters."""
    return (FIXTURES / "sieca_filters.json").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def sieca_exports_json() -> str:
    """Real SIECA LoadData response, exports, six countries, whole history."""
    return (FIXTURES / "sieca_flow_exports.json").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def sieca_imports_json() -> str:
    """Real SIECA LoadData response, imports, six countries, whole history."""
    return (FIXTURES / "sieca_flow_imports.json").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def sieca_balance_json() -> str:
    """Real SIECA LoadData response, balance, six countries, whole history."""
    return (FIXTURES / "sieca_flow_balance.json").read_text(encoding="utf-8")


@pytest.fixture
def inide_source(catalog: SourceCatalog) -> SourceEntry:
    """Catalog entry for the INIDE monthly CPI source."""
    return catalog.get("inide_cpi_monthly")


@pytest.fixture(scope="session")
def catalog() -> SourceCatalog:
    """The repository's real source catalog."""
    return load_catalog(REPO_ROOT / "sources" / "catalog.yml")


@pytest.fixture(scope="session")
def quality_rules() -> QualityRuleSet:
    """The repository's real quality rules."""
    return load_quality_rules(REPO_ROOT / "sources" / "quality_rules.yml")


@pytest.fixture
def cpi_source(catalog: SourceCatalog) -> SourceEntry:
    """Catalog entry for the World Bank CPI source."""
    return catalog.get("worldbank_ni_cpi_inflation")


@pytest.fixture
def bcn_source(catalog: SourceCatalog) -> SourceEntry:
    """Catalog entry for the (disabled) BCN exchange-rate source."""
    return catalog.get("bcn_exchange_rate")


@pytest.fixture
def permissive_rule() -> IndicatorRule:
    """A rule that only enforces universally safe invariants."""
    return IndicatorRule()


# --------------------------------------------------------------------------
# Builders
# --------------------------------------------------------------------------
@pytest.fixture
def make_observation():  # type: ignore[no-untyped-def]
    """Return a factory for :class:`NormalizedObservation` instances."""

    def _build(
        period: str = "2024",
        value: str | Decimal | None = "10.5",
        *,
        indicator_code: str = "ni_cpi_inflation_annual",
        source_key: str = "worldbank_ni_cpi_inflation",
        country_iso3: str = "NIC",
        unit: str = "percent",
        currency_code: str | None = None,
        frequency: Frequency | None = None,
        value_text: str | None = None,
        retrieved_at: datetime | None = None,
    ) -> NormalizedObservation:
        return NormalizedObservation(
            country_iso3=country_iso3,
            indicator_code=indicator_code,
            source_key=source_key,
            period=parse_period(period, frequency),
            unit=unit,
            currency_code=currency_code,
            value_numeric=None if value is None else Decimal(str(value)),
            value_text=value_text,
            retrieved_at=retrieved_at or datetime(2026, 8, 4, 12, 0, tzinfo=UTC),
            source_url="https://api.worldbank.org/v2/country/NIC/indicator/FP.CPI.TOTL.ZG",
            source_record_id=f"FP.CPI.TOTL.ZG:{period}",
        )

    return _build


# --------------------------------------------------------------------------
# Database (integration only)
# --------------------------------------------------------------------------
def _test_database_url() -> str | None:
    return os.environ.get("REIM_TEST_DATABASE_URL")


requires_db = pytest.mark.skipif(
    _test_database_url() is None,
    reason="Set REIM_TEST_DATABASE_URL to run integration tests (see 'make db-up')",
)


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    """Session-scoped engine against a scratch schema built from the models.

    The schema is created with ``create_all`` rather than Alembic so a broken
    migration cannot silently mask a model problem; migrations are verified
    separately by ``make migrate-check``.
    """
    url = _test_database_url()
    if url is None:
        pytest.skip("REIM_TEST_DATABASE_URL is not set")

    created = create_engine(url, future=True, pool_pre_ping=True)
    with created.connect() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS reim_test CASCADE"))
        connection.execute(text("CREATE SCHEMA reim_test"))
        connection.commit()

    scoped = create_engine(
        url,
        future=True,
        pool_pre_ping=True,
        connect_args={"options": "-csearch_path=reim_test"},
    )
    Base.metadata.create_all(scoped)
    yield scoped
    scoped.dispose()
    with created.connect() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS reim_test CASCADE"))
        connection.commit()
    created.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """A clean, isolated session; every table is truncated afterwards."""
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = factory()
    try:
        yield db
    finally:
        db.rollback()
        db.close()
        with engine.begin() as connection:
            tables = ", ".join(f"reim_test.{table.name}" for table in Base.metadata.sorted_tables)
            connection.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
def seeded_session(session: Session, catalog: SourceCatalog) -> Session:
    """A session with all reference data (countries, orgs, indicators, sources)."""
    from reim.services.seeding import seed_all

    seed_all(session, catalog)
    session.commit()
    return session


@pytest.fixture
def run_id() -> uuid.UUID:
    """A stable UUID for tests that need to reference a pipeline run."""
    return uuid.uuid4()
