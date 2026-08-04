"""ORM models.

Importing this package registers every table on ``Base.metadata``; Alembic's
``env.py`` relies on that for autogeneration.
"""

from reim.database.models.observation import (
    NATURAL_KEY_COLUMNS,
    Observation,
    ObservationRevision,
)
from reim.database.models.pipeline import DataQualityCheck, PipelineRun
from reim.database.models.reference import Country, DataSource, Indicator, Organization

__all__ = [
    "NATURAL_KEY_COLUMNS",
    "Country",
    "DataQualityCheck",
    "DataSource",
    "Indicator",
    "Observation",
    "ObservationRevision",
    "Organization",
    "PipelineRun",
]
