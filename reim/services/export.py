"""CSV export of observations.

Rows are streamed so a large export never materialises in memory. The column
order is fixed by :data:`~reim.schemas.observations.CSV_COLUMNS` and is treated
as a stable contract.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator

from sqlalchemy.orm import Session

from reim.database.models import Observation
from reim.repositories.observations import ObservationFilters, iter_observations
from reim.schemas.observations import CSV_COLUMNS


def _row(observation: Observation) -> dict[str, str]:
    """Flatten one observation into CSV cells.

    Decimals are rendered with :func:`str` so full stored precision survives the
    round trip — never through ``float``.
    """
    return {
        "country_iso3": observation.country.iso3,
        "country_name": observation.country.name,
        "indicator_code": observation.indicator.code,
        "indicator_name": observation.indicator.name,
        "period_label": observation.period_label,
        "period_start": observation.period_start.isoformat(),
        "period_end": observation.period_end.isoformat(),
        "value_numeric": ""
        if observation.value_numeric is None
        else str(observation.value_numeric),
        "unit": observation.unit,
        "currency_code": observation.currency_code or "",
        "source_key": observation.source.source_key,
        "source_url": observation.source_url,
        "published_at": observation.published_at.isoformat() if observation.published_at else "",
        "retrieved_at": observation.retrieved_at.isoformat(),
        "validation_status": observation.validation_status.value,
        "revision_count": str(observation.revision_count),
        "connector_version": observation.connector_version,
        "pipeline_version": observation.pipeline_version,
        "content_hash": observation.content_hash,
    }


def stream_observations_csv(
    session: Session,
    filters: ObservationFilters,
    *,
    limit: int,
    sort_by: str = "period_start",
    descending: bool = True,
    chunk_rows: int = 500,
) -> Iterator[str]:
    """Yield the CSV export in chunks, header first.

    Args:
        session: Active session; must stay open while the iterator is consumed.
        filters: Which observations to export.
        limit: Hard cap on exported rows (``REIM_MAX_EXPORT_ROWS``).
        sort_by: Column to order by.
        descending: Sort direction.
        chunk_rows: Rows accumulated per yielded string.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(CSV_COLUMNS), lineterminator="\n")
    writer.writeheader()
    yield buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)

    pending = 0
    for observation in iter_observations(
        session, filters, limit=limit, sort_by=sort_by, descending=descending
    ):
        writer.writerow(_row(observation))
        pending += 1
        if pending >= chunk_rows:
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)
            pending = 0

    if pending:
        yield buffer.getvalue()
