"""``_post_to_webhook``: the real sender, exercised without touching a socket.

Every test in ``test_alerting_service.py`` injects ``send=``, so none of them
ever runs this function — it is the code that actually talks to a webhook in
production, and it earns coverage here by monkeypatching the two names
``reim.services.alerting`` imports (``http_client`` and ``post``) rather than
by adding an HTTP-mocking dependency or reaching the network.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest

from reim.core.config import Settings
from reim.core.exceptions import ExtractionError
from reim.services.alerting import AlertDeliveryError, _post_to_webhook

URL = "https://hooks.example.org/reim"


class _StubClient:
    """Stands in for the ``httpx.AsyncClient`` yielded by ``http_client``.

    Its only job is to remember whether ``follow_redirects`` was set to
    ``False`` — the only way that line in ``_post_to_webhook`` gets tested at
    all.
    """

    def __init__(self) -> None:
        self.follow_redirects = True


class _StubResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


def _settings() -> Settings:
    return Settings(alert_webhook_url=URL)


def _patch_http_client(monkeypatch: pytest.MonkeyPatch, client: _StubClient) -> None:
    @asynccontextmanager
    async def _fake_http_client(settings: Settings) -> AsyncIterator[_StubClient]:
        yield client

    monkeypatch.setattr("reim.services.alerting.http_client", _fake_http_client)


async def test_a_successful_delivery_disables_redirects_and_sends_the_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _StubClient()
    _patch_http_client(monkeypatch, client)
    calls: list[dict[str, Any]] = []

    async def _fake_post(
        posted_client: _StubClient,
        posted_url: str,
        *,
        content: bytes,
        headers: dict[str, str],
        settings: Settings,
    ) -> _StubResponse:
        calls.append(
            {
                "client": posted_client,
                "url": posted_url,
                "content": content,
                "headers": headers,
            }
        )
        return _StubResponse(200)

    monkeypatch.setattr("reim.services.alerting.post", _fake_post)

    await _post_to_webhook(URL, b'{"firing": []}', _settings())

    assert client.follow_redirects is False
    assert len(calls) == 1
    assert calls[0]["client"] is client
    assert calls[0]["url"] == URL
    assert calls[0]["content"] == b'{"firing": []}'
    assert calls[0]["headers"]["Content-Type"] == "application/json"


async def test_a_non_2xx_answer_becomes_an_alert_delivery_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``404`` rather than ``500``: a status the real ``post`` can actually hand back.

    ``500`` is in ``RETRYABLE_STATUS_CODES`` (``reim/ingestion/http.py``), so
    the real client would retry it and raise ``ExtractionError`` before this
    function ever saw a response — a situation production cannot produce. It
    also fails to discriminate the boundary: ``500`` satisfies both ``>= 300``
    and ``>= 500``, so a regression that widened the check to ``>= 500`` would
    still pass. ``404`` is what ``post``'s own docstring calls "a real answer".
    """
    _patch_http_client(monkeypatch, _StubClient())

    async def _fake_post(*args: Any, **kwargs: Any) -> _StubResponse:
        return _StubResponse(404)

    monkeypatch.setattr("reim.services.alerting.post", _fake_post)

    with pytest.raises(AlertDeliveryError) as excinfo:
        await _post_to_webhook(URL, b"{}", _settings())

    assert URL in excinfo.value.message
    assert excinfo.value.details["status_code"] == 404


async def test_a_non_2xx_answer_redacts_the_url_query_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spec §9: an operator-controlled webhook URL may carry a token."""
    url = "https://hooks.example.org/reim?token=secret"
    _patch_http_client(monkeypatch, _StubClient())

    async def _fake_post(*args: Any, **kwargs: Any) -> _StubResponse:
        return _StubResponse(404)

    monkeypatch.setattr("reim.services.alerting.post", _fake_post)

    with pytest.raises(AlertDeliveryError) as excinfo:
        await _post_to_webhook(url, b"{}", _settings())

    assert "secret" not in excinfo.value.message
    assert "hooks.example.org" in excinfo.value.message
    assert "secret" not in json.dumps(excinfo.value.details)


async def test_a_transport_failure_translation_redacts_the_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ``{url}`` this module interpolates is redacted, even though the
    chained ``ExtractionError``'s own message may still name the raw URL —
    that deeper leak lives in ``reim/ingestion/http.py`` and is out of scope
    here (see the ``.env.example`` note beside ``REIM_ALERT_WEBHOOK_URL``).
    """
    url = "https://hooks.example.org/reim?token=secret"
    _patch_http_client(monkeypatch, _StubClient())
    original = ExtractionError("boom", url=url)

    async def _fake_post(*args: Any, **kwargs: Any) -> _StubResponse:
        raise original

    monkeypatch.setattr("reim.services.alerting.post", _fake_post)

    with pytest.raises(AlertDeliveryError) as excinfo:
        await _post_to_webhook(url, b"{}", _settings())

    assert "secret" not in excinfo.value.message
    assert "secret" not in json.dumps(excinfo.value.details)


async def test_a_transport_failure_is_translated_and_the_original_is_chained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The translation the spec asks for; the chaining proves nothing is swallowed."""
    _patch_http_client(monkeypatch, _StubClient())
    original = ExtractionError("boom", url=URL)

    async def _fake_post(*args: Any, **kwargs: Any) -> _StubResponse:
        raise original

    monkeypatch.setattr("reim.services.alerting.post", _fake_post)

    with pytest.raises(AlertDeliveryError) as excinfo:
        await _post_to_webhook(URL, b"{}", _settings())

    assert excinfo.value.__cause__ is original
