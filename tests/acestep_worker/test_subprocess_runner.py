from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from acestep_worker.model_cache import LoadedModel
from acestep_worker.subprocess_runner import (
    SubprocessHandle,
    SubprocessStartError,
    _read_stderr_tail,
    build_env,
    find_uv,
    is_acestep_healthy,
    make_acestep_runner,
    start_acestep_subprocess,
    stop_acestep_subprocess,
    wait_for_health,
)


def _run(coro):
    return asyncio.run(coro)


def test_find_uv_first_works() -> None:
    with patch("subprocess.run", return_value=MagicMock()):
        result = find_uv()
    assert result == ["uv"]


def test_find_uv_falls_back() -> None:
    calls = {"n": 0}

    def fake_run(cmd, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise FileNotFoundError
        return MagicMock()

    with patch("subprocess.run", side_effect=fake_run):
        result = find_uv()
    assert result is not None
    assert "uv" in result[0]


def test_find_uv_none_found() -> None:
    with patch("subprocess.run", side_effect=FileNotFoundError):
        result = find_uv()
    assert result is None


def test_find_uv_handles_timeout() -> None:
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("uv", 5)):
        result = find_uv()
    assert result is None


def test_build_env_unknown_mode() -> None:
    with pytest.raises(SubprocessStartError, match="Unknown mode"):
        build_env("ghost", port=8101, vram_budget_gb=24.0)


def test_build_env_strips_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret")
    monkeypatch.setenv("SESSION_SECRET", "secret2")
    monkeypatch.setenv("SONGMAKER_INTERNAL_TOKEN", "secret3")
    env = build_env("sft", port=8101, vram_budget_gb=24.0)
    assert env["ACESTEP_API_PORT"] == "8101"
    assert env["ACESTEP_CONFIG_PATH"] == "acestep-v15-sft"
    assert "ANTHROPIC_API_KEY" not in env
    assert "SESSION_SECRET" not in env
    assert "SONGMAKER_INTERNAL_TOKEN" not in env


def test_is_acestep_healthy_true() -> None:
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=False)
    with patch("acestep_worker.subprocess_runner.urlopen", return_value=mock_response):
        assert is_acestep_healthy(8101) is True


def test_is_acestep_healthy_false() -> None:
    with patch("acestep_worker.subprocess_runner.urlopen", side_effect=OSError("refused")):
        assert is_acestep_healthy(8101) is False


def test_wait_for_health_succeeds_immediately() -> None:
    handle = SubprocessHandle(process=MagicMock(), stderr_path=None, port=8101)
    sleeps: list[float] = []
    times = iter([0.0, 0.0])
    with patch("acestep_worker.subprocess_runner.is_acestep_healthy", return_value=True):
        wait_for_health(
            handle,
            timeout=10,
            sleeper=lambda s: sleeps.append(s),
            clock=lambda: next(times),
        )
    assert sleeps == []


def test_wait_for_health_timeout() -> None:
    proc = MagicMock()
    proc.poll.return_value = None
    handle = SubprocessHandle(process=proc, stderr_path=None, port=8101)
    times = iter([0.0, 1.0, 2.0, 100.0])
    sleeps: list[float] = []
    with patch("acestep_worker.subprocess_runner.is_acestep_healthy", return_value=False):
        with pytest.raises(SubprocessStartError, match="did not become healthy"):
            wait_for_health(
                handle,
                timeout=10,
                sleeper=lambda s: sleeps.append(s),
                clock=lambda: next(times),
            )
    assert sleeps


def test_wait_for_health_subprocess_died(tmp_path: Path) -> None:
    proc = MagicMock()
    proc.poll.return_value = 1
    stderr = tmp_path / "stderr.log"
    stderr.write_text("crash log")
    handle = SubprocessHandle(process=proc, stderr_path=stderr, port=8101)
    times = iter([0.0, 0.0])
    with patch("acestep_worker.subprocess_runner.is_acestep_healthy", return_value=False):
        with pytest.raises(SubprocessStartError, match="exited"):
            wait_for_health(
                handle,
                timeout=10,
                sleeper=lambda _: None,
                clock=lambda: next(times),
            )


def test_read_stderr_tail_none() -> None:
    assert _read_stderr_tail(None) == ""


def test_read_stderr_tail_missing(tmp_path: Path) -> None:
    assert _read_stderr_tail(tmp_path / "ghost") == ""


def test_read_stderr_tail_short(tmp_path: Path) -> None:
    p = tmp_path / "log"
    p.write_text("hi")
    assert _read_stderr_tail(p) == "hi"


def test_read_stderr_tail_long(tmp_path: Path) -> None:
    p = tmp_path / "log"
    p.write_text("x" * 1000)
    result = _read_stderr_tail(p, max_chars=100)
    assert len(result) == 100


def test_start_acestep_subprocess_no_uv(tmp_path: Path) -> None:
    with patch("acestep_worker.subprocess_runner.find_uv", return_value=None):
        with pytest.raises(SubprocessStartError, match="uv not found"):
            start_acestep_subprocess(
                "sft",
                port=8101,
                checkpoint_dir=tmp_path,
                vram_budget_gb=24.0,
            )


def test_start_acestep_subprocess_success(tmp_path: Path) -> None:
    proc = MagicMock()
    proc.pid = 1234
    proc.poll.return_value = None
    with (
        patch("acestep_worker.subprocess_runner.find_uv", return_value=["uv"]),
        patch("subprocess.Popen", return_value=proc),
        patch("acestep_worker.subprocess_runner.wait_for_health"),
    ):
        handle = start_acestep_subprocess(
            "sft",
            port=8101,
            checkpoint_dir=tmp_path,
            vram_budget_gb=24.0,
            log_dir=tmp_path / "logs",
        )
    assert handle.port == 8101
    assert handle.process is proc
    assert handle.stderr_path is not None


def test_start_acestep_health_failure_stops_process(tmp_path: Path) -> None:
    proc = MagicMock()
    proc.pid = 1
    proc.poll.return_value = None
    stops: list = []

    def fake_stop(handle: SubprocessHandle) -> None:
        stops.append(handle)

    with (
        patch("acestep_worker.subprocess_runner.find_uv", return_value=["uv"]),
        patch("subprocess.Popen", return_value=proc),
        patch(
            "acestep_worker.subprocess_runner.wait_for_health",
            side_effect=SubprocessStartError("nope"),
        ),
        patch("acestep_worker.subprocess_runner.stop_acestep_subprocess", side_effect=fake_stop),
    ):
        with pytest.raises(SubprocessStartError):
            start_acestep_subprocess(
                "sft",
                port=8101,
                checkpoint_dir=tmp_path,
                vram_budget_gb=24.0,
            )
    assert len(stops) == 1


def test_stop_acestep_subprocess_already_dead() -> None:
    proc = MagicMock()
    proc.poll.return_value = 0
    handle = SubprocessHandle(process=proc, stderr_path=None, port=8101)
    stop_acestep_subprocess(handle)
    proc.send_signal.assert_not_called()


def test_stop_acestep_subprocess_graceful() -> None:
    proc = MagicMock()
    proc.poll.return_value = None
    proc.pid = 1
    handle = SubprocessHandle(process=proc, stderr_path=None, port=8101)
    stop_acestep_subprocess(handle)
    proc.send_signal.assert_called_once()
    proc.wait.assert_called()


def test_stop_acestep_subprocess_kills_on_timeout() -> None:
    proc = MagicMock()
    proc.poll.return_value = None
    proc.pid = 1
    proc.wait.side_effect = [subprocess.TimeoutExpired("a", 1), None]
    handle = SubprocessHandle(process=proc, stderr_path=None, port=8101)
    stop_acestep_subprocess(handle)
    proc.kill.assert_called_once()


def test_stop_acestep_subprocess_handles_lookup_error() -> None:
    proc = MagicMock()
    proc.poll.return_value = None
    proc.pid = 1
    proc.send_signal.side_effect = ProcessLookupError
    handle = SubprocessHandle(process=proc, stderr_path=None, port=8101)
    stop_acestep_subprocess(handle)


def test_stop_acestep_subprocess_closes_stderr_file() -> None:
    proc = MagicMock()
    proc.poll.return_value = None
    proc.pid = 1
    stderr_file = MagicMock()
    handle = SubprocessHandle(
        process=proc, stderr_path=None, port=8101, stderr_file=stderr_file
    )
    stop_acestep_subprocess(handle)
    stderr_file.close.assert_called_once()
    assert handle.stderr_file is None


def test_stop_acestep_subprocess_closes_stderr_when_already_dead() -> None:
    proc = MagicMock()
    proc.poll.return_value = 0
    stderr_file = MagicMock()
    handle = SubprocessHandle(
        process=proc, stderr_path=None, port=8101, stderr_file=stderr_file
    )
    stop_acestep_subprocess(handle)
    stderr_file.close.assert_called_once()


def test_stop_acestep_subprocess_handles_close_error() -> None:
    proc = MagicMock()
    proc.poll.return_value = 0
    stderr_file = MagicMock()
    stderr_file.close.side_effect = OSError("io")
    handle = SubprocessHandle(
        process=proc, stderr_path=None, port=8101, stderr_file=stderr_file
    )
    stop_acestep_subprocess(handle)
    assert handle.stderr_file is None


def test_make_acestep_runner_loader_unloader(tmp_path: Path) -> None:
    fake_handle = SubprocessHandle(process=MagicMock(), stderr_path=None, port=8101)

    with patch(
        "acestep_worker.subprocess_runner.start_acestep_subprocess",
        return_value=fake_handle,
    ):
        loader, unloader = make_acestep_runner(
            checkpoint_dir=tmp_path,
            base_port=8101,
            vram_budget_gb=24.0,
        )
        loaded = _run(loader("sft"))
    assert isinstance(loaded, LoadedModel)
    assert loaded.mode == "sft"
    assert loaded.port == 8101
    assert loaded.handle is fake_handle

    stops: list = []
    with patch(
        "acestep_worker.subprocess_runner.stop_acestep_subprocess",
        side_effect=lambda h: stops.append(h),
    ):
        _run(unloader(loaded))
    assert stops == [fake_handle]


def test_make_acestep_runner_unload_non_handle(tmp_path: Path) -> None:
    _, unloader = make_acestep_runner(
        checkpoint_dir=tmp_path,
        base_port=8101,
        vram_budget_gb=24.0,
    )
    model = LoadedModel(mode="sft", handle="not-a-handle", port=8101)
    _run(unloader(model))
