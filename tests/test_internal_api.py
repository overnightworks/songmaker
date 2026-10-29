"""Tests for the internal worker registration API."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from support.web_app import make_test_app

from songmaker_cli.db.queries.workers import get_worker_identity, list_worker_identities


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    client, _ = make_test_app(tmp_path)
    return client


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


@pytest.mark.parametrize(
    ("configured_token", "header_token", "expected_status"),
    [
        pytest.param("secret", None, 422, id="missing-header"),
        pytest.param("secret", b"wrong", 401, id="wrong-token"),
        pytest.param("secret", b"", 401, id="empty-token"),
        pytest.param("secret", b"\xff", 401, id="raw-non-ascii-token"),
        pytest.param("", b"anything", 503, id="unconfigured-server"),
        pytest.param("secret", b"secret", 200, id="valid-registration"),
    ],
)
def test_register_token_authentication(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    configured_token: str,
    header_token: bytes | None,
    expected_status: int,
) -> None:
    """1301-F9-AUTH: token failures refuse registration; a valid token persists it."""
    monkeypatch.setenv("SONGMAKER_INTERNAL_TOKEN", configured_token)
    from songmaker_cli.settings import get_settings
    get_settings.cache_clear()
    headers = [] if header_token is None else [(b"X-Internal-Token", header_token)]
    resp = client.post(
        "/api/internal/workers/register",
        json=_payload(),
        headers=headers,
    )
    assert resp.status_code == expected_status

    factory = client.app.state.ctx.db
    with factory() as session:
        worker = get_worker_identity(session, "acestep-worker-0")
        if expected_status != 200:
            assert worker is None
            return
        assert worker is not None
        assert worker.host == "acestep-worker-0"
        assert worker.port == 8001
        assert worker.gpu_id == 0
        assert worker.vram_total_gb == 24.0

    data = resp.json()
    assert data["worker_id"] == "acestep-worker-0"
    assert data["registered_at"]


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
