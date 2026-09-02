"""Tests for the boot-time report on the Claude CLI's tool surface."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from songmaker_cli.claude.provider import CliToolSurfaceError, UnavailableError
from songmaker_cli.lifecycle import report_claude_cli_tool_surface


def _boot_log(caplog, verify: AsyncMock) -> str:
    caplog.set_level("INFO")
    with patch(
        "songmaker_cli.claude.provider.verify_cli_tool_surface", verify,
    ):
        asyncio.run(report_claude_cli_tool_surface())
    return caplog.text


def test_boot_log_names_the_tool_that_broke_the_allowlist(caplog) -> None:
    verify = AsyncMock(side_effect=CliToolSurfaceError("offers FutureTool"))

    text = _boot_log(caplog, verify)

    assert "FutureTool" in text
    assert any(record.levelname == "ERROR" for record in caplog.records)


def test_boot_log_stays_calm_when_no_cli_is_mounted(caplog) -> None:
    verify = AsyncMock(side_effect=UnavailableError("Claude CLI not found"))

    text = _boot_log(caplog, verify)

    assert "not verified" in text
    assert all(record.levelname != "ERROR" for record in caplog.records)


def test_boot_log_confirms_a_clean_tool_surface(caplog) -> None:
    text = _boot_log(caplog, AsyncMock())

    assert "verified" in text
    assert all(record.levelname != "ERROR" for record in caplog.records)
