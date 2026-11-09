"""The admin restart route refuses when the worker answers with an error."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient
from support.web_app import make_test_app, seed_session, seed_user

from songmaker_cli.db.queries.workers import register_worker

WORKER_ID = "w1"


class _WorkerAnswering:
    """The worker's HTTP end: every post is answered with ``status_code``."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code

    async def __aenter__(self) -> _WorkerAnswering:
        return self

    async def __aexit__(self, *_exc) -> bool:
        return False

    async def post(self, url: str, **_kwargs) -> httpx.Response:
        return httpx.Response(self.status_code, request=httpx.Request("POST", url))


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


def test_a_restart_the_worker_answers_with_an_error_is_refused_as_failed(
    admin_client: TestClient,
) -> None:
    with patch("songmaker_cli.admin_api.httpx.AsyncClient", return_value=_WorkerAnswering(500)):
        response = admin_client.post(f"/api/admin/workers/{WORKER_ID}/restart")

    assert response.status_code == 502
