"""Tests for the boot-time report on the Claude CLI's tool surface."""

from __future__ import annotations

import asyncio
import subprocess
from unittest.mock import AsyncMock, patch

import pytest

from songmaker_cli.claude.provider import CliToolSurfaceError, UnavailableError
from songmaker_cli.lifecycle import (
    codex_image_sandbox_runtime_health,
    record_codex_image_sandbox_runtime_health,
    report_claude_cli_tool_surface,
    report_codex_image_sandbox_runtime,
)


@pytest.fixture(autouse=True)
def _reset_codex_image_sandbox_runtime_health():
    """codex_image_sandbox_runtime_health() is a module-level live value,
    not scoped to a single test the way most fixtures are — reset it
    around every test in this file so one test's recorded verdict can't
    leak into the next (see test_health_api.py's analogous fixture for
    the claude_cli_tool_surface state)."""
    record_codex_image_sandbox_runtime_health("unverified")
    yield
    record_codex_image_sandbox_runtime_health("unverified")


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


def test_boot_marks_the_future_codex_cover_path_not_set_up_without_stopping(caplog) -> None:
    """Also proves the boot report publishes its verdict as the live
    /health state (codex_image_sandbox_runtime_health(), #789) — not a
    value frozen at whatever the process saw first."""
    caplog.set_level("INFO")
    completed = subprocess.CompletedProcess(args=(), returncode=1)
    with patch("songmaker_cli.lifecycle.shutil.which", return_value="/usr/bin/bwrap"), patch(
        "songmaker_cli.lifecycle.subprocess.run", return_value=completed,
    ):
        status = report_codex_image_sandbox_runtime()

    assert status == "not_set_up"
    assert "Codex cover image path not set up" in caplog.text
    assert codex_image_sandbox_runtime_health() == "not_set_up"


def test_boot_confirms_the_codex_cover_sandbox_runtime(caplog) -> None:
    """Also proves the boot report publishes its verdict as the live
    /health state (codex_image_sandbox_runtime_health(), #789)."""
    caplog.set_level("INFO")
    completed = subprocess.CompletedProcess(args=(), returncode=0)
    with patch("songmaker_cli.lifecycle.shutil.which", return_value="/usr/bin/bwrap"), patch(
        "songmaker_cli.lifecycle.subprocess.run", side_effect=(completed, completed),
    ):
        status = report_codex_image_sandbox_runtime()

    assert status == "ready"
    assert "Codex cover image sandbox runtime verified" in caplog.text
    assert codex_image_sandbox_runtime_health() == "ready"


def test_boot_report_overrides_an_earlier_recorded_state() -> None:
    """A later boot report replaces an earlier one instead of /health
    staying stuck at whatever the process first recorded."""
    with patch("songmaker_cli.lifecycle.shutil.which", return_value=None):
        report_codex_image_sandbox_runtime()
    assert codex_image_sandbox_runtime_health() == "not_set_up"

    completed = subprocess.CompletedProcess(args=(), returncode=0)
    with patch("songmaker_cli.lifecycle.shutil.which", return_value="/usr/bin/bwrap"), patch(
        "songmaker_cli.lifecycle.subprocess.run", side_effect=(completed, completed),
    ):
        report_codex_image_sandbox_runtime()

    assert codex_image_sandbox_runtime_health() == "ready"


def test_codex_cover_startup_probe_uses_codex_embedded_bubblewrap_argv() -> None:
    completed = subprocess.CompletedProcess(args=(), returncode=0)
    with patch("songmaker_cli.lifecycle.shutil.which", return_value="/usr/bin/bwrap"), patch(
        "songmaker_cli.lifecycle.subprocess.run", side_effect=(completed, completed),
    ) as run:
        report_codex_image_sandbox_runtime()

    assert run.call_args_list[0].args[0] == (
        "/usr/bin/bwrap",
        "--unshare-user",
        "--unshare-net",
        "--ro-bind", "/", "/",
        "/bin/true",
    )
    assert run.call_args_list[1].args[0] == (
        "/usr/bin/bwrap",
        "--new-session",
        "--die-with-parent",
        "--tmpfs", "/",
        "--dev", "/dev",
        "--ro-bind", "/bin", "/bin",
        "--ro-bind", "/etc", "/etc",
        "--ro-bind", "/lib", "/lib",
        "--ro-bind", "/lib64", "/lib64",
        "--ro-bind", "/sbin", "/sbin",
        "--ro-bind", "/usr", "/usr",
        "--unshare-user",
        "--unshare-pid",
        "--unshare-net",
        "--proc", "/proc",
        "--",
        "/usr/bin/true",
    )


def test_boot_requires_the_per_run_codex_startup_probe(caplog) -> None:
    caplog.set_level("INFO")
    completed = subprocess.CompletedProcess(args=(), returncode=0)
    failed = subprocess.CompletedProcess(args=(), returncode=1)
    with patch("songmaker_cli.lifecycle.shutil.which", return_value="/usr/bin/bwrap"), patch(
        "songmaker_cli.lifecycle.subprocess.run", side_effect=(completed, failed),
    ):
        status = report_codex_image_sandbox_runtime()

    assert status == "not_set_up"


@pytest.mark.parametrize(
    "probe_error",
    [OSError("bwrap not executable"), subprocess.TimeoutExpired(cmd="bwrap", timeout=5)],
    ids=["oserror", "timeout"],
)
def test_boot_marks_the_codex_cover_path_not_set_up_when_the_probe_raises(
    caplog, probe_error: Exception,
) -> None:
    caplog.set_level("INFO")
    with patch("songmaker_cli.lifecycle.shutil.which", return_value="/usr/bin/bwrap"), patch(
        "songmaker_cli.lifecycle.subprocess.run", side_effect=probe_error,
    ):
        status = report_codex_image_sandbox_runtime()

    assert status == "not_set_up"
    assert "bubblewrap user namespaces are unavailable" in caplog.text
