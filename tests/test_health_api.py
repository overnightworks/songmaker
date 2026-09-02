"""Tests for /health's ACE-Step worker health computation.

Issue #367: a worker whose GPU has gone away (NVML present but unreachable —
a driver mismatch, a vanished device) keeps heartbeating to Redis just fine,
so the pre-fix "online" check (heartbeat key exists) kept counting it as a
healthy worker forever. These tests simulate that exact failure via the
``gpu_healthy`` flag the worker now publishes in its heartbeat state,
never a lucky real GPU.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from conftest import make_test_app

from songmaker_cli.db.models import AceStepWorker


def _seed_one_worker(session) -> None:
    session.add(
        AceStepWorker(id="acestep-worker-0", host="acestep-worker-0", port=8001),
    )


def _get_health(client, *, gpu_healthy: bool | None) -> dict:
    import songmaker_cli.arq_pool as arq_mod

    state: dict = {"loaded": []}
    if gpu_healthy is not None:
        state["gpu_healthy"] = gpu_healthy
    arq_mod._pool.get = AsyncMock(return_value=json.dumps(state).encode())

    with (
        patch("songmaker_cli.arq_pool.is_music_worker_healthy", AsyncMock(return_value=True)),
        patch("songmaker_cli.arq_pool.is_scoring_worker_healthy", AsyncMock(return_value=True)),
        patch("songmaker_cli.arq_pool.get_music_queue_depth", AsyncMock(return_value=0)),
        patch("songmaker_cli.arq_pool.get_scoring_queue_depth", AsyncMock(return_value=0)),
    ):
        resp = client.get("/health")
    assert resp.status_code == 200
    return resp.json()


@pytest.fixture()
def health_client(tmp_path, mock_arq_pool):
    client, _ = make_test_app(tmp_path, seed_db=_seed_one_worker)
    with client:
        yield client


def test_worker_with_broken_gpu_is_not_counted_online(health_client) -> None:
    body = _get_health(health_client, gpu_healthy=False)
    assert body["acestep_workers_total"] == 1
    assert body["acestep_workers_online"] == 0
    assert body["acestep"] == "unhealthy"


def test_acestep_unhealthy_marks_overall_status_degraded_but_keeps_200(
    health_client,
) -> None:
    body = _get_health(health_client, gpu_healthy=False)
    assert body["status"] == "degraded"


def test_worker_with_healthy_gpu_is_counted_online(health_client) -> None:
    body = _get_health(health_client, gpu_healthy=True)
    assert body["acestep_workers_online"] == 1
    assert body["acestep"] == "healthy"
    assert body["status"] == "ok"


def test_worker_without_gpu_healthy_field_is_treated_as_not_online(health_client) -> None:
    """Fail-closed: a heartbeat with no ``gpu_healthy`` key at all (an old
    or broken worker build that never learned to publish it) must never
    count as online on a silent "assume fine forever" default."""
    body = _get_health(health_client, gpu_healthy=None)
    assert body["acestep_workers_online"] == 0
    assert body["acestep"] == "unhealthy"


def test_metrics_excludes_broken_gpu_worker_from_online_count(health_client) -> None:
    """The #333 alert (`songmaker_acestep_workers_total{status="online"} == 0`)
    reads this exact metric — a GPU-broken worker still counted as "online"
    here is the original incident in new clothes."""
    import songmaker_cli.arq_pool as arq_mod

    arq_mod._pool.get = AsyncMock(
        return_value=json.dumps({"loaded": [], "gpu_healthy": False}).encode(),
    )
    arq_mod._pool.zcard = AsyncMock(return_value=0)

    resp = health_client.get("/metrics")
    assert resp.status_code == 200
    body = resp.text
    assert 'songmaker_acestep_workers_total{status="online"} 0' in body
    assert 'songmaker_acestep_workers_total{status="offline"} 1' in body
