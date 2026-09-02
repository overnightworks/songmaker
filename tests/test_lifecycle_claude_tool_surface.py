"""Tests for the boot-time report on the Claude CLI's tool surface."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from songmaker_cli.claude.provider import CliToolSurfaceError, UnavailableError
from songmaker_cli.lifecycle import report_claude_cli_tool_surface


def _boot(caplog, verify: AsyncMock) -> tuple[str, str]:
    """Run the boot-time report and return (status, log text) — the status
    is what /health's claude_cli_tool_surface field shows (#351 round 6);
    the log text is what the boot log shows."""
    caplog.set_level("INFO")
    with patch(
        "songmaker_cli.claude.provider.verify_cli_tool_surface", verify,
    ):
        status = asyncio.run(report_claude_cli_tool_surface())
    return status, caplog.text


def test_boot_never_raises_even_when_the_allowlist_is_broken(caplog) -> None:
    """The operator's ruling (#351 round 6): the issue literally asked for
    an unknown tool to fail the server start; the operator overruled that
    once the allowlist gate itself was confirmed to cover every call
    path — a server refusing albums and playback over a co-writer
    problem is a worse outage than the co-writer being unavailable. The
    server must keep starting; only the co-writer path stays gated."""
    verify = AsyncMock(side_effect=CliToolSurfaceError("offers FutureTool"))

    status, text = _boot(caplog, verify)

    assert status == "drift"
    assert "FutureTool" in text
    assert any(record.levelname == "ERROR" for record in caplog.records)


def test_boot_log_stays_calm_when_no_cli_is_mounted(caplog) -> None:
    verify = AsyncMock(side_effect=UnavailableError("Claude CLI not found"))

    status, text = _boot(caplog, verify)

    # "Could not check" is its own state, not folded into either verified
    # outcome: not "drift" (no confirmed unexpected tool surface), and not
    # "ok" either (that claims the CLI was actually checked and found
    # clean, which did not happen here).
    assert status == "unverified"
    assert "not verified" in text
    assert all(record.levelname != "ERROR" for record in caplog.records)


def test_boot_log_confirms_a_clean_tool_surface(caplog) -> None:
    status, text = _boot(caplog, AsyncMock())

    assert status == "ok"
    assert "verified" in text
    assert all(record.levelname != "ERROR" for record in caplog.records)
