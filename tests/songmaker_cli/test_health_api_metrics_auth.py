"""``/metrics`` and ``/health/details`` answer only the monitoring token; ``/health`` stays open."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from support.web_app import make_test_app

from songmaker_cli.health_api import PROM_CONTENT_TYPE

CONFIGURED_MONITORING_TOKEN = "scratch-monitoring-token"


@pytest.fixture
def metrics_client(tmp_path, mock_arq_pool, pg_factory):
    client, _ = make_test_app(tmp_path, factory=pg_factory)
    with client:
        yield client


def _bearer(credentials: str, scheme: str = "Bearer") -> dict[str, str]:
    return {"Authorization": f"{scheme} {credentials}"}


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param({}, id="no-header"),
        pytest.param(_bearer(CONFIGURED_MONITORING_TOKEN, "Basic"), id="basic-scheme"),
        pytest.param({"Authorization": "Bearer"}, id="bearer-without-credential"),
        pytest.param(_bearer("wrong-token"), id="wrong-token"),
        pytest.param(_bearer(CONFIGURED_MONITORING_TOKEN + "x"), id="longer"),
    ],
)
def test_metrics_refuses_a_request_without_the_monitoring_token(
    metrics_client, monkeypatch, fresh_settings, headers,
) -> None:
    monkeypatch.setenv("SONGMAKER_MONITORING_TOKEN", CONFIGURED_MONITORING_TOKEN)

    resp = metrics_client.get("/metrics", headers=headers)

    assert resp.status_code == 401
    assert resp.json() == {"detail": "Not authenticated"}
    assert resp.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("configured", [None, "", "   "], ids=["unset", "empty", "whitespace"])
def test_metrics_is_unavailable_and_health_answers_without_a_monitoring_token(
    metrics_client, monkeypatch, fresh_settings, configured,
) -> None:
    monkeypatch.delenv("SONGMAKER_MONITORING_TOKEN", raising=False)
    if configured is not None:
        monkeypatch.setenv("SONGMAKER_MONITORING_TOKEN", configured)

    resp = metrics_client.get("/metrics", headers=_bearer(configured or ""))

    assert resp.status_code == 503
    assert resp.json() == {"detail": "Monitoring not configured"}
    assert metrics_client.get("/health").status_code == 200
    details = metrics_client.get("/health/details", headers=_bearer(configured or ""))
    assert details.status_code == 503


@pytest.mark.parametrize(
    ("scheme", "configured"),
    [
        pytest.param("Bearer", CONFIGURED_MONITORING_TOKEN, id="bearer"),
        pytest.param("bearer", CONFIGURED_MONITORING_TOKEN, id="lowercase-scheme"),
        pytest.param("Bearer", f"  {CONFIGURED_MONITORING_TOKEN}\n", id="trimmed-like-prometheus"),
    ],
)
def test_metrics_serves_prometheus_text_to_the_monitoring_token(
    metrics_client, monkeypatch, fresh_settings, scheme, configured,
) -> None:
    monkeypatch.setenv("SONGMAKER_MONITORING_TOKEN", configured)

    resp = metrics_client.get("/metrics", headers=_bearer(CONFIGURED_MONITORING_TOKEN, scheme))

    assert resp.status_code == 200
    assert resp.headers["content-type"] == PROM_CONTENT_TYPE
    assert "songmaker_acestep_workers_total" in resp.text


@pytest.fixture
def workers_running(request):
    running = request.param
    with (
        patch("songmaker_cli.arq_pool.is_music_worker_healthy", AsyncMock(return_value=running)),
        patch("songmaker_cli.arq_pool.is_scoring_worker_healthy", AsyncMock(return_value=running)),
    ):
        yield running


@pytest.mark.parametrize(
    ("workers_running", "status"), [(True, "ok"), (False, "degraded")],
    indirect=["workers_running"],
)
def test_health_answers_its_status_and_nothing_else_to_everyone(
    metrics_client, monkeypatch, fresh_settings, workers_running, status,
) -> None:
    monkeypatch.setenv("SONGMAKER_MONITORING_TOKEN", CONFIGURED_MONITORING_TOKEN)
    metrics_client.cookies.set("songmaker_session", "any-session-value")

    for headers in (
        {},
        _bearer(CONFIGURED_MONITORING_TOKEN),
        _bearer("wrong-token"),
        _bearer(CONFIGURED_MONITORING_TOKEN, "Basic"),
    ):
        resp = metrics_client.get("/health", headers=headers)

        assert resp.status_code == 200
        assert resp.json() == {"status": status}


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param({}, id="no-header"),
        pytest.param(_bearer("wrong-token"), id="wrong-token"),
    ],
)
def test_health_details_refuses_a_request_without_the_monitoring_token(
    metrics_client, monkeypatch, fresh_settings, headers,
) -> None:
    monkeypatch.setenv("SONGMAKER_MONITORING_TOKEN", CONFIGURED_MONITORING_TOKEN)

    resp = metrics_client.get("/health/details", headers=headers)

    assert resp.status_code == 401
    assert resp.json() == {"detail": "Not authenticated"}


def test_health_details_refuses_a_session_cookie_alone(
    metrics_client, monkeypatch, fresh_settings,
) -> None:
    monkeypatch.setenv("SONGMAKER_MONITORING_TOKEN", CONFIGURED_MONITORING_TOKEN)
    metrics_client.cookies.set("songmaker_session", "any-session-value")

    assert metrics_client.get("/health/details").status_code == 401


@pytest.mark.parametrize(
    ("workers_running", "status"), [(True, "ok"), (False, "degraded")],
    indirect=["workers_running"],
)
def test_health_details_serve_the_full_body_to_the_monitoring_token_and_agree_on_status(
    metrics_client, monkeypatch, fresh_settings, workers_running, status,
) -> None:
    monkeypatch.setenv("SONGMAKER_MONITORING_TOKEN", CONFIGURED_MONITORING_TOKEN)

    details = metrics_client.get("/health/details", headers=_bearer(CONFIGURED_MONITORING_TOKEN))

    assert details.status_code == 200
    assert details.json()["status"] == status == metrics_client.get("/health").json()["status"]
    assert {"db", "redis", "release", "background_loops"} <= details.json().keys()
