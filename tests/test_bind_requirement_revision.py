from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).parents[1]
SCRIPTS = PROJECT_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import bind_requirement_revision as command  # noqa: E402
import requirement_binder as binder  # noqa: E402


class WaitingProcess:
    def __init__(self, *, require_kill: bool = False) -> None:
        self.pid = 4321
        self.require_kill = require_kill
        self.waits = 0
        self.returncode: int | None = None

    def wait(self, timeout: float | None = None) -> int:
        self.waits += 1
        if self.waits == 1 or (self.require_kill and self.waits == 2):
            raise subprocess.TimeoutExpired(["worker"], timeout)
        self.returncode = -9 if self.require_kill else -15
        return self.returncode

    def poll(self) -> int | None:
        return self.returncode


@pytest.mark.parametrize("require_kill", (False, True))
def test_supervisor_stops_the_complete_worker_group_at_its_wall_deadline(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    require_kill: bool,
) -> None:
    process = WaitingProcess(require_kill=require_kill)
    signals: list[tuple[int, int]] = []
    invocations: list[tuple[list[str], dict[str, Any]]] = []

    def fake_popen(arguments: list[str], **kwargs: Any) -> WaitingProcess:
        invocations.append((arguments, kwargs))
        return process

    monkeypatch.setattr(command.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(command.os, "killpg", lambda pid, sent: signals.append((pid, sent)))
    monkeypatch.setenv("GITHUB_TOKEN", "must-not-be-an-argument")

    result = command._supervise(
        [
            "--path",
            "docs/requirements/0001-albums.md",
            "--issue-number",
            "41",
            "--comment-id",
            "1001",
        ]
    )

    assert result == 2
    assert signals[0] == (4321, command.signal.SIGTERM)
    assert signals[-1] == (4321, command.signal.SIGKILL)
    assert invocations[0][1]["start_new_session"] is True
    assert invocations[0][1]["shell"] is False
    assert len(invocations[0][1]["pass_fds"]) == 1
    assert command.WORKER_GUARD_FLAG in invocations[0][0]
    assert "must-not-be-an-argument" not in " ".join(invocations[0][0])
    assert invocations[0][1]["env"]["GITHUB_TOKEN"] == "must-not-be-an-argument"
    assert "original, partial red, or fully prevalidated" in capsys.readouterr().err


def test_worker_reports_only_a_local_prepared_result(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    result = binder.BindingResult(
        "0001",
        "a" * 64,
        Path("docs/requirements/witnesses/1001.json"),
        "b" * 40,
    )
    monkeypatch.setattr(command.HttpsGitHubClient, "from_environment", lambda: object())

    def bind(*_args: Any, **kwargs: Any) -> binder.BindingResult:
        kwargs["on_prepared"](result)
        return result

    monkeypatch.setattr(command, "bind_requirement_revision", bind)
    arguments = argparse.Namespace(
        path="docs/requirements/0001-albums.md",
        issue_number=41,
        comment_id=1001,
        private_bind_worker=True,
    )

    assert command._worker(arguments) == 0
    output = capsys.readouterr().out
    assert "Local binding prepared" in output
    assert "Review the complete diff" in output
    assert "commit and push" in output
    assert "treating it as landed" in output


def test_worker_distinguishes_manual_recovery_from_safe_refusal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(command.HttpsGitHubClient, "from_environment", lambda: object())
    arguments = argparse.Namespace(
        path="docs/requirements/0001-albums.md",
        issue_number=41,
        comment_id=1001,
        private_bind_worker=True,
    )

    def recovery(*_args: Any, **_kwargs: Any) -> binder.BindingResult:
        raise binder.RequirementBinderRecoveryError("inspect exact bytes")

    monkeypatch.setattr(command, "bind_requirement_revision", recovery)
    assert command._worker(arguments) == 2
    assert "recovery required" in capsys.readouterr().err

    def refusal(*_args: Any, **_kwargs: Any) -> binder.BindingResult:
        raise binder.RequirementBinderError("candidate is dirty")

    monkeypatch.setattr(command, "bind_requirement_revision", refusal)
    assert command._worker(arguments) == 1
    assert "bind refused" in capsys.readouterr().err


def test_parent_guard_terminates_the_worker_group_when_the_supervisor_disappears(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guard_read, guard_write = os.pipe()
    signalled = threading.Event()
    signals: list[tuple[int, int]] = []

    def signal_group(pid: int, sent: int) -> None:
        signals.append((pid, sent))
        signalled.set()

    monkeypatch.setattr(command.os, "killpg", signal_group)
    assert command._start_parent_guard(guard_read)

    os.close(guard_write)

    assert signalled.wait(timeout=1.0)
    assert signals == [(os.getpgrp(), command.signal.SIGKILL)]


def test_private_worker_mode_refuses_a_missing_parent_guard(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        command.sys,
        "argv",
        [
            "bind_requirement_revision.py",
            "--path",
            "docs/requirements/0001-albums.md",
            "--issue-number",
            "41",
            "--comment-id",
            "1001",
            command.WORKER_FLAG,
        ],
    )
    monkeypatch.setattr(
        command,
        "_worker",
        lambda _arguments: pytest.fail("unguarded worker must not run"),
    )

    assert command.main() == 1
    assert "private worker guard is absent" in capsys.readouterr().err
