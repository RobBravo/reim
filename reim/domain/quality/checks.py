"""Reusable data-quality checks.

Every check is a pure function over a list of :class:`NormalizedObservation`
and returns :class:`QualityResult` objects. Nothing here touches the database,
so checks are cheap to unit-test.

Severity semantics enforced by the runner:

``critical``
    Aborts the load; the transaction is rolled back.
``error``
    Rejects the affected observations; the rest of the batch is still written.
``warning`` / ``info``
    Recorded for observability only.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from itertools import pairwise

from reim.core.constants import (
    FREQUENCY_DAYS,
    CheckSeverity,
    CheckType,
    Frequency,
)
from reim.domain.pipelines.models import NormalizedObservation, QualityResult
from reim.domain.quality.rules import IndicatorRule

CheckList = list[QualityResult]


def _label(obs: NormalizedObservation) -> dict[str, str]:
    return {"indicator_code": obs.indicator_code, "period_label": obs.period.label}


# --------------------------------------------------------------------------
# Dataset-level checks
# --------------------------------------------------------------------------
def check_dataset_not_empty(
    observations: list[NormalizedObservation], rule: IndicatorRule
) -> CheckList:
    """Fail critically when a source returned fewer rows than configured.

    A source that suddenly returns nothing is far more likely to be broken than
    to have genuinely lost its history, so this is a hard stop.
    """
    count = len(observations)
    if count >= rule.min_observations:
        return [
            QualityResult.passed(
                "dataset_not_empty",
                CheckType.COMPLETENESS,
                f"Extracted {count} observation(s)",
                expected_value=f">= {rule.min_observations}",
                actual_value=str(count),
            )
        ]
    return [
        QualityResult.failure(
            "dataset_not_empty",
            CheckType.COMPLETENESS,
            CheckSeverity.CRITICAL,
            f"Source returned {count} observation(s), expected at least {rule.min_observations}",
            expected_value=f">= {rule.min_observations}",
            actual_value=str(count),
        )
    ]


def check_no_duplicate_periods(
    observations: list[NormalizedObservation], _rule: IndicatorRule
) -> CheckList:
    """Fail critically when the same natural key appears twice in one batch.

    The database would reject the second row anyway; catching it here produces a
    far more useful error message than a constraint violation.
    """
    counts = Counter(obs.natural_key for obs in observations)
    duplicates = sorted(f"{key[1]}@{key[3]}" for key, n in counts.items() if n > 1)
    if not duplicates:
        return [
            QualityResult.passed(
                "no_duplicate_periods",
                CheckType.UNIQUENESS,
                "No duplicated natural keys in batch",
                actual_value="0",
            )
        ]
    return [
        QualityResult.failure(
            "no_duplicate_periods",
            CheckType.UNIQUENESS,
            CheckSeverity.CRITICAL,
            f"Batch contains {len(duplicates)} duplicated natural key(s): "
            f"{', '.join(duplicates[:5])}",
            expected_value="0",
            actual_value=str(len(duplicates)),
            details={"duplicates": duplicates[:50]},
        )
    ]


def check_referential_consistency(
    observations: list[NormalizedObservation], _rule: IndicatorRule
) -> CheckList:
    """Fail critically if a batch mixes countries or sources unexpectedly.

    Each connector owns exactly one source; more than one ``source_key`` in a
    batch means the transform is attributing data to the wrong provenance.
    """
    results: CheckList = []
    sources = {obs.source_key for obs in observations}
    countries = {obs.country_iso3 for obs in observations}

    if len(sources) <= 1:
        results.append(
            QualityResult.passed(
                "single_source_per_batch",
                CheckType.INTEGRITY,
                "All observations share one source key",
                actual_value=next(iter(sources), "-"),
            )
        )
    else:
        results.append(
            QualityResult.failure(
                "single_source_per_batch",
                CheckType.INTEGRITY,
                CheckSeverity.CRITICAL,
                f"Batch mixes {len(sources)} source keys: {', '.join(sorted(sources))}",
                expected_value="1",
                actual_value=str(len(sources)),
            )
        )

    results.append(
        QualityResult.passed(
            "country_attribution",
            CheckType.INTEGRITY,
            f"Observations attributed to {', '.join(sorted(countries)) or '-'}",
            actual_value=str(len(countries)),
        )
    )
    return results


def check_expected_frequency(
    observations: list[NormalizedObservation],
    _rule: IndicatorRule,
    expected: Frequency,
) -> CheckList:
    """Warn when a period's length does not match the declared frequency."""
    mismatches = [obs for obs in observations if obs.period.frequency is not expected]
    if not mismatches:
        return [
            QualityResult.passed(
                "expected_frequency",
                CheckType.CONSISTENCY,
                f"All periods are {expected.value}",
                expected_value=expected.value,
            )
        ]
    return [
        QualityResult.failure(
            "expected_frequency",
            CheckType.CONSISTENCY,
            CheckSeverity.WARNING,
            f"{len(mismatches)} observation(s) do not match the declared "
            f"{expected.value} frequency",
            expected_value=expected.value,
            actual_value=", ".join(sorted({o.period.frequency.value for o in mismatches})),
        )
    ]


def check_freshness(
    observations: list[NormalizedObservation],
    rule: IndicatorRule,
    *,
    today: date | None = None,
) -> CheckList:
    """Report how old the newest period in the batch is."""
    if not observations:
        return [
            QualityResult.skipped("freshness", CheckType.TIMELINESS, "No observations to assess")
        ]
    if rule.freshness_max_age_days is None:
        return [
            QualityResult.skipped(
                "freshness", CheckType.TIMELINESS, "No freshness threshold configured"
            )
        ]

    reference = today or datetime.now(UTC).date()
    newest = max(obs.period.end for obs in observations)
    age_days = (reference - newest).days

    if age_days <= rule.freshness_max_age_days:
        return [
            QualityResult.passed(
                "freshness",
                CheckType.TIMELINESS,
                f"Newest period ends {newest.isoformat()} ({age_days} day(s) old)",
                expected_value=f"<= {rule.freshness_max_age_days} days",
                actual_value=str(age_days),
            )
        ]
    return [
        QualityResult.failure(
            "freshness",
            CheckType.TIMELINESS,
            rule.freshness_severity,
            f"Newest period ends {newest.isoformat()}, {age_days} day(s) old",
            expected_value=f"<= {rule.freshness_max_age_days} days",
            actual_value=str(age_days),
        )
    ]


def check_temporal_monotonicity(
    observations: list[NormalizedObservation], rule: IndicatorRule
) -> CheckList:
    """Verify a series that must never decrease actually never decreases."""
    if not rule.monotonic_increasing:
        return [
            QualityResult.skipped(
                "temporal_monotonicity",
                CheckType.CONSISTENCY,
                "Series is not declared monotonic",
            )
        ]

    ordered = sorted(
        (o for o in observations if o.value_numeric is not None),
        key=lambda o: o.period.start,
    )
    breaches = [
        (previous, current)
        for previous, current in pairwise(ordered)
        if current.value_numeric < previous.value_numeric  # type: ignore[operator]
    ]
    if not breaches:
        return [
            QualityResult.passed(
                "temporal_monotonicity",
                CheckType.CONSISTENCY,
                "Series is non-decreasing",
            )
        ]
    first_prev, first_cur = breaches[0]
    return [
        QualityResult.failure(
            "temporal_monotonicity",
            CheckType.CONSISTENCY,
            CheckSeverity.WARNING,
            f"{len(breaches)} decrease(s) in a series declared monotonic, "
            f"first at {first_cur.period.label}",
            expected_value=f">= {first_prev.value_numeric}",
            actual_value=str(first_cur.value_numeric),
            **_label(first_cur),
        )
    ]


def check_period_change(
    observations: list[NormalizedObservation], rule: IndicatorRule
) -> CheckList:
    """Flag anomalous percentage jumps between consecutive periods."""
    if rule.max_period_change_pct is None:
        return [
            QualityResult.skipped(
                "period_change", CheckType.ACCURACY, "No change threshold configured"
            )
        ]

    ordered = sorted(
        (o for o in observations if o.value_numeric is not None),
        key=lambda o: o.period.start,
    )
    results: CheckList = []
    for previous, current in pairwise(ordered):
        prior = previous.value_numeric
        assert prior is not None and current.value_numeric is not None
        if prior == 0:
            continue
        change_pct = abs((current.value_numeric - prior) / prior) * Decimal(100)
        if change_pct > rule.max_period_change_pct:
            results.append(
                QualityResult.failure(
                    "period_change",
                    CheckType.ACCURACY,
                    rule.change_severity,
                    f"{current.period.label} changed {change_pct:.2f}% versus "
                    f"{previous.period.label}",
                    expected_value=f"<= {rule.max_period_change_pct}%",
                    actual_value=f"{change_pct:.2f}%",
                    observation_index=observations.index(current),
                    **_label(current),
                )
            )
    if not results:
        results.append(
            QualityResult.passed(
                "period_change",
                CheckType.ACCURACY,
                f"All period-over-period changes within {rule.max_period_change_pct}%",
            )
        )
    return results


# --------------------------------------------------------------------------
# Per-observation checks
# --------------------------------------------------------------------------
def check_values_present(
    observations: list[NormalizedObservation], _rule: IndicatorRule
) -> CheckList:
    """Reject observations that carry neither a numeric nor a textual value.

    Missing upstream values are never imputed — they are simply not stored.
    """
    results: CheckList = []
    for index, obs in enumerate(observations):
        if obs.value_numeric is None and not obs.value_text:
            results.append(
                QualityResult.failure(
                    "value_present",
                    CheckType.COMPLETENESS,
                    CheckSeverity.ERROR,
                    f"Observation {obs.period.label} has no value",
                    expected_value="non-null",
                    actual_value="null",
                    observation_index=index,
                    **_label(obs),
                )
            )
    if not results:
        results.append(
            QualityResult.passed(
                "value_present", CheckType.COMPLETENESS, "All observations carry a value"
            )
        )
    return results


def check_values_numeric(
    observations: list[NormalizedObservation], _rule: IndicatorRule
) -> CheckList:
    """Reject values that are not finite decimals."""
    results: CheckList = []
    for index, obs in enumerate(observations):
        value = obs.value_numeric
        if value is None:
            continue
        try:
            is_finite = value.is_finite()
        except (InvalidOperation, AttributeError):  # pragma: no cover - defensive
            is_finite = False
        if not is_finite:
            results.append(
                QualityResult.failure(
                    "value_numeric_finite",
                    CheckType.VALIDITY,
                    CheckSeverity.ERROR,
                    f"Observation {obs.period.label} has a non-finite value",
                    expected_value="finite decimal",
                    actual_value=str(value),
                    observation_index=index,
                    **_label(obs),
                )
            )
    if not results:
        results.append(
            QualityResult.passed(
                "value_numeric_finite", CheckType.VALIDITY, "All numeric values are finite"
            )
        )
    return results


def check_value_range(observations: list[NormalizedObservation], rule: IndicatorRule) -> CheckList:
    """Enforce the configured bounds and sign constraints."""
    results: CheckList = []
    for index, obs in enumerate(observations):
        value = obs.value_numeric
        if value is None:
            continue
        problem: str | None = None
        expected: str | None = None
        if rule.min_value is not None and value < rule.min_value:
            problem, expected = "below the configured minimum", f">= {rule.min_value}"
        elif rule.max_value is not None and value > rule.max_value:
            problem, expected = "above the configured maximum", f"<= {rule.max_value}"
        elif not rule.allow_negative and value < 0:
            problem, expected = "negative in a non-negative series", ">= 0"
        elif not rule.allow_zero and value == 0:
            problem, expected = "zero in a series that excludes zero", "!= 0"

        if problem:
            results.append(
                QualityResult.failure(
                    "value_range",
                    CheckType.VALIDITY,
                    rule.range_severity,
                    f"Observation {obs.period.label} is {problem}",
                    expected_value=expected,
                    actual_value=str(value),
                    observation_index=index,
                    **_label(obs),
                )
            )
    if not results:
        results.append(
            QualityResult.passed(
                "value_range", CheckType.VALIDITY, "All values within configured bounds"
            )
        )
    return results


def check_period_validity(
    observations: list[NormalizedObservation],
    rule: IndicatorRule,
    *,
    today: date | None = None,
) -> CheckList:
    """Reject inverted periods and unjustified future periods."""
    reference = today or datetime.now(UTC).date()
    horizon = reference + timedelta(days=rule.max_future_days)
    results: CheckList = []

    for index, obs in enumerate(observations):
        period = obs.period
        if period.end < period.start:
            results.append(
                QualityResult.failure(
                    "period_range",
                    CheckType.VALIDITY,
                    CheckSeverity.CRITICAL,
                    f"Period {period.label} ends before it starts",
                    expected_value="end >= start",
                    actual_value=f"{period.start} .. {period.end}",
                    observation_index=index,
                    **_label(obs),
                )
            )
        elif period.end > horizon:
            results.append(
                QualityResult.failure(
                    "period_not_future",
                    CheckType.VALIDITY,
                    CheckSeverity.ERROR,
                    f"Period {period.label} ends {period.end.isoformat()}, beyond the "
                    f"allowed horizon {horizon.isoformat()}",
                    expected_value=f"<= {horizon.isoformat()}",
                    actual_value=period.end.isoformat(),
                    observation_index=index,
                    **_label(obs),
                )
            )
    if not results:
        results.append(
            QualityResult.passed(
                "period_validity", CheckType.VALIDITY, "All periods are well-formed and not future"
            )
        )
    return results


def check_period_length_matches_frequency(
    observations: list[NormalizedObservation],
    _rule: IndicatorRule,
    expected: Frequency,
) -> CheckList:
    """Warn when a period's day count is implausible for its frequency."""
    limit = FREQUENCY_DAYS[expected]
    offenders = [obs for obs in observations if obs.period.days > limit]
    if not offenders:
        return [
            QualityResult.passed(
                "period_length",
                CheckType.CONSISTENCY,
                f"All periods are at most {limit} days long",
                expected_value=f"<= {limit} days",
            )
        ]
    worst = max(offenders, key=lambda o: o.period.days)
    return [
        QualityResult.failure(
            "period_length",
            CheckType.CONSISTENCY,
            CheckSeverity.WARNING,
            f"{len(offenders)} period(s) longer than the {expected.value} nominal length",
            expected_value=f"<= {limit} days",
            actual_value=str(worst.period.days),
            **_label(worst),
        )
    ]


def run_standard_checks(
    observations: list[NormalizedObservation],
    rule: IndicatorRule,
    expected_frequency: Frequency,
    *,
    today: date | None = None,
) -> CheckList:
    """Run the full standard battery against a transformed batch.

    Connectors add their own source-specific checks on top via
    :meth:`BaseConnector.validate`.
    """
    results: CheckList = []
    results += check_dataset_not_empty(observations, rule)
    results += check_no_duplicate_periods(observations, rule)
    results += check_referential_consistency(observations, rule)
    results += check_values_present(observations, rule)
    results += check_values_numeric(observations, rule)
    results += check_value_range(observations, rule)
    results += check_period_validity(observations, rule, today=today)
    results += check_expected_frequency(observations, rule, expected_frequency)
    results += check_period_length_matches_frequency(observations, rule, expected_frequency)
    results += check_period_change(observations, rule)
    results += check_temporal_monotonicity(observations, rule)
    results += check_freshness(observations, rule, today=today)
    return results
