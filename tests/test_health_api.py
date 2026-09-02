"""Tests for the /health endpoint: Claude CLI tool-surface reporting and
ACE-Step worker health computation.

Issue #367: a worker whose GPU has gone away (NVML present but unreachable —
a driver mismatch, a vanished device) keeps heartbeating to Redis just fine,
so the pre-fix "online" check (heartbeat key exists) kept counting it as a
healthy worker forever. These tests simulate that exact failure via the
``gpu_healthy`` flag the worker now publishes in its heartbeat state,
never a lucky real GPU.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from conftest import make_test_app

from songmaker_cli.claude import provider
from songmaker_cli.claude.provider import verify_cli_tool_surface as _real_verify_cli_tool_surface
from songmaker_cli.constants import BACKGROUND_LOOP_FAILURE_THRESHOLD
from songmaker_cli.db.models import AceStepWorker
from songmaker_cli.lifecycle import BackgroundLoopName


@pytest.fixture(autouse=True)
def _reset_tool_surface_state():
    """claude_cli_tool_surface_health() (round 7) is a module-level live
    value, not scoped to a single test the way most fixtures are — reset
    it around every test in this file so one test's real gate call can't
    leak its verdict into the next."""
    provider.clear_cli_tool_surface_cache()
    yield
    provider.clear_cli_tool_surface_cache()


def _init_line(tools: list[str]) -> bytes:
    return json.dumps({
        "type": "system",
        "subtype": "init",
        "tools": tools,
        "slash_commands": [],
        "mcp_servers": [{"name": "songmaker", "status": "connected"}],
    }).encode() + b"\n"


def _fake_cli(first_line: bytes) -> MagicMock:
    proc = MagicMock()
    proc.pid = 9191
    proc.poll.return_value = 0
    proc.stdin = MagicMock()
    proc.stdout = MagicMock()
    proc.stdout.readline.return_value = first_line
    proc.wait.return_value = None
    return proc


def _use_real_gate_with_fake_cli(monkeypatch, binary_path: Path, *lines: bytes) -> None:
    """Undo the test suite's blanket verify_cli_tool_surface() stub (see
    conftest._no_claude_cli_tool_surface_probe) for this one test, so the
    *real* gate — including the /health state it now records — runs
    against a fake CLI process instead of not running at all.
    """
    monkeypatch.setattr(provider, "verify_cli_tool_surface", _real_verify_cli_tool_surface)
    monkeypatch.setattr(provider, "_require_claude_binary", lambda: str(binary_path))
    queued = list(lines)

    def fake_popen(_cmd, **_kw):
        return _fake_cli(queued.pop(0))

    monkeypatch.setattr(provider.subprocess, "Popen", fake_popen)


def test_health_reports_claude_cli_tool_surface_ok_after_a_real_clean_probe(
    tmp_path: Path, monkeypatch, mock_arq_pool,
) -> None:
    binary = tmp_path / "claude"
    binary.write_bytes(b"cli-build")
    _use_real_gate_with_fake_cli(
        monkeypatch, binary, _init_line(sorted(provider._EXPECTED_MCP_TOOL_NAMES)),
    )

    client, _ = make_test_app(tmp_path)
    with client:
        resp = client.get("/health")

    assert resp.status_code == 200
    assert resp.json()["claude_cli_tool_surface"] == "ok"


def test_health_reports_drift_without_failing_the_server(
    tmp_path: Path, monkeypatch, mock_arq_pool,
) -> None:
    """#351 round 6, Finding 1 / the operator's ruling: a drifted Claude
    CLI must not stop the server from starting or serving albums and
    playback — it must be visible on /health, not only in the boot log,
    so the operator and monitoring see it instead of just whichever
    musician opens a chat first and finds it broken."""
    binary = tmp_path / "claude"
    binary.write_bytes(b"cli-build")
    _use_real_gate_with_fake_cli(monkeypatch, binary, _init_line(["Bash"]))

    client, _ = make_test_app(tmp_path)
    with client:
        resp = client.get("/health")

    assert resp.status_code == 200
    assert resp.json()["claude_cli_tool_surface"] == "drift"


def test_health_reports_unverified_when_the_probe_itself_could_not_check(
    tmp_path: Path, monkeypatch, mock_arq_pool,
) -> None:
    """#351 round 6 follow-up: "could not check" (no CLI mounted, a
    timeout, a zombie, MCP never connecting — anything UnavailableError
    that is not a confirmed CliToolSurfaceError) is its own state, not
    silently folded into "ok". Reporting it as "ok" would be exactly the
    silent default check_no_silent_fallbacks.py exists to catch."""
    binary = tmp_path / "claude"
    binary.write_bytes(b"cli-build")
    _use_real_gate_with_fake_cli(monkeypatch, binary, b"not json\n")

    client, _ = make_test_app(tmp_path)
    with client:
        resp = client.get("/health")

    assert resp.status_code == 200
    assert resp.json()["claude_cli_tool_surface"] == "unverified"


def test_health_defaults_to_unverified_not_ok_when_nothing_has_verified_yet(
    tmp_path: Path, mock_arq_pool,
) -> None:
    """The live state defaults to "unverified" (never a silent "ok")
    until something actually calls verify_cli_tool_surface() and records
    a real answer. This test never triggers a real gate call at all —
    including at boot, where the suite's own safety stub
    (conftest._no_claude_cli_tool_surface_probe) deliberately keeps
    verify_cli_tool_surface() from running for real, the same way a CLI
    that is not reachable yet would. Reporting "ok" here would be exactly
    the silent default check_no_silent_fallbacks.py exists to catch."""
    client, _ = make_test_app(tmp_path)
    with client:
        resp = client.get("/health")

    assert resp.status_code == 200
    assert resp.json()["claude_cli_tool_surface"] == "unverified"


def test_health_and_metrics_report_background_loop_health(tmp_path: Path, mock_arq_pool) -> None:
    client, _ = make_test_app(tmp_path)
    with client:
        registry = client.app.state.background_loop_registry
        for _ in range(BACKGROUND_LOOP_FAILURE_THRESHOLD):
            registry.record_failure(BackgroundLoopName.SCORE_BACKFILL, RuntimeError("no pool"))
        registry.mark_dead(BackgroundLoopName.SESSION_SYNC, None)

        health = client.get("/health")
        metrics = client.get("/metrics")

    assert health.status_code == 200
    assert health.json()["background_loops"] == {
        "session_sync": {"state": "dead", "consecutive_failures": 0},
        "resource_event_cleanup": {"state": "ok", "consecutive_failures": 0},
        "score_backfill": {"state": "failing", "consecutive_failures": 3},
        "stale_job_reaper": {"state": "ok", "consecutive_failures": 0},
    }
    assert metrics.status_code == 200
    assert 'songmaker_background_loop_consecutive_failures{loop="score_backfill"} 3' in metrics.text
    assert 'songmaker_background_loop_alive{loop="score_backfill"} 1' in metrics.text
    assert 'songmaker_background_loop_alive{loop="session_sync"} 0' in metrics.text


def test_health_reports_the_gates_most_recent_verdict_not_a_boot_snapshot(
    tmp_path: Path, monkeypatch, mock_arq_pool,
) -> None:
    """#351 round 7, Finding 4: /health must follow the tool-surface
    gate's live state, not a value captured once at boot — a later
    successful probe (e.g. a real co-writer turn, once the CLI becomes
    reachable) must be visible on the very next /health call, and a
    later drift must be visible too."""
    client, _ = make_test_app(tmp_path)

    import asyncio

    with client:
        before = client.get("/health").json()["claude_cli_tool_surface"]
        assert before == "unverified"

        clean_binary = tmp_path / "claude-clean"
        clean_binary.write_bytes(b"cli-build")
        _use_real_gate_with_fake_cli(
            monkeypatch, clean_binary, _init_line(sorted(provider._EXPECTED_MCP_TOOL_NAMES)),
        )
        asyncio.run(_real_verify_cli_tool_surface())
        after_clean = client.get("/health").json()["claude_cli_tool_surface"]

        drifted_binary = tmp_path / "claude-drifted"
        drifted_binary.write_bytes(b"cli-build-2")
        provider.clear_cli_tool_surface_cache()
        _use_real_gate_with_fake_cli(monkeypatch, drifted_binary, _init_line(["Bash"]))
        with pytest.raises(provider.CliToolSurfaceError):
            asyncio.run(_real_verify_cli_tool_surface())
        after_drift = client.get("/health").json()["claude_cli_tool_surface"]

    assert after_clean == "ok"
    assert after_drift == "drift"


def test_health_drift_does_not_by_itself_mark_the_server_degraded(
    tmp_path: Path, monkeypatch, mock_arq_pool,
) -> None:
    """A drifted co-writer is not the same outage as a down database or
    Redis — /health's overall status is unaffected; only the dedicated
    field carries the co-writer-specific signal."""
    clean_binary = tmp_path / "claude-clean"
    clean_binary.write_bytes(b"cli-build")
    clean_client, _ = make_test_app(tmp_path)
    _use_real_gate_with_fake_cli(
        monkeypatch, clean_binary, _init_line(sorted(provider._EXPECTED_MCP_TOOL_NAMES)),
    )
    with clean_client:
        clean_status = clean_client.get("/health").json()["status"]

    provider.clear_cli_tool_surface_cache()

    drifted_binary = tmp_path / "claude-drifted"
    drifted_binary.write_bytes(b"cli-build")
    drifted_client, _ = make_test_app(tmp_path)
    _use_real_gate_with_fake_cli(monkeypatch, drifted_binary, _init_line(["Bash"]))
    with drifted_client:
        drifted_body = drifted_client.get("/health").json()

    assert drifted_body["claude_cli_tool_surface"] == "drift"
    assert drifted_body["status"] == clean_status


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
