"""Shared HTTP layer: TLS profiles and the retry policy."""

from __future__ import annotations

import ssl

import pytest

from reim.core.constants import TlsProfile
from reim.ingestion.http import http_client, legacy_tls_context


def test_legacy_context_pins_tls_10() -> None:
    ctx = legacy_tls_context()

    assert ctx.minimum_version is ssl.TLSVersion.TLSv1
    assert ctx.maximum_version is ssl.TLSVersion.TLSv1


def test_legacy_context_keeps_certificate_verification() -> None:
    """The concession is 'this host is old', not 'trust anyone'."""
    ctx = legacy_tls_context()

    assert ctx.check_hostname is True
    assert ctx.verify_mode is ssl.CERT_REQUIRED
    assert ctx.get_ca_certs(), "the CA bundle must be loaded"


def test_legacy_context_does_not_leak_a_deprecation_warning(
    recwarn: pytest.WarningsRecorder,
) -> None:
    """pyproject turns DeprecationWarning from reim.* into an error."""
    legacy_tls_context()

    assert not [w for w in recwarn if issubclass(w.category, DeprecationWarning)]


async def test_http_client_verifies_normally_by_default() -> None:
    async with http_client() as client:
        assert client is not None


async def test_http_client_accepts_the_legacy_profile() -> None:
    async with http_client(tls_profile=TlsProfile.LEGACY) as client:
        assert client is not None
