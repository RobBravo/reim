"""One freshness threshold, shared by every reporter of it.

The catalog contains no source whose indicators disagree, so every real input
gives the same answer whether you read ``indicators[0]`` or take the strictest.
These tests build the case the catalog lacks — the only input that can tell the
two rules apart.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from reim.domain.quality.freshness import freshness_threshold
from reim.domain.quality.rules import IndicatorRule, QualityRuleSet
from reim.domain.sources.catalog import SourceCatalog, get_catalog

#: A real entry declaring three indicators, in this order.
ENTRY_KEY = "imf_imts_nicaragua"
FIRST_INDICATOR = "exports_goods_monthly"
SECOND_INDICATOR = "imports_goods_monthly"


@pytest.fixture
def entry():
    catalog = get_catalog()
    entry = next(source for source in catalog.sources if source.key == ENTRY_KEY)
    assert entry.indicators[0] == FIRST_INDICATOR, "catalog changed; pick another entry"
    assert SECOND_INDICATOR in entry.indicators
    return entry


def test_the_strictest_threshold_wins_over_the_first_indicator(entry) -> None:
    """A lenient first indicator must not hide a strict sibling."""
    rules = QualityRuleSet(
        indicators={
            FIRST_INDICATOR: IndicatorRule(freshness_max_age_days=400),
            SECOND_INDICATOR: IndicatorRule(freshness_max_age_days=30),
        }
    )

    assert freshness_threshold(entry, rules) == 30


def test_an_indicator_without_a_threshold_cannot_silence_one_that_has_it(entry) -> None:
    """``None`` means "no policy here", not "zero days"."""
    rules = QualityRuleSet(
        indicators={
            FIRST_INDICATOR: IndicatorRule(freshness_max_age_days=None),
            SECOND_INDICATOR: IndicatorRule(freshness_max_age_days=30),
        }
    )

    assert freshness_threshold(entry, rules) == 30


def test_no_thresholds_at_all_is_no_threshold(entry) -> None:
    """Not zero, which would mark every pipeline stale."""
    rules = QualityRuleSet(
        defaults=IndicatorRule(freshness_max_age_days=None),
        indicators={},
    )

    assert freshness_threshold(entry, rules) is None


def test_the_status_summary_uses_the_strictest_threshold(entry, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """``build_pipeline_summaries`` must use the strictest threshold across all indicators.

    Test that /api/v1/status applies the strictest threshold across all
    indicators, not just indicators[0]. A 60-day-old observation is stale under
    the strict (30-day) threshold but not under the lenient (400-day) one; this
    tests that the function uses the strict rule.
    """
    from reim.services import status

    # Mock get_source_by_key to return a mock DataSource with an id
    class MockDataSource:
        def __init__(self):
            self.id = uuid.uuid4()

    mock_source = MockDataSource()
    monkeypatch.setattr(status, "get_source_by_key", lambda _session, _key: mock_source)

    # Mock latest_period_end to return a date 60 days ago
    # (between the 30-day strict and 400-day lenient thresholds)
    today = datetime.now(UTC).date()
    sixty_days_ago = today - timedelta(days=60)
    monkeypatch.setattr(status, "latest_period_end", lambda _session, _id: sixty_days_ago)

    # Create a catalog with only the test entry
    catalog = SourceCatalog(sources=[entry])

    # Create a rule set with lenient first indicator and strict second
    rules = QualityRuleSet(
        indicators={
            FIRST_INDICATOR: IndicatorRule(freshness_max_age_days=400),
            SECOND_INDICATOR: IndicatorRule(freshness_max_age_days=30),
        }
    )

    # Stub session that doesn't access the database
    class StubSession:
        def scalar(self, _query):  # type: ignore[no-untyped-def]
            return None

    stub_session = StubSession()

    # Call build_pipeline_summaries with injected catalog and rules
    summaries = status.build_pipeline_summaries(stub_session, catalog=catalog, rules=rules)

    # The summary should show the data as stale under the strict 30-day threshold
    # (60 days > 30 days), not under the lenient 400-day one
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.data_age_days == 60
    assert summary.is_stale is True, (
        "Under the strict 30-day threshold, 60-day-old data must be marked stale. "
        "If this fails, build_pipeline_summaries may not be using the strictest "
        "threshold across all indicators."
    )
