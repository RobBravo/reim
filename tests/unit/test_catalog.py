"""Source catalog validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from reim.core.constants import Frequency, IndicatorCategory, TlsProfile, ValueType
from reim.core.exceptions import CatalogError, CatalogValidationError
from reim.domain.countries.registry import COUNTRIES, COUNTRIES_BY_ISO2, COUNTRIES_BY_ISO3
from reim.domain.indicators.registry import INDICATORS, INDICATORS_BY_CODE
from reim.domain.quality.rules import QualityRuleSet, load_quality_rules
from reim.domain.sources.catalog import SourceCatalog, SourceEntry, load_catalog
from tests.conftest import REPO_ROOT

VALID_ENTRY: dict[str, Any] = {
    "key": "worldbank_ni_cpi_inflation",
    "name": "Nicaragua consumer price inflation",
    "country": "NI",
    "organization": "WORLDBANK",
    "category": "prices",
    "access_type": "http_api",
    "frequency": "annual",
    "format": "json",
    "base_url": "https://api.worldbank.org/v2",
    "connector": "reim.ingestion.connectors.nicaragua.worldbank_cpi_inflation",
    "indicators": ["ni_cpi_inflation_annual"],
}


def _write(tmp_path: Path, payload: dict[str, Any]) -> Path:
    path = tmp_path / "catalog.yml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def _catalog(**overrides: Any) -> dict[str, Any]:
    return {"version": 1, "sources": [{**VALID_ENTRY, **overrides}]}


# --------------------------------------------------------------------------
# The repository's own catalog
# --------------------------------------------------------------------------
def test_repository_catalog_is_valid(catalog: SourceCatalog) -> None:
    assert len(catalog.sources) >= 1
    assert catalog.version == 1


def test_repository_catalog_has_at_least_three_enabled_sources(catalog: SourceCatalog) -> None:
    """The MVP requires at least three working connectors."""
    assert len(catalog.enabled_sources) >= 3


def test_every_disabled_source_documents_why(catalog: SourceCatalog) -> None:
    for entry in catalog.sources:
        if not entry.enabled:
            assert entry.disabled_reason, f"{entry.key} is disabled without a reason"


def test_no_enabled_source_uses_a_placeholder_host(catalog: SourceCatalog) -> None:
    for entry in catalog.enabled_sources:
        assert "example.invalid" not in str(entry.base_url)


def test_get_returns_the_entry(catalog: SourceCatalog) -> None:
    assert catalog.get("worldbank_ni_cpi_inflation").organization == "WORLDBANK"


def test_get_unknown_key_raises(catalog: SourceCatalog) -> None:
    with pytest.raises(CatalogError, match="not registered"):
        catalog.get("does_not_exist")


# --------------------------------------------------------------------------
# Validation failures
# --------------------------------------------------------------------------
def test_valid_minimal_catalog_loads(tmp_path: Path) -> None:
    loaded = load_catalog(_write(tmp_path, _catalog()))
    assert loaded.sources[0].enabled is True
    assert loaded.sources[0].country_iso2 == "NI"


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(CatalogError, match="not found"):
        load_catalog(tmp_path / "absent.yml")


def test_malformed_yaml_raises(tmp_path: Path) -> None:
    path = tmp_path / "catalog.yml"
    path.write_text("sources: [\n  - key: broken\n", encoding="utf-8")
    with pytest.raises(CatalogError, match="not valid YAML"):
        load_catalog(path)


def test_non_mapping_root_raises(tmp_path: Path) -> None:
    path = tmp_path / "catalog.yml"
    path.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(CatalogValidationError, match="must be a YAML mapping"):
        load_catalog(path)


def test_empty_source_list_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(CatalogValidationError):
        load_catalog(_write(tmp_path, {"version": 1, "sources": []}))


def test_unknown_organization_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(CatalogValidationError, match="unknown organization"):
        load_catalog(_write(tmp_path, _catalog(organization="NOT_REAL")))


def test_unknown_country_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(CatalogValidationError, match="unknown country"):
        load_catalog(_write(tmp_path, _catalog(country="ZZ")))


def test_unknown_indicator_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(CatalogValidationError, match="unknown indicator"):
        load_catalog(_write(tmp_path, _catalog(indicators=["ni_not_an_indicator"])))


def test_duplicate_indicators_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(CatalogValidationError, match="duplicate indicator"):
        load_catalog(_write(tmp_path, _catalog(indicators=["ni_cpi_inflation_annual"] * 2)))


def test_duplicate_source_keys_are_rejected(tmp_path: Path) -> None:
    payload = {"version": 1, "sources": [VALID_ENTRY, dict(VALID_ENTRY)]}
    with pytest.raises(CatalogValidationError, match="duplicate source key"):
        load_catalog(_write(tmp_path, payload))


def test_enabled_source_with_placeholder_host_is_rejected(tmp_path: Path) -> None:
    """example.invalid must never appear on an operational source."""
    with pytest.raises(CatalogValidationError, match="placeholder host"):
        load_catalog(_write(tmp_path, _catalog(base_url="https://example.invalid")))


def test_disabled_source_may_use_a_placeholder_host(tmp_path: Path) -> None:
    loaded = load_catalog(
        _write(
            tmp_path,
            _catalog(
                base_url="https://example.invalid",
                enabled=False,
                disabled_reason="Endpoint not identified yet.",
            ),
        )
    )
    assert loaded.enabled_sources == []


def test_disabled_source_without_a_reason_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(CatalogValidationError, match="disabled_reason"):
        load_catalog(_write(tmp_path, _catalog(enabled=False)))


def test_imf_source_declares_its_non_open_licence(catalog: SourceCatalog) -> None:
    """The IMF is the one source here whose data is not openly licensed."""
    entry = catalog.get("imf_imts_nicaragua")

    assert entry.license == "imf_terms_of_use"
    assert entry.license != "public_official_data"
    assert entry.enabled is True


def test_inide_source_declares_all_nine_cpi_indicators(catalog: SourceCatalog) -> None:
    """One source, one download, nine series: national plus two regions."""
    entry = catalog.get("inide_cpi_monthly")

    assert set(entry.indicators) == {
        "ni_cpi_index_monthly",
        "ni_cpi_inflation_monthly",
        "ni_cpi_inflation_yoy",
        "ni_cpi_index_monthly_managua",
        "ni_cpi_inflation_monthly_managua",
        "ni_cpi_inflation_yoy_managua",
        "ni_cpi_index_monthly_rest_of_country",
        "ni_cpi_inflation_monthly_rest_of_country",
        "ni_cpi_inflation_yoy_rest_of_country",
    }


def test_source_defaults_to_the_modern_tls_profile(tmp_path: Path) -> None:
    loaded = load_catalog(_write(tmp_path, _catalog()))
    entry = loaded.sources[0]
    assert entry.tls_profile is TlsProfile.MODERN
    assert entry.tls_note is None


def test_legacy_tls_profile_without_a_note_is_rejected(tmp_path: Path) -> None:
    """A downgraded handshake must justify itself, like a disabled source must."""
    with pytest.raises(CatalogValidationError, match="tls_note"):
        load_catalog(_write(tmp_path, _catalog(tls_profile="legacy")))


def test_legacy_tls_profile_is_accepted_with_a_note(tmp_path: Path) -> None:
    loaded = load_catalog(
        _write(
            tmp_path,
            _catalog(
                tls_profile="legacy",
                tls_note="Host negotiates TLS 1.0 only; verification stays enforced.",
            ),
        )
    )
    assert loaded.sources[0].tls_profile is TlsProfile.LEGACY


def test_unknown_tls_profile_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(CatalogValidationError):
        load_catalog(_write(tmp_path, _catalog(tls_profile="ancient")))


def test_unknown_field_is_rejected(tmp_path: Path) -> None:
    """A typo in a key must fail loudly instead of being silently ignored."""
    with pytest.raises(CatalogValidationError):
        load_catalog(_write(tmp_path, _catalog(enabledd=True)))


@pytest.mark.parametrize("key", ["Not-Snake-Case", "with spaces", "UPPER", "trailing_"])
def test_malformed_keys_are_rejected(tmp_path: Path, key: str) -> None:
    with pytest.raises(CatalogValidationError):
        load_catalog(_write(tmp_path, _catalog(key=key)))


def test_non_http_base_url_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(CatalogValidationError):
        load_catalog(_write(tmp_path, _catalog(base_url="ftp://files.example.org")))


def test_error_message_names_the_offending_field(tmp_path: Path) -> None:
    with pytest.raises(CatalogValidationError) as exc_info:
        load_catalog(_write(tmp_path, _catalog(frequency="fortnightly")))
    assert "frequency" in str(exc_info.value)


def test_imts_covers_the_six_reporting_countries(catalog: SourceCatalog) -> None:
    """Belize is absent on purpose: it reports nothing to IMTS."""
    imts = {e.key: e.country for e in catalog.sources if e.key.startswith("imf_imts_")}

    assert imts == {
        "imf_imts_nicaragua": "NI",
        "imf_imts_guatemala": "GT",
        "imf_imts_el_salvador": "SV",
        "imf_imts_honduras": "HN",
        "imf_imts_costa_rica": "CR",
        "imf_imts_panama": "PA",
    }


def test_every_imts_entry_declares_the_imf_licence(catalog: SourceCatalog) -> None:
    for entry in catalog.sources:
        if entry.key.startswith("imf_imts_"):
            assert entry.license == "imf_terms_of_use"


def test_seven_countries_are_active() -> None:
    """All seven are active: Belize joined on the strength of CEPALSTAT's
    national accounts, even though it still reports nothing to IMTS."""
    active = {c.iso2 for c in COUNTRIES if c.is_active}

    assert active == {"NI", "GT", "SV", "HN", "CR", "PA", "BZ"}
    assert COUNTRIES_BY_ISO2["BZ"].is_active is True


def test_a_source_may_declare_its_own_user_agent() -> None:
    entry = SourceEntry.model_validate(
        {
            **VALID_ENTRY,
            "user_agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/126.0",
            "user_agent_note": "The host answers 202 with an empty body otherwise.",
        }
    )

    assert entry.user_agent == "Mozilla/5.0 (X11; Linux x86_64) Chrome/126.0"


def test_most_sources_declare_no_user_agent() -> None:
    """The honest default must stay the default."""
    entry = SourceEntry.model_validate(VALID_ENTRY)

    assert entry.user_agent is None


def test_a_custom_user_agent_must_document_itself() -> None:
    """Same rule as tls_profile: an exception that cannot explain itself is a bug."""
    with pytest.raises(ValidationError, match="user_agent_note"):
        SourceEntry.model_validate({**VALID_ENTRY, "user_agent": "Mozilla/5.0"})


def test_the_four_gdp_indicators_are_registered() -> None:
    codes = {
        "gdp_current_usd_annual",
        "gdp_constant_usd_annual",
        "gdp_per_capita_current_usd_annual",
        "gdp_per_capita_constant_usd_annual",
    }
    assert codes <= set(INDICATORS_BY_CODE)
    for code in codes:
        definition = INDICATORS_BY_CODE[code]
        assert definition.category is IndicatorCategory.REAL_SECTOR
        assert definition.frequency is Frequency.ANNUAL
        assert definition.value_type is ValueType.LEVEL


def test_the_constant_price_indicators_name_their_base_year() -> None:
    """The base year lives in a CEPAL footnote, so REIM puts it in the unit."""
    assert INDICATORS_BY_CODE["gdp_constant_usd_annual"].unit == "constant 2018 USD"
    assert (
        INDICATORS_BY_CODE["gdp_per_capita_constant_usd_annual"].unit
        == "constant 2018 USD per person"
    )
    assert INDICATORS_BY_CODE["gdp_current_usd_annual"].unit == "current USD"
    assert INDICATORS_BY_CODE["gdp_per_capita_current_usd_annual"].unit == "current USD per person"


def test_belize_is_active() -> None:
    """CEPALSTAT gives Belize its first data; the IMF dataflow held none."""
    assert COUNTRIES_BY_ISO3["BLZ"].is_active is True
    assert all(country.is_active for country in COUNTRIES)


def test_every_gdp_indicator_has_a_quality_rule(quality_rules: QualityRuleSet) -> None:
    for code in (
        "gdp_current_usd_annual",
        "gdp_constant_usd_annual",
        "gdp_per_capita_current_usd_annual",
        "gdp_per_capita_constant_usd_annual",
    ):
        rule = quality_rules.for_indicator(code)
        assert rule is not quality_rules.defaults, f"{code} fell through to the defaults"
        assert rule.min_observations == 240
        assert rule.max_period_change_pct == 40
        assert rule.allow_negative is False
        assert rule.allow_zero is False


def test_the_three_monetary_indicators_are_registered() -> None:
    """The first use of the monetary category, declared since v0.1.0."""
    codes = {i.code: i for i in INDICATORS}

    for code in ("money_m1_monthly", "money_m2_monthly", "money_m3_monthly"):
        assert codes[code].category is IndicatorCategory.MONETARY
        assert codes[code].frequency is Frequency.MONTHLY
        assert codes[code].value_type is ValueType.LEVEL


def test_the_monetary_indicators_carry_no_country_prefix() -> None:
    """Decision C8: regional sources drop the prefix, as SIECA and GDP did."""
    codes = {i.code for i in INDICATORS}

    assert {"money_m1_monthly", "money_m2_monthly", "money_m3_monthly"} <= codes
    assert not any(code.startswith(("ni_money", "gt_money")) for code in codes)


def test_the_monetary_indicator_unit_names_no_single_currency() -> None:
    """Seven countries, six currencies: the code cannot claim one of them."""
    codes = {i.code: i for i in INDICATORS}

    for code in ("money_m1_monthly", "money_m2_monthly", "money_m3_monthly"):
        assert codes[code].unit == "units of local currency"


def test_the_monetary_source_is_registered_and_enabled() -> None:
    catalog = load_catalog(REPO_ROOT / "sources" / "catalog.yml")
    entry = catalog.get("cepalstat_monetary_monthly")

    assert entry.organization == "CEPAL"
    assert entry.frequency is Frequency.MONTHLY
    assert entry.license == "cepal_terms_of_use"
    assert entry.enabled
    assert set(entry.indicators) == {
        "money_m1_monthly",
        "money_m2_monthly",
        "money_m3_monthly",
    }


def test_the_two_debt_indicators_are_registered() -> None:
    """The first use of the fiscal category, declared since v0.1.0."""
    codes = {i.code: i for i in INDICATORS}

    for code in ("public_debt_usd_annual", "public_debt_pct_gdp_annual"):
        assert codes[code].category is IndicatorCategory.FISCAL
        assert codes[code].frequency is Frequency.ANNUAL


def test_the_debt_indicators_declare_their_own_value_types() -> None:
    """A stock in dollars is a level; a share of GDP is a percent."""
    codes = {i.code: i for i in INDICATORS}

    assert codes["public_debt_usd_annual"].value_type is ValueType.LEVEL
    assert codes["public_debt_usd_annual"].unit == "current USD"
    assert codes["public_debt_pct_gdp_annual"].value_type is ValueType.PERCENT
    assert codes["public_debt_pct_gdp_annual"].unit == "percent of GDP"


def test_the_debt_source_is_registered_and_enabled() -> None:
    catalog = load_catalog(REPO_ROOT / "sources" / "catalog.yml")
    entry = catalog.get("cepalstat_debt_annual")

    assert entry.organization == "CEPAL"
    assert entry.frequency is Frequency.ANNUAL
    assert entry.license == "cepal_terms_of_use"
    assert entry.enabled
    assert set(entry.indicators) == {
        "public_debt_usd_annual",
        "public_debt_pct_gdp_annual",
    }


def test_the_debt_rules_allow_a_ratio_above_one_hundred() -> None:
    """Nicaragua reached 222.1% of GDP; a 100 cap would reject real data."""
    rules = load_quality_rules(REPO_ROOT / "sources" / "quality_rules.yml")
    rule = rules.for_indicator("public_debt_pct_gdp_annual")

    assert rule.max_value is None
    assert rule.min_value == 0
    assert rule.allow_negative is False


def test_the_debt_change_threshold_clears_the_nicaraguan_relief() -> None:
    """1996 fell 47.8% on HIPC relief. The threshold is set above it knowingly."""
    rules = load_quality_rules(REPO_ROOT / "sources" / "quality_rules.yml")

    for code in ("public_debt_usd_annual", "public_debt_pct_gdp_annual"):
        assert rules.for_indicator(code).max_period_change_pct == 60
