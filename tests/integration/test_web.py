"""The web catalog browser skeleton: an empty page, mounted beside the API.

Unlike ``test_api.py``, these tests need no database. They cover routing and
static-file wiring only, so they run against a plain ``TestClient`` with no
seeded session and no dependency override — the ordinary gate, not the
database-gated integration suite.

The two API routes checked below (``/health`` and ``/metrics``) are
deliberately the ones that touch no database: every data-bearing router
(indicators, countries, sources, ...) requires a live session via
``SessionDep``, which is out of scope for this task.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.main import create_app


def test_the_catalog_page_renders() -> None:
    """The skeleton serves HTML at the site root, beside the API."""
    client = TestClient(create_app())

    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "REIM" in response.text


def test_the_api_is_unchanged_by_the_web_surface() -> None:
    """Mounting pages at / must not move or shadow any API route."""
    client = TestClient(create_app())

    assert client.get("/health").status_code == 200
    assert client.get("/metrics").status_code == 200


def test_the_stylesheet_is_served() -> None:
    """No CDN: the one stylesheet ships with the application."""
    client = TestClient(create_app())

    response = client.get("/static/reim.css")

    assert response.status_code == 200
    assert "css" in response.headers["content-type"]
