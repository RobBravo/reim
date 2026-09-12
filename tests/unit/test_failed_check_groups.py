"""Ordering of the failed-check aggregate, without a database.

The SQL groups; Python orders. The reader's first question is what is most
broken, so severity leads, then how often it failed, then the name as a
tie-break so the page is stable between renders of identical data.
"""

from __future__ import annotations

from datetime import UTC, datetime

from reim.core.constants import CheckSeverity, CheckType
from reim.repositories.pipeline_runs import order_failed_check_groups
from reim.schemas.pipelines import FailedCheckGroup


def _group(name: str, severity: CheckSeverity, failures: int) -> FailedCheckGroup:
    return FailedCheckGroup(
        check_name=name,
        check_type=CheckType.COMPLETENESS,
        severity=severity,
        failures=failures,
        last_failed_at=datetime(2026, 9, 12, tzinfo=UTC),
        pipeline_keys=["worldbank_ni_cpi_inflation"],
    )


def test_the_most_severe_group_comes_first() -> None:
    groups = [
        _group("a", CheckSeverity.INFO, 99),
        _group("b", CheckSeverity.CRITICAL, 1),
        _group("c", CheckSeverity.WARNING, 50),
    ]

    ordered = order_failed_check_groups(groups)

    assert [group.check_name for group in ordered] == ["b", "c", "a"]


def test_within_a_severity_the_most_frequent_comes_first() -> None:
    groups = [
        _group("rare", CheckSeverity.ERROR, 2),
        _group("common", CheckSeverity.ERROR, 40),
    ]

    ordered = order_failed_check_groups(groups)

    assert [group.check_name for group in ordered] == ["common", "rare"]


def test_ties_break_on_name_so_the_page_is_stable() -> None:
    groups = [
        _group("zeta", CheckSeverity.ERROR, 3),
        _group("alpha", CheckSeverity.ERROR, 3),
    ]

    ordered = order_failed_check_groups(groups)

    assert [group.check_name for group in ordered] == ["alpha", "zeta"]
