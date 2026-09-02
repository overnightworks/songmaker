"""Tests for the /health endpoint."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

from conftest import make_test_app

from songmaker_cli.claude.provider import CliToolSurfaceError, UnavailableError


def test_health_reports_claude_cli_tool_surface_ok_by_default(tmp_path: Path) -> None:
    client, _ = make_test_app(tmp_path)

    with client:
        resp = client.get("/health")

    assert resp.status_code == 200
    assert resp.json()["claude_cli_tool_surface"] == "ok"


def test_health_reports_drift_without_failing_the_server(tmp_path: Path) -> None:
    """#351 round 6, Finding 1 / the operator's ruling: a drifted Claude
    CLI must not stop the server from starting or serving albums and
    playback — it must be visible on /health, not only in the boot log,
    so the operator and monitoring see it instead of just whichever
    musician opens a chat first and finds it broken."""
    client, _ = make_test_app(tmp_path)

    with (
        patch(
            "songmaker_cli.claude.provider.verify_cli_tool_surface",
            AsyncMock(side_effect=CliToolSurfaceError("offers FutureTool")),
        ),
        client,
    ):
        resp = client.get("/health")

    assert resp.status_code == 200
    assert resp.json()["claude_cli_tool_surface"] == "drift"


def test_health_reports_unverified_when_the_probe_itself_could_not_check(
    tmp_path: Path,
) -> None:
    """#351 round 6 follow-up: "could not check" (no CLI mounted, a
    timeout, a zombie, MCP never connecting — anything UnavailableError
    that is not a confirmed CliToolSurfaceError) is its own state, not
    silently folded into "ok". Reporting it as "ok" would be exactly the
    silent default check_no_silent_fallbacks.py exists to catch."""
    client, _ = make_test_app(tmp_path)

    with (
        patch(
            "songmaker_cli.claude.provider.verify_cli_tool_surface",
            AsyncMock(side_effect=UnavailableError("Claude CLI not found")),
        ),
        client,
    ):
        resp = client.get("/health")

    assert resp.status_code == 200
    assert resp.json()["claude_cli_tool_surface"] == "unverified"


def test_health_defaults_to_unverified_not_ok_when_the_state_was_never_set(
    tmp_path: Path,
) -> None:
    """The getattr default on app.state.claude_cli_tool_surface must not
    be "ok" — that would silently claim "checked and clean" for a state
    that was never actually checked. Simulates the boot-time report never
    having run by removing the attribute the real lifespan set."""
    client, _ = make_test_app(tmp_path)

    with client:
        del client.app.state.claude_cli_tool_surface
        resp = client.get("/health")

    assert resp.status_code == 200
    assert resp.json()["claude_cli_tool_surface"] == "unverified"


def test_health_drift_does_not_by_itself_mark_the_server_degraded(tmp_path: Path) -> None:
    """A drifted co-writer is not the same outage as a down database or
    Redis — /health's overall status is unaffected; only the dedicated
    field carries the co-writer-specific signal."""
    clean_client, _ = make_test_app(tmp_path)
    with clean_client:
        clean_status = clean_client.get("/health").json()["status"]

    drifted_client, _ = make_test_app(tmp_path)
    with (
        patch(
            "songmaker_cli.claude.provider.verify_cli_tool_surface",
            AsyncMock(side_effect=CliToolSurfaceError("offers FutureTool")),
        ),
        drifted_client,
    ):
        drifted_body = drifted_client.get("/health").json()

    assert drifted_body["claude_cli_tool_surface"] == "drift"
    assert drifted_body["status"] == clean_status
