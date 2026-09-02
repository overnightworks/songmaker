"""Tests for the /health endpoint."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from conftest import make_test_app

from songmaker_cli.claude import provider
from songmaker_cli.claude.provider import verify_cli_tool_surface as _real_verify_cli_tool_surface


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
    tmp_path: Path, monkeypatch,
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


def test_health_reports_drift_without_failing_the_server(tmp_path: Path, monkeypatch) -> None:
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
    tmp_path: Path, monkeypatch,
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
    tmp_path: Path,
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


def test_health_reports_the_gates_most_recent_verdict_not_a_boot_snapshot(
    tmp_path: Path, monkeypatch,
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
    tmp_path: Path, monkeypatch,
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
