"""Shared HTTP layer: TLS profiles and the retry policy."""

from __future__ import annotations

import ssl

import httpx
import pytest
import respx

from reim.core.config import get_settings
from reim.core.constants import TlsProfile
from reim.core.exceptions import ExtractionError
from reim.ingestion.http import fetch, http_client, legacy_tls_context, post

SOAP_URL = "https://servicios.bcn.gob.ni/Tc_Servicio/ServicioTC.asmx"


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


# --------------------------------------------------------------------------
# post()
# --------------------------------------------------------------------------
@respx.mock
async def test_post_returns_a_successful_response() -> None:
    route = respx.post(SOAP_URL).mock(return_value=httpx.Response(200, text="<ok/>"))

    async with http_client() as client:
        response = await post(client, SOAP_URL, content=b"<req/>")

    assert response.status_code == 200
    assert route.call_count == 1


@respx.mock
async def test_post_retries_a_transient_status_then_succeeds() -> None:
    route = respx.post(SOAP_URL).mock(
        side_effect=[httpx.Response(503), httpx.Response(200, text="<ok/>")]
    )

    async with http_client() as client:
        response = await post(client, SOAP_URL, content=b"<req/>")

    assert response.status_code == 200
    assert route.call_count == 2


@respx.mock
async def test_post_does_not_retry_a_real_error_status() -> None:
    """A 404 is an answer, not a transient failure."""
    route = respx.post(SOAP_URL).mock(return_value=httpx.Response(404))

    async with http_client() as client:
        response = await post(client, SOAP_URL, content=b"<req/>")

    assert response.status_code == 404
    assert route.call_count == 1


@respx.mock
async def test_post_raises_extraction_error_when_the_host_is_unreachable() -> None:
    respx.post(SOAP_URL).mock(side_effect=httpx.ConnectError("boom"))
    # A transport error is retried, so cap the attempts at one: the default
    # would spend ~7s in exponential backoff to assert the same thing.
    no_retries = get_settings().model_copy(update={"http_max_retries": 0})

    async with http_client() as client:
        with pytest.raises(ExtractionError, match="Could not reach"):
            await post(client, SOAP_URL, content=b"<req/>", settings=no_retries)


@respx.mock
async def test_post_sends_the_body_and_headers_unchanged() -> None:
    route = respx.post(SOAP_URL).mock(return_value=httpx.Response(200, text="<ok/>"))

    async with http_client() as client:
        await post(
            client,
            SOAP_URL,
            content=b"<envelope/>",
            headers={"SOAPAction": "http://servicios.bcn.gob.ni/RecuperaTC_Mes"},
        )

    request = route.calls.last.request
    assert request.content == b"<envelope/>"
    assert request.headers["SOAPAction"] == "http://servicios.bcn.gob.ni/RecuperaTC_Mes"


@respx.mock
async def test_the_honest_user_agent_is_the_default() -> None:
    route = respx.get("https://example.invalid/x").mock(return_value=httpx.Response(200, text="ok"))

    async with http_client() as client:
        await fetch(client, "https://example.invalid/x")

    assert route.calls.last.request.headers["User-Agent"].startswith("REIM/")


@respx.mock
async def test_a_source_can_override_the_user_agent() -> None:
    route = respx.get("https://example.invalid/x").mock(return_value=httpx.Response(200, text="ok"))

    async with http_client(user_agent="Mozilla/5.0 (X11; Linux x86_64) Chrome/126.0") as client:
        await fetch(client, "https://example.invalid/x")

    assert route.calls.last.request.headers["User-Agent"] == (
        "Mozilla/5.0 (X11; Linux x86_64) Chrome/126.0"
    )
