"""Source catalog validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from reim.core.constants import TlsProfile
from reim.core.exceptions import CatalogError, CatalogValidationError
from reim.domain.sources.catalog import SourceCatalog, load_catalog

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
