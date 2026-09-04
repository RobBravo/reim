"""Quality checks and the rule configuration."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from reim.core.constants import CheckSeverity, CheckStatus, Frequency
from reim.core.exceptions import ConfigurationError
from reim.domain.quality.checks import (
    check_dataset_not_empty,
    check_expected_frequency,
    check_freshness,
    check_no_duplicate_periods,
    check_period_change,
    check_period_validity,
    check_referential_consistency,
    check_temporal_monotonicity,
    check_value_range,
    check_values_numeric,
    check_values_present,
    run_standard_checks,
)
from reim.domain.quality.rules import IndicatorRule, QualityRuleSet, load_quality_rules
from tests.conftest import REPO_ROOT


def _failed(results, name):  # type: ignore[no-untyped-def]
    return [r for r in results if r.check_name == name and r.status is CheckStatus.FAILED]


# --------------------------------------------------------------------------
# Completeness / uniqueness
# --------------------------------------------------------------------------
def test_empty_dataset_fails_critically(permissive_rule: IndicatorRule) -> None:
    """A source that returns nothing is treated as broken, not as empty history."""
    results = check_dataset_not_empty([], permissive_rule)
    assert results[0].status is CheckStatus.FAILED
    assert results[0].severity is CheckSeverity.CRITICAL


def test_dataset_meeting_the_minimum_passes(make_observation, permissive_rule) -> None:  # type: ignore[no-untyped-def]
    results = check_dataset_not_empty([make_observation()], permissive_rule)
    assert results[0].status is CheckStatus.PASSED


def test_min_observations_is_configurable(make_observation) -> None:  # type: ignore[no-untyped-def]
    rule = IndicatorRule(min_observations=5)
    assert check_dataset_not_empty([make_observation()], rule)[0].failed


def test_duplicate_natural_keys_fail_critically(make_observation, permissive_rule) -> None:  # type: ignore[no-untyped-def]
    batch = [make_observation("2024", "1"), make_observation("2024", "2")]
    results = check_no_duplicate_periods(batch, permissive_rule)
    assert results[0].severity is CheckSeverity.CRITICAL
    assert results[0].failed


def test_distinct_periods_pass(make_observation, permissive_rule) -> None:  # type: ignore[no-untyped-def]
    batch = [make_observation("2023"), make_observation("2024")]
    assert check_no_duplicate_periods(batch, permissive_rule)[0].status is CheckStatus.PASSED


def test_missing_values_are_rejected_not_imputed(make_observation, permissive_rule) -> None:  # type: ignore[no-untyped-def]
    """REIM never fills a gap; the observation is simply rejected."""
    batch = [make_observation("2024", None)]
    failures = _failed(check_values_present(batch, permissive_rule), "value_present")
    assert failures and failures[0].severity is CheckSeverity.ERROR
    assert failures[0].observation_index == 0


def test_text_only_values_are_accepted(make_observation, permissive_rule) -> None:  # type: ignore[no-untyped-def]
    batch = [make_observation("2024", None, value_text="not available")]
    assert not _failed(check_values_present(batch, permissive_rule), "value_present")


def test_non_finite_values_are_rejected(make_observation, permissive_rule) -> None:  # type: ignore[no-untyped-def]
    observation = make_observation("2024", "1")
    observation.value_numeric = Decimal("NaN")
    failures = _failed(check_values_numeric([observation], permissive_rule), "value_numeric_finite")
    assert failures and failures[0].severity is CheckSeverity.ERROR


# --------------------------------------------------------------------------
# Ranges
# --------------------------------------------------------------------------
def test_value_below_minimum_is_rejected(make_observation) -> None:  # type: ignore[no-untyped-def]
    rule = IndicatorRule(min_value=Decimal("0"))
    failures = _failed(check_value_range([make_observation("2024", "-1")], rule), "value_range")
    assert failures and failures[0].observation_index == 0


def test_value_above_maximum_is_rejected(make_observation) -> None:  # type: ignore[no-untyped-def]
    rule = IndicatorRule(max_value=Decimal("100"))
    assert _failed(check_value_range([make_observation("2024", "101")], rule), "value_range")


def test_value_inside_bounds_passes(make_observation) -> None:  # type: ignore[no-untyped-def]
    rule = IndicatorRule(min_value=Decimal("0"), max_value=Decimal("100"))
    assert not _failed(check_value_range([make_observation("2024", "50")], rule), "value_range")


def test_tiny_positive_values_pass_a_zero_lower_bound(make_observation) -> None:  # type: ignore[no-untyped-def]
    """Pre-redenomination exchange rates (~2e-9) are legitimate figures."""
    rule = IndicatorRule(min_value=Decimal("0"), allow_zero=False, allow_negative=False)
    observation = make_observation("1975", "2.06064418965517E-9")
    assert not _failed(check_value_range([observation], rule), "value_range")


def test_negative_value_rejected_when_disallowed(make_observation) -> None:  # type: ignore[no-untyped-def]
    rule = IndicatorRule(allow_negative=False)
    assert _failed(check_value_range([make_observation("2024", "-5")], rule), "value_range")


def test_zero_rejected_when_disallowed(make_observation) -> None:  # type: ignore[no-untyped-def]
    rule = IndicatorRule(allow_zero=False)
    assert _failed(check_value_range([make_observation("2024", "0")], rule), "value_range")


def test_range_severity_is_configurable(make_observation) -> None:  # type: ignore[no-untyped-def]
    rule = IndicatorRule(max_value=Decimal("1"), range_severity=CheckSeverity.WARNING)
    failures = _failed(check_value_range([make_observation("2024", "5")], rule), "value_range")
    assert failures[0].severity is CheckSeverity.WARNING


# --------------------------------------------------------------------------
# Periods and time
# --------------------------------------------------------------------------
def test_future_period_is_rejected(make_observation, permissive_rule) -> None:  # type: ignore[no-untyped-def]
    results = check_period_validity(
        [make_observation("2030")], permissive_rule, today=date(2026, 8, 4)
    )
    failures = _failed(results, "period_not_future")
    assert failures and failures[0].severity is CheckSeverity.ERROR


def test_future_period_allowed_within_the_configured_horizon(make_observation) -> None:  # type: ignore[no-untyped-def]
    rule = IndicatorRule(max_future_days=400)
    results = check_period_validity([make_observation("2026")], rule, today=date(2026, 8, 4))
    assert not _failed(results, "period_not_future")


def test_current_period_passes(make_observation, permissive_rule) -> None:  # type: ignore[no-untyped-def]
    results = check_period_validity(
        [make_observation("2024")], permissive_rule, today=date(2026, 8, 4)
    )
    assert not _failed(results, "period_not_future")


def test_frequency_mismatch_warns(make_observation, permissive_rule) -> None:  # type: ignore[no-untyped-def]
    batch = [make_observation("2024-03", frequency=Frequency.MONTHLY)]
    failures = _failed(
        check_expected_frequency(batch, permissive_rule, Frequency.ANNUAL), "expected_frequency"
    )
    assert failures and failures[0].severity is CheckSeverity.WARNING


def test_stale_data_is_flagged(make_observation) -> None:  # type: ignore[no-untyped-def]
    rule = IndicatorRule(freshness_max_age_days=30)
    results = check_freshness([make_observation("2020")], rule, today=date(2026, 8, 4))
    assert results[0].failed


def test_fresh_data_passes(make_observation) -> None:  # type: ignore[no-untyped-def]
    rule = IndicatorRule(freshness_max_age_days=800)
    results = check_freshness([make_observation("2025")], rule, today=date(2026, 8, 4))
    assert results[0].status is CheckStatus.PASSED


def test_freshness_is_skipped_without_a_threshold(make_observation, permissive_rule) -> None:  # type: ignore[no-untyped-def]
    results = check_freshness([make_observation("1990")], permissive_rule)
    assert results[0].status is CheckStatus.SKIPPED


def test_one_stale_country_does_not_hide_behind_the_others(make_observation) -> None:
    """The failure this check exists to catch, and could not see before.

    Measuring the newest period of the whole batch means a country that stopped
    publishing years ago stays invisible for as long as any other country is
    current. Belize could have frozen in 2018 and every check would pass.
    """
    rule = IndicatorRule(freshness_max_age_days=600)
    batch = [
        make_observation("2025", country_iso3="NIC"),
        make_observation("2018", country_iso3="BLZ"),
    ]

    results = check_freshness(batch, rule, today=date(2026, 8, 19))

    assert results[0].failed
    assert "BLZ" in results[0].message
    assert "NIC" not in results[0].message


def test_freshness_passes_when_every_country_is_current(make_observation) -> None:
    rule = IndicatorRule(freshness_max_age_days=600)
    batch = [
        make_observation("2025", country_iso3="NIC"),
        make_observation("2025", country_iso3="BLZ"),
    ]

    result = check_freshness(batch, rule, today=date(2026, 8, 19))[0]

    assert result.status is CheckStatus.PASSED
    assert "2" in result.message


def test_freshness_reports_the_stalest_country_not_the_newest(make_observation) -> None:
    """`actual_value` drives the dashboards: it must be the worst age, not the best."""
    rule = IndicatorRule(freshness_max_age_days=100)
    batch = [
        make_observation("2026-06", country_iso3="NIC", frequency=Frequency.MONTHLY),
        make_observation("2026-01", country_iso3="BLZ", frequency=Frequency.MONTHLY),
    ]

    result = check_freshness(batch, rule, today=date(2026, 8, 19))[0]

    assert result.actual_value == "200"


def test_single_country_freshness_is_unchanged(make_observation) -> None:
    """Twelve of REIM's seventeen pipelines run one country; they must not move."""
    rule = IndicatorRule(freshness_max_age_days=30)
    stale = check_freshness([make_observation("2020")], rule, today=date(2026, 8, 4))[0]
    fresh = check_freshness([make_observation("2025")], rule, today=date(2026, 1, 4))[0]

    assert stale.failed
    assert stale.actual_value == "2042"
    assert fresh.status is CheckStatus.PASSED
    assert fresh.actual_value == "4"


def test_monotonic_series_breach_warns(make_observation) -> None:  # type: ignore[no-untyped-def]
    rule = IndicatorRule(monotonic_increasing=True)
    batch = [make_observation("2023", "100"), make_observation("2024", "90")]
    results = check_temporal_monotonicity(batch, rule)
    assert results[0].failed and results[0].severity is CheckSeverity.WARNING


def test_monotonic_check_skipped_when_not_declared(make_observation, permissive_rule) -> None:  # type: ignore[no-untyped-def]
    batch = [make_observation("2023", "100"), make_observation("2024", "90")]
    assert check_temporal_monotonicity(batch, permissive_rule)[0].status is CheckStatus.SKIPPED


def test_anomalous_period_change_is_flagged(make_observation) -> None:  # type: ignore[no-untyped-def]
    rule = IndicatorRule(max_period_change_pct=Decimal("10"))
    batch = [make_observation("2023", "100"), make_observation("2024", "150")]
    failures = _failed(check_period_change(batch, rule), "period_change")
    assert failures and failures[0].actual_value == "50.00%"


def test_small_period_change_passes(make_observation) -> None:  # type: ignore[no-untyped-def]
    rule = IndicatorRule(max_period_change_pct=Decimal("10"))
    batch = [make_observation("2023", "100"), make_observation("2024", "105")]
    assert not _failed(check_period_change(batch, rule), "period_change")


def test_period_change_skipped_without_a_threshold(make_observation, permissive_rule) -> None:  # type: ignore[no-untyped-def]
    batch = [make_observation("2023", "1"), make_observation("2024", "1000")]
    assert check_period_change(batch, permissive_rule)[0].status is CheckStatus.SKIPPED


def test_period_change_ignores_non_adjacent_periods(make_observation) -> None:
    """Regression: INIDE has no monthly CPI for 2008-2010.

    Comparing 2011-01 straight against 2007-12 reported a bogus "25.25% monthly
    change". Only genuinely consecutive periods may be compared.
    """
    rule = IndicatorRule(max_period_change_pct=Decimal("10"))
    batch = [
        make_observation("2007-12", "115", frequency=Frequency.MONTHLY),
        make_observation("2011-01", "144", frequency=Frequency.MONTHLY),
    ]
    assert not _failed(check_period_change(batch, rule), "period_change")


def test_period_change_still_compares_adjacent_periods(make_observation) -> None:
    """The gap guard must not disable the check for contiguous months."""
    rule = IndicatorRule(max_period_change_pct=Decimal("10"))
    batch = [
        make_observation("2026-01", "100", frequency=Frequency.MONTHLY),
        make_observation("2026-02", "150", frequency=Frequency.MONTHLY),
    ]
    failures = _failed(check_period_change(batch, rule), "period_change")
    assert failures and failures[0].actual_value == "50.00%"


def test_period_change_adjacency_holds_across_frequencies(make_observation) -> None:
    """Consecutive annual periods are one day apart, just like months."""
    rule = IndicatorRule(max_period_change_pct=Decimal("10"))
    adjacent = [make_observation("2023", "100"), make_observation("2024", "150")]
    assert _failed(check_period_change(adjacent, rule), "period_change")

    with_hole = [make_observation("2020", "100"), make_observation("2024", "150")]
    assert not _failed(check_period_change(with_hole, rule), "period_change")


def test_period_change_reports_how_many_comparisons_it_skipped(make_observation) -> None:
    rule = IndicatorRule(max_period_change_pct=Decimal("10"))
    batch = [make_observation("2020", "100"), make_observation("2024", "101")]
    result = check_period_change(batch, rule)[0]
    assert result.details["comparisons_skipped_across_gaps"] == 1


def test_period_change_ignores_a_zero_baseline(make_observation) -> None:  # type: ignore[no-untyped-def]
    """Dividing by a zero previous value must not blow up."""
    rule = IndicatorRule(max_period_change_pct=Decimal("10"))
    batch = [make_observation("2023", "0"), make_observation("2024", "5")]
    assert not _failed(check_period_change(batch, rule), "period_change")


# --------------------------------------------------------------------------
# One batch, many countries
# --------------------------------------------------------------------------
# A multi-country batch holds one series per country, not one long series.
# Ordering such a batch by period alone interleaves them, and the pair that
# straddles a period boundary then compares two different countries. CEPALSTAT
# is where this first showed: 138 warnings on every run, every one of them the
# last country of one year against the first country of the next, while the
# worst real year-on-year move in the data was 22.95%.
def test_period_change_never_compares_two_countries(make_observation) -> None:
    """Each country is flat; only a cross-country pair could look like a jump."""
    rule = IndicatorRule(max_period_change_pct=Decimal("10"))
    batch = [
        make_observation("2023", "100", country_iso3="NIC"),
        make_observation("2023", "1000", country_iso3="PAN"),
        make_observation("2024", "100", country_iso3="NIC"),
        make_observation("2024", "1000", country_iso3="PAN"),
    ]

    assert not _failed(check_period_change(batch, rule), "period_change")


def test_period_change_still_flags_a_jump_inside_one_country(make_observation) -> None:
    """Grouping by country must not blunt the check it exists to run."""
    rule = IndicatorRule(max_period_change_pct=Decimal("10"))
    batch = [
        make_observation("2023", "100", country_iso3="NIC"),
        make_observation("2023", "1000", country_iso3="PAN"),
        make_observation("2024", "150", country_iso3="NIC"),
        make_observation("2024", "1000", country_iso3="PAN"),
    ]

    failures = _failed(check_period_change(batch, rule), "period_change")

    assert len(failures) == 1
    assert failures[0].actual_value == "50.00%"
    assert batch[failures[0].observation_index].country_iso3 == "NIC"


def test_period_change_counts_gaps_per_country(make_observation) -> None:
    """Two countries each missing 2021-2023 is two skipped comparisons, not one."""
    rule = IndicatorRule(max_period_change_pct=Decimal("10"))
    batch = [
        make_observation("2020", "100", country_iso3="NIC"),
        make_observation("2020", "100", country_iso3="PAN"),
        make_observation("2024", "101", country_iso3="NIC"),
        make_observation("2024", "101", country_iso3="PAN"),
    ]

    result = check_period_change(batch, rule)[0]

    assert result.details["comparisons_skipped_across_gaps"] == 2


def test_monotonicity_never_compares_two_countries(make_observation) -> None:
    """Both countries rise; only a cross-country pair could look like a fall."""
    rule = IndicatorRule(monotonic_increasing=True)
    batch = [
        make_observation("2023", "100", country_iso3="NIC"),
        make_observation("2023", "1000", country_iso3="PAN"),
        make_observation("2024", "110", country_iso3="NIC"),
        make_observation("2024", "1100", country_iso3="PAN"),
    ]

    assert not _failed(check_temporal_monotonicity(batch, rule), "temporal_monotonicity")


def test_monotonicity_still_flags_a_fall_inside_one_country(make_observation) -> None:
    rule = IndicatorRule(monotonic_increasing=True)
    batch = [
        make_observation("2023", "100", country_iso3="NIC"),
        make_observation("2023", "1000", country_iso3="PAN"),
        make_observation("2024", "90", country_iso3="NIC"),
        make_observation("2024", "1100", country_iso3="PAN"),
    ]

    failures = _failed(check_temporal_monotonicity(batch, rule), "temporal_monotonicity")

    assert len(failures) == 1
    assert failures[0].expected_value == ">= 100"
    assert failures[0].actual_value == "90"


# --------------------------------------------------------------------------
# Integrity
# --------------------------------------------------------------------------
def test_mixed_sources_in_one_batch_fail_critically(make_observation, permissive_rule) -> None:  # type: ignore[no-untyped-def]
    batch = [
        make_observation("2023", source_key="worldbank_ni_cpi_inflation"),
        make_observation("2024", source_key="bcn_exchange_rate"),
    ]
    failures = _failed(
        check_referential_consistency(batch, permissive_rule), "single_source_per_batch"
    )
    assert failures and failures[0].severity is CheckSeverity.CRITICAL


def test_single_source_batch_passes(make_observation, permissive_rule) -> None:  # type: ignore[no-untyped-def]
    batch = [make_observation("2023"), make_observation("2024")]
    assert not _failed(
        check_referential_consistency(batch, permissive_rule), "single_source_per_batch"
    )


# --------------------------------------------------------------------------
# Standard battery
# --------------------------------------------------------------------------
def test_standard_battery_runs_every_check(make_observation, permissive_rule) -> None:  # type: ignore[no-untyped-def]
    batch = [make_observation("2023"), make_observation("2024")]
    names = {r.check_name for r in run_standard_checks(batch, permissive_rule, Frequency.ANNUAL)}
    assert {
        "dataset_not_empty",
        "no_duplicate_periods",
        "single_source_per_batch",
        "value_present",
        "value_numeric_finite",
        "value_range",
        "period_validity",
        "expected_frequency",
        "period_length",
        "period_change",
        "temporal_monotonicity",
        "freshness",
    } <= names


def test_clean_batch_produces_no_failures(make_observation, permissive_rule) -> None:  # type: ignore[no-untyped-def]
    batch = [make_observation("2023"), make_observation("2024")]
    results = run_standard_checks(batch, permissive_rule, Frequency.ANNUAL, today=date(2026, 8, 4))
    assert [r for r in results if r.failed] == []


# --------------------------------------------------------------------------
# Rule configuration
# --------------------------------------------------------------------------
def test_repository_rules_load(quality_rules: QualityRuleSet) -> None:
    assert quality_rules.indicators


def test_repository_rules_do_not_reject_historical_exchange_rates(
    quality_rules: QualityRuleSet,
) -> None:
    """Regression: min_value=1 once rejected 31 real pre-redenomination figures."""
    rule = quality_rules.for_indicator("ni_exchange_rate_official_annual_avg")
    assert rule.min_value is not None
    assert rule.min_value <= Decimal("2.06064418965517E-9")


def test_unknown_indicator_falls_back_to_defaults(quality_rules: QualityRuleSet) -> None:
    assert quality_rules.for_indicator("not_an_indicator") is quality_rules.defaults


def test_missing_rules_file_yields_defaults(tmp_path: Path) -> None:
    assert load_quality_rules(tmp_path / "absent.yml").indicators == {}


def test_rules_for_unknown_indicator_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "rules.yml"
    path.write_text(yaml.safe_dump({"indicators": {"nope": {"min_value": 1}}}), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="unknown indicator"):
        load_quality_rules(path)


def test_malformed_rules_yaml_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "rules.yml"
    path.write_text("indicators: [\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="not valid YAML"):
        load_quality_rules(path)


def test_inverted_bounds_are_rejected() -> None:
    with pytest.raises(ValueError, match="exceeds max_value"):
        IndicatorRule(min_value=Decimal("10"), max_value=Decimal("1"))


def test_monthly_trade_indicators_have_their_own_rules(
    quality_rules: QualityRuleSet,
) -> None:
    """Every monthly trade series needs bounds of its own before ingestion.

    Asserted against `.indicators`, not `for_indicator()`: the latter falls
    back to `defaults` for an unknown code and would pass even with no rule
    set at all.
    """
    for code in (
        "exports_goods_monthly",
        "imports_goods_monthly",
        "trade_balance_goods_monthly",
    ):
        assert code in quality_rules.indicators, f"{code} has no rule set of its own"


def test_trade_balance_may_be_negative(quality_rules: QualityRuleSet) -> None:
    """Nicaragua ran a merchandise deficit in 433 of 436 published months."""
    balance = quality_rules.indicators["trade_balance_goods_monthly"]

    assert balance.allow_negative is True
    assert balance.min_value is None


def test_guatemala_exchange_rate_indicators_have_their_own_rules(
    quality_rules: QualityRuleSet,
) -> None:
    """Both sides of the published pair need bounds before ingestion."""
    for code in (
        "gt_exchange_rate_official_daily_buy",
        "gt_exchange_rate_official_daily_sell",
    ):
        assert code in quality_rules.indicators, f"{code} has no rule set of its own"


def test_the_quetzal_rate_has_no_ceiling(quality_rules: QualityRuleSet) -> None:
    """It ran 3.41 to 8.39 over 36 years; a narrow band would reject real history."""
    rule = quality_rules.indicators["gt_exchange_rate_official_daily_sell"]

    assert rule.allow_negative is False
    assert rule.max_value is None
    assert rule.max_period_change_pct is None


def test_services_trade_indicators_have_their_own_rules(quality_rules: QualityRuleSet) -> None:
    for code in (
        "exports_services_quarterly",
        "imports_services_quarterly",
        "trade_balance_services_quarterly",
    ):
        assert code in quality_rules.indicators, f"{code} has no rule set of its own"


def test_the_services_balance_may_be_negative(quality_rules: QualityRuleSet) -> None:
    """99 of 414 quarters are deficits; the sign is the figure's point."""
    rule = quality_rules.indicators["trade_balance_services_quarterly"]

    assert rule.allow_negative is True


def test_services_exports_may_not_be_negative(quality_rules: QualityRuleSet) -> None:
    rule = quality_rules.indicators["exports_services_quarterly"]

    assert rule.allow_negative is False
    assert rule.max_value is None


def test_services_indicators_have_a_real_min_observations_floor(
    quality_rules: QualityRuleSet,
) -> None:
    """SIECA returns 414 cells per flow on every run; the default floor of 1
    would let a run truncated to a single quarter pass every SIECA check.
    """
    for code in (
        "exports_services_quarterly",
        "imports_services_quarterly",
        "trade_balance_services_quarterly",
    ):
        rule = quality_rules.indicators[code]
        assert rule.min_observations >= 400, (
            f"{code} min_observations={rule.min_observations} would not catch "
            "a run truncated to far less than the real 414-cell history"
        )


def test_monetary_indicators_have_their_own_rules() -> None:
    rules = load_quality_rules(REPO_ROOT / "sources" / "quality_rules.yml")

    for code, floor in (
        ("money_m1_monthly", 1950),
        ("money_m2_monthly", 1550),
        ("money_m3_monthly", 1680),
    ):
        rule = rules.for_indicator(code)
        assert rule.min_observations == floor
        assert rule.max_period_change_pct == Decimal("60")
        assert rule.freshness_max_age_days == 900


def test_the_monetary_change_ceiling_clears_the_worst_real_move() -> None:
    """Panama's M1 moved 45.93% in November 2006; the source published it."""
    rules = load_quality_rules(REPO_ROOT / "sources" / "quality_rules.yml")

    assert rules.for_indicator("money_m1_monthly").max_period_change_pct > Decimal("45.93")


def test_monetary_aggregates_may_not_be_negative() -> None:
    """A money stock is a stock: negative is a broken feed, not a deficit."""
    rules = load_quality_rules(REPO_ROOT / "sources" / "quality_rules.yml")

    assert not rules.for_indicator("money_m1_monthly").allow_negative
