"""The connector contract.

A connector is responsible for exactly three things:

1. :meth:`~BaseConnector.extract` — retrieve the raw payload from the source.
2. :meth:`~BaseConnector.transform` — normalize it into observations.
3. :meth:`~BaseConnector.validate` — assert source-specific expectations.

Everything else — run bookkeeping, transactions, persistence, idempotency,
generic quality checks, error handling and structured logging — belongs to
:mod:`reim.ingestion.runner`, so that no connector can get it subtly wrong.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime

from reim.core.constants import Frequency
from reim.core.logging import get_logger
from reim.domain.pipelines.models import (
    NormalizedObservation,
    QualityResult,
    RawDataset,
)
from reim.domain.sources.catalog import SourceEntry


class BaseConnector(ABC):
    """Abstract base class every connector must implement.

    Attributes:
        connector_key: Stable identifier; must equal the catalog ``key``.
        version: Connector version, stamped on every observation it produces.
            Bump it whenever ``transform`` changes its output for the same input.
    """

    connector_key: str
    version: str
    #: Frequency the connector is expected to emit; used by generic checks.
    expected_frequency: Frequency = Frequency.ANNUAL

    def __init__(self, source: SourceEntry) -> None:
        if source.key != self.connector_key:
            msg = f"Catalog key {source.key!r} does not match connector key {self.connector_key!r}"
            raise ValueError(msg)
        self.source = source
        self.logger = get_logger(
            type(self).__module__,
            source_key=source.key,
            connector_version=self.version,
        )

    # -- Contract ---------------------------------------------------------
    @abstractmethod
    async def extract(self) -> RawDataset:
        """Retrieve the raw payload from the source.

        Implementations must not write to the database and must not mutate
        global state.

        Raises:
            ExtractionError: The source was unreachable or unusable.
        """

    @abstractmethod
    def transform(self, raw: RawDataset) -> list[NormalizedObservation]:
        """Normalize a raw payload into observations.

        Must be a pure function of ``raw`` so it can be tested against a
        recorded fixture without network access.

        Raises:
            TransformationError: The payload could not be interpreted.
        """

    @abstractmethod
    def validate(self, observations: list[NormalizedObservation]) -> list[QualityResult]:
        """Run source-specific quality checks.

        The runner always applies the standard battery from
        :mod:`reim.domain.quality.checks`; this method adds expectations only
        this source can express.
        """

    # -- Shared helpers ---------------------------------------------------
    @property
    def country_iso2(self) -> str | None:
        """ISO-3166 alpha-2 code of the source's country, if any."""
        return self.source.country_iso2

    @staticmethod
    def now() -> datetime:
        """Return the current UTC timestamp used for ``retrieved_at``."""
        return datetime.now(UTC)

    def describe(self) -> dict[str, str]:
        """Return identifying fields for structured logs and run metadata."""
        return {
            "connector_key": self.connector_key,
            "connector_version": self.version,
            "source_key": self.source.key,
            "organization": self.source.organization,
        }
