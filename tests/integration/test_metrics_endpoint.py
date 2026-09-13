"""``/metrics``: the process defaults, the pipeline series, and the outage.

The endpoint is thin — the figures are tested in
``tests/integration/test_metrics_service.py`` and the rendering in
``tests/unit/test_metrics_render.py``. What is asserted here is the wiring: both
payloads present, a 200 during an outage, and the 404 when metrics are off.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from apps.api.dependencies import get_db
from apps.api.main import create_app
from tests.conftest import requires_db


@pytest.fixture
def client(seeded_session: Session) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_db] = lambda: seeded_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@requires_db
def test_the_scrape_carries_both_the_process_and_the_pipeline_metrics(
    client: TestClient,
) -> None:
    """Concatenating two registries is only valid if neither name collides."""
    response = client.get("/metrics")

    assert response.status_code == 200
    body = response.text
    assert "python_info" in body
    assert "reim_database_up 1.0" in body
    assert "reim_pipeline_enabled{" in body


@requires_db
def test_every_catalog_pipeline_appears_in_the_scrape(client: TestClient) -> None:
    body = client.get("/metrics").text

    assert body.count("reim_pipeline_enabled{") == 23


@requires_db
def test_an_outage_answers_two_hundred_with_the_database_marked_down(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A scrape target that vanishes during an outage is useless during one."""

    def _raise(*args: object, **kwargs: object) -> None:
        raise SQLAlchemyError("database is down")

    monkeypatch.setattr("reim.services.metrics.run_repo.latest_runs_by_pipeline", _raise)

    response = client.get("/metrics")

    assert response.status_code == 200
    assert "reim_database_up 0.0" in response.text
    assert "python_info" in response.text
    assert "reim_pipeline_enabled{" not in response.text


@requires_db
def test_metrics_can_still_be_switched_off(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REIM_METRICS_ENABLED", "false")
    from reim.core.config import get_settings

    get_settings.cache_clear()
    try:
        assert client.get("/metrics").status_code == 404
    finally:
        get_settings.cache_clear()
