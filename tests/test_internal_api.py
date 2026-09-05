"""Tests for the internal worker registration API."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import make_test_app
from fastapi.testclient import TestClient

from songmaker_cli.db.queries import get_worker_identity, list_worker_identities


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    client, _ = make_test_app(tmp_path)
    yield client


def _payload(**overrides) -> dict:
    base = {
        "worker_id": "acestep-worker-0",
        "host": "acestep-worker-0",
        "port": 8001,
        "gpu_id": 0,
        "vram_total_gb": 24.0,
    }
    base.update(overrides)
    return base


def test_register_missing_token_header(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SONGMAKER_INTERNAL_TOKEN", "secret")
    from songmaker_cli.settings import get_settings
    get_settings.cache_clear()
    resp = client.post("/api/internal/workers/register", json=_payload())
    assert resp.status_code == 422


def test_register_wrong_token_returns_401(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SONGMAKER_INTERNAL_TOKEN", "secret")
    from songmaker_cli.settings import get_settings
    get_settings.cache_clear()
    resp = client.post(
        "/api/internal/workers/register",
        json=_payload(),
        headers={"X-Internal-Token": "wrong"},
    )
    assert resp.status_code == 401


def test_register_empty_token_returns_503(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SONGMAKER_INTERNAL_TOKEN", "")
    from songmaker_cli.settings import get_settings
    get_settings.cache_clear()
    resp = client.post(
        "/api/internal/workers/register",
        json=_payload(),
        headers={"X-Internal-Token": "anything"},
    )
    assert resp.status_code == 503


def test_register_success_creates_row(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SONGMAKER_INTERNAL_TOKEN", "secret")
    from songmaker_cli.settings import get_settings
    get_settings.cache_clear()
    resp = client.post(
        "/api/internal/workers/register",
        json=_payload(),
        headers={"X-Internal-Token": "secret"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["worker_id"] == "acestep-worker-0"
    assert data["registered_at"]

    factory = client.app.state.ctx.db
    with factory() as session:
        worker = get_worker_identity(session, "acestep-worker-0")
        assert worker is not None
        assert worker.host == "acestep-worker-0"
        assert worker.port == 8001
        assert worker.gpu_id == 0
        assert worker.vram_total_gb == 24.0


def test_register_is_idempotent(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SONGMAKER_INTERNAL_TOKEN", "secret")
    from songmaker_cli.settings import get_settings
    get_settings.cache_clear()
    headers = {"X-Internal-Token": "secret"}

    resp1 = client.post(
        "/api/internal/workers/register",
        json=_payload(host="old"),
        headers=headers,
    )
    assert resp1.status_code == 200

    resp2 = client.post(
        "/api/internal/workers/register",
        json=_payload(host="new", port=9999),
        headers=headers,
    )
    assert resp2.status_code == 200

    factory = client.app.state.ctx.db
    with factory() as session:
        rows = list_worker_identities(session)
        assert len(rows) == 1
        assert rows[0].host == "new"
        assert rows[0].port == 9999


def test_router_has_token_dependency() -> None:
    from songmaker_cli.internal_api import router, verify_internal_token

    assert any(
        getattr(dep, "dependency", None) is verify_internal_token
        for dep in router.dependencies
    )
