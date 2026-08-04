"""Content hashing, natural keys and duplicate detection."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from reim.domain.observations.hashing import (
    content_hash,
    natural_key,
    natural_key_digest,
    normalize_decimal,
)

BASE = {
    "country_iso3": "NIC",
    "indicator_code": "ni_cpi_inflation_annual",
    "source_key": "worldbank_ni_cpi_inflation",
    "period_start": date(2024, 1, 1),
    "period_end": date(2024, 12, 31),
    "value_numeric": Decimal("4.62473841057141"),
    "unit": "percent",
}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1.50", "1.5"),
        ("1.5", "1.5"),
        ("1.500000", "1.5"),
        ("1000", "1000"),
        ("1E+3", "1000"),
        ("0", "0"),
        ("-2.30", "-2.3"),
        ("2.06064418965517E-9", "0.00000000206064418965517"),
    ],
)
def test_normalize_decimal_is_canonical(raw: str, expected: str) -> None:
    assert normalize_decimal(Decimal(raw)) == expected


def test_normalize_decimal_preserves_none() -> None:
    assert normalize_decimal(None) is None


def test_hash_is_deterministic() -> None:
    assert content_hash(**BASE) == content_hash(**BASE)


def test_trailing_zeros_do_not_change_the_hash() -> None:
    """1.50 and 1.5 are the same figure and must not look like a revision."""
    a = content_hash(**{**BASE, "value_numeric": Decimal("1.50")})
    b = content_hash(**{**BASE, "value_numeric": Decimal("1.5")})
    assert a == b


def test_case_and_whitespace_are_normalized() -> None:
    a = content_hash(**BASE)
    b = content_hash(
        **{
            **BASE,
            "country_iso3": "nic",
            "indicator_code": "NI_CPI_INFLATION_ANNUAL",
            "unit": "  percent  ",
        }
    )
    assert a == b


@pytest.mark.parametrize(
    "override",
    [
        {"value_numeric": Decimal("4.7")},
        {"unit": "index"},
        {"currency_code": "USD"},
        {"period_end": date(2024, 6, 30)},
        {"indicator_code": "ni_remittances_received"},
        {"source_key": "bcn_exchange_rate"},
        {"country_iso3": "CRI"},
        {"value_text": "provisional"},
    ],
)
def test_any_payload_change_changes_the_hash(override: dict[str, object]) -> None:
    assert content_hash(**{**BASE, **override}) != content_hash(**BASE)


def test_hash_excludes_retrieval_metadata() -> None:
    """Re-running an unchanged pipeline must not look like a revision.

    ``retrieved_at`` and the version stamps are deliberately not part of the
    hashed payload, so identical upstream data always hashes identically.
    """
    signature = set(content_hash.__code__.co_varnames[: content_hash.__code__.co_argcount])
    excluded = {"retrieved_at", "connector_version", "pipeline_version", "published_at"}
    assert signature.isdisjoint(excluded)


def test_hash_is_a_sha256_hex_digest() -> None:
    digest = content_hash(**BASE)
    assert len(digest) == 64
    assert set(digest) <= set("0123456789abcdef")


def test_natural_key_is_normalized() -> None:
    key = natural_key(
        country_iso3="nic",
        indicator_code="NI_CPI_INFLATION_ANNUAL",
        source_key="WorldBank_NI_CPI_Inflation",
        period_start=date(2024, 1, 1),
        period_end=date(2024, 12, 31),
    )
    assert key == (
        "NIC",
        "ni_cpi_inflation_annual",
        "worldbank_ni_cpi_inflation",
        "2024-01-01",
        "2024-12-31",
    )


def test_natural_key_distinguishes_sources_for_the_same_series() -> None:
    """Two sources publishing the same concept must remain separate series."""
    common = {
        "country_iso3": "NIC",
        "indicator_code": "ni_exchange_rate_official_annual_avg",
        "period_start": date(2024, 1, 1),
        "period_end": date(2024, 12, 31),
    }
    assert natural_key(**common, source_key="worldbank_ni_exchange_rate") != natural_key(
        **common, source_key="bcn_exchange_rate"
    )


def test_natural_key_digest_is_stable_and_distinct() -> None:
    args = {
        "country_iso3": "NIC",
        "indicator_code": "ni_cpi_inflation_annual",
        "source_key": "worldbank_ni_cpi_inflation",
        "period_start": date(2024, 1, 1),
        "period_end": date(2024, 12, 31),
    }
    assert natural_key_digest(**args) == natural_key_digest(**args)
    assert natural_key_digest(**{**args, "period_start": date(2023, 1, 1)}) != natural_key_digest(
        **args
    )


def test_observation_hash_matches_helper(make_observation) -> None:  # type: ignore[no-untyped-def]
    observation = make_observation("2024", "4.5")
    assert observation.compute_content_hash() == content_hash(
        country_iso3="NIC",
        indicator_code="ni_cpi_inflation_annual",
        source_key="worldbank_ni_cpi_inflation",
        period_start=date(2024, 1, 1),
        period_end=date(2024, 12, 31),
        value_numeric=Decimal("4.5"),
        value_text=None,
        unit="percent",
        currency_code=None,
    )


def test_retrieval_time_does_not_affect_the_observation_hash(make_observation) -> None:  # type: ignore[no-untyped-def]
    early = make_observation("2024", "4.5", retrieved_at=datetime(2026, 1, 1, tzinfo=UTC))
    late = make_observation("2024", "4.5", retrieved_at=datetime(2026, 8, 4, tzinfo=UTC))
    assert early.compute_content_hash() == late.compute_content_hash()
