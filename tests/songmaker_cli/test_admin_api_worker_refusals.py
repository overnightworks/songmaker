"""The admin worker and model routes refuse with a sentence and a catalog key."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient
from songmaker_cli.arq_pool import get_arq_pool_dep
from support.refused_download import hold_a_download
from support.web_app import SettledFakeAsyncRedis, make_test_app, seed_session, seed_user

from songmaker_cli.acestep_state import worker_state_key
from songmaker_cli.db.queries.workers import register_worker

WORKER_ID = "w1"


class _WorkerAnswering:
    """The worker's HTTP end: every post is answered with ``status_code``."""

    def __init__(self, status_code: int, body: str = "") -> None:
        self.status_code = status_code
        self.body = body

    async def __aenter__(self) -> _WorkerAnswering:
        return self

    async def __aexit__(self, *_exc) -> bool:
        return False

    async def post(self, url: str, **_kwargs) -> httpx.Response:
        return httpx.Response(
            self.status_code, text=self.body, request=httpx.Request("POST", url),
        )


@pytest.fixture
def admin_client(tmp_path: Path, pg_factory) -> TestClient:
    client, factory = make_test_app(tmp_path, factory=pg_factory)
    with factory() as session:
        seed_user(session, "admin", "admin")
        register_worker(
            session, worker_id=WORKER_ID, host=WORKER_ID, port=8001, gpu_id=0,
            vram_total_gb=24.0,
        )
        session.commit()
    seed_session(client, "admin")
    return client


class _WorkerUnreachable(_WorkerAnswering):
    async def post(self, url: str, **_kwargs) -> httpx.Response:
        raise httpx.ConnectError("refused")


def _heartbeat(**state) -> dict[str, str]:
    return {worker_state_key(WORKER_ID): json.dumps({"gpu_healthy": True, **state})}


def _message(response) -> dict:
    return response.json()["message"]


def test_a_restart_the_worker_answers_with_an_error_is_refused_as_failed(
    admin_client: TestClient,
) -> None:
    with patch("songmaker_cli.admin_api.httpx.AsyncClient", return_value=_WorkerAnswering(500)):
        response = admin_client.post(f"/api/admin/workers/{WORKER_ID}/restart")

    assert response.status_code == 502
    assert response.json()["detail"] == "Worker returned 500"
    assert _message(response) == {
        "key": "workerRefusal.returnedStatus", "values": {"status": "500"},
    }


def test_a_restart_nobody_answers_names_the_worker(admin_client: TestClient) -> None:
    with patch("songmaker_cli.admin_api.httpx.AsyncClient", return_value=_WorkerUnreachable(0)):
        response = admin_client.post(f"/api/admin/workers/{WORKER_ID}/restart")

    assert _message(response) == {
        "key": "workerRefusal.notResponding", "values": {"workerId": WORKER_ID},
    }


def test_a_model_command_nobody_answers_names_the_connection_error(
    admin_client: TestClient,
) -> None:
    with patch("songmaker_cli.admin_api.httpx.AsyncClient", return_value=_WorkerUnreachable(0)):
        response = admin_client.post(
            f"/api/admin/workers/{WORKER_ID}/evict_model", json={"mode": "sft"},
        )

    assert _message(response) == {
        "key": "workerRefusal.unreachable", "values": {"reason": "refused"},
    }


@pytest.mark.parametrize(
    ("worker_status", "body", "expected_status", "cause"),
    [
        (409, '{"detail": "Model busy"}', 409, "Model busy"),
        (400, '{"detail": "Bad mode"}', 400, "Bad mode"),
        (500, "", 502, "Worker returned 500 with no detail"),
    ],
)
def test_a_model_command_the_worker_refuses_relays_the_workers_words(
    admin_client: TestClient,
    worker_status: int,
    body: str,
    expected_status: int,
    cause: str,
) -> None:
    worker = _WorkerAnswering(worker_status, body)
    with patch("songmaker_cli.admin_api.httpx.AsyncClient", return_value=worker):
        response = admin_client.post(
            f"/api/admin/workers/{WORKER_ID}/evict_model", json={"mode": "sft"},
        )

    assert response.status_code == expected_status
    assert response.json()["detail"] == cause
    assert _message(response) == {"key": "workerRefusal.relayed", "values": {"cause": cause}}


@pytest.mark.parametrize("route", ["load_model", "evict_model"])
def test_a_model_mode_nobody_knows_is_named_on_a_worker_route(
    admin_client: TestClient, route: str,
) -> None:
    response = admin_client.post(f"/api/admin/workers/{WORKER_ID}/{route}", json={"mode": "bogus"})

    assert response.status_code == 400
    assert _message(response) == {
        "key": "adminRefusal.unknownModelMode", "values": {"mode": "bogus"},
    }


@pytest.mark.parametrize(
    ("route", "body"),
    [
        ("load_model", {"mode": "sft"}),
        ("evict_model", {"mode": "sft"}),
        ("restart", None),
    ],
)
def test_a_worker_nobody_registered_is_named_on_each_worker_route(
    admin_client: TestClient, route: str, body: dict[str, str] | None,
) -> None:
    response = admin_client.post(f"/api/admin/workers/ghost/{route}", json=body)

    assert response.status_code == 404
    assert response.json()["detail"] == "Worker 'ghost' not found"
    assert _message(response) == {"key": "workerRefusal.notFound", "values": {"workerId": "ghost"}}


@pytest.mark.parametrize(
    ("mode", "store", "download_holder", "status", "key", "values"),
    [
        ("bogus", _heartbeat(), None, 400, "adminRefusal.unknownModelMode", {"mode": "bogus"}),
        ("sft", {}, None, 503, "adminRefusal.noOnlineWorkers", {}),
        (
            "sft", _heartbeat(available_modes=["sft"]), None, 409,
            "adminRefusal.alreadyDownloaded", {"mode": "sft"},
        ),
        (
            "xl-base", _heartbeat(), "job-7", 409,
            "adminRefusal.alreadyDownloading", {"mode": "xl-base", "jobId": "job-7"},
        ),
    ],
)
def test_a_download_the_registry_cannot_start_names_why(
    admin_client: TestClient,
    mode: str,
    store: dict[str, str],
    download_holder: str | None,
    status: int,
    key: str,
    values: dict[str, str],
) -> None:
    pool = SettledFakeAsyncRedis()
    for stored_key, value in store.items():
        pool.store[stored_key] = value
    if download_holder is not None:
        hold_a_download(pool, mode, download_holder)
    admin_client.app.dependency_overrides[get_arq_pool_dep] = lambda: pool

    response = admin_client.post(f"/api/admin/registry/{mode}/download")

    assert response.status_code == status
    assert _message(response) == {"key": key, "values": values}
