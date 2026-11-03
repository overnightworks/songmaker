"""``/metrics`` answers only Prometheus's own token; ``/health`` stays open."""

from __future__ import annotations

import pytest
from support.web_app import make_test_app

from songmaker_cli.constants import PROM_CONTENT_TYPE

CONFIGURED_MONITORING_TOKEN = "scratch-monitoring-token"


@pytest.fixture
def metrics_client(tmp_path, mock_arq_pool):
    client, _ = make_test_app(tmp_path)
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
