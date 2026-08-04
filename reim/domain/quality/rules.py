"""Per-indicator quality rules, loaded from ``sources/quality_rules.yml``.

Thresholds live in configuration rather than in code so that tuning them is a
reviewable data change. Anything not configured falls back to
:data:`DEFAULT_RULE`, which only enforces universally safe invariants.
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from reim.core.config import get_settings
from reim.core.constants import CheckSeverity
from reim.core.exceptions import ConfigurationError
from reim.domain.indicators.registry import INDICATORS_BY_CODE


class IndicatorRule(BaseModel):
    """Quality thresholds for one indicator."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    #: Inclusive bounds a value must fall within.
    min_value: Decimal | None = None
    max_value: Decimal | None = None
    #: Maximum tolerated absolute percentage change between consecutive periods.
    max_period_change_pct: Decimal | None = Field(default=None, gt=0)
    #: Whether the series may legitimately contain non-positive values.
    allow_negative: bool = True
    allow_zero: bool = True
    #: Reject periods that end after today plus this many days.
    max_future_days: int = Field(default=0, ge=0)
    #: A series is considered stale when its newest period ended more than this
    #: many days ago. ``None`` disables the freshness check.
    freshness_max_age_days: int | None = Field(default=None, gt=0)
    #: True when values are expected to be non-decreasing (e.g. a price index).
    monotonic_increasing: bool = False
    #: Severity applied when a range or change rule is violated.
    range_severity: CheckSeverity = CheckSeverity.ERROR
    change_severity: CheckSeverity = CheckSeverity.WARNING
    freshness_severity: CheckSeverity = CheckSeverity.WARNING
    #: Minimum number of observations a run must produce; below this the run is
    #: treated as a critical failure (a source that silently returns nothing).
    min_observations: int = Field(default=1, ge=0)

    @model_validator(mode="after")
    def _bounds_ordered(self) -> Self:
        if (
            self.min_value is not None
            and self.max_value is not None
            and self.min_value > self.max_value
        ):
            msg = f"min_value {self.min_value} exceeds max_value {self.max_value}"
            raise ValueError(msg)
        return self


#: Applied to indicators with no explicit configuration.
DEFAULT_RULE = IndicatorRule()


class QualityRuleSet(BaseModel):
    """The whole ``quality_rules.yml`` file."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int = Field(default=1, ge=1)
    defaults: IndicatorRule = Field(default_factory=IndicatorRule)
    indicators: dict[str, IndicatorRule] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _known_indicators(self) -> Self:
        unknown = sorted(set(self.indicators) - set(INDICATORS_BY_CODE))
        if unknown:
            msg = f"rules reference unknown indicator code(s): {', '.join(unknown)}"
            raise ValueError(msg)
        return self

    def for_indicator(self, indicator_code: str) -> IndicatorRule:
        """Return the rule for ``indicator_code``, falling back to defaults."""
        return self.indicators.get(indicator_code, self.defaults)


def load_quality_rules(path: Path | None = None) -> QualityRuleSet:
    """Load and validate the quality rule file.

    A missing file is not an error: it means "use the defaults everywhere".

    Raises:
        ConfigurationError: The file exists but is invalid.
    """
    rules_path = path or get_settings().quality_rules_path
    if not rules_path.is_file():
        return QualityRuleSet()

    try:
        raw = yaml.safe_load(rules_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        msg = f"Quality rules at {rules_path} are not valid YAML: {exc}"
        raise ConfigurationError(msg, path=str(rules_path)) from exc

    try:
        return QualityRuleSet.model_validate(raw)
    except ValidationError as exc:
        msg = f"Quality rules at {rules_path} are invalid: {exc}"
        raise ConfigurationError(msg, path=str(rules_path)) from exc


@lru_cache(maxsize=1)
def get_quality_rules() -> QualityRuleSet:
    """Return the process-wide quality rule set."""
    return load_quality_rules()


def reset_quality_rules_cache() -> None:
    """Clear the cached rule set (used by tests)."""
    get_quality_rules.cache_clear()
