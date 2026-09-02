"""Tests for the /health endpoint."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

from conftest import make_test_app

from songmaker_cli.claude.provider import CliToolSurfaceError


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
