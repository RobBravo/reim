"""How stale a pipeline's data may get before anyone says so.

Freshness is per source — ``latest_period_end`` is keyed on ``source_id`` — but
thresholds are per indicator, and 14 of the 23 catalog entries declare more
than one. This is the single answer every reporter of staleness uses, so
``/api/v1/status`` and ``/metrics`` cannot disagree about the same pipeline.
"""

from __future__ import annotations

from reim.domain.quality.rules import QualityRuleSet
from reim.domain.sources.catalog import SourceEntry


def freshness_threshold(entry: SourceEntry, rules: QualityRuleSet) -> int | None:
    """Return the strictest freshness threshold across a pipeline's indicators.

    When indicators disagree the strictest wins: a staleness report that fires
    early beats one that never fires.

    An indicator with no threshold is skipped rather than read as zero, so "no
    policy here" cannot silence a sibling indicator that does have one.
    """
    configured = [
        threshold
        for threshold in (
            rules.for_indicator(code).freshness_max_age_days for code in entry.indicators
        )
        if threshold is not None
    ]
    return min(configured) if configured else None
