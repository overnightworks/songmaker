from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from acestep_worker.constants import SECRET_ENV_KEYS
from acestep_worker.model_cache import LoadedModel
from acestep_worker.subprocess_runner import (
    SubprocessHandle,
    SubprocessStartError,
    _open_log_file,
    _read_stderr_tail,
    _stream_subprocess_logs,
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
    for key in SECRET_ENV_KEYS:
        monkeypatch.setenv(key, "leaked-value")
    env = build_env("sft", port=8101, vram_budget_gb=24.0)
    assert env["ACESTEP_API_PORT"] == "8101"
    assert env["ACESTEP_CONFIG_PATH"] == "acestep-v15-sft"
    for key in SECRET_ENV_KEYS:
        assert key not in env


def test_build_env_binds_configured_gpu() -> None:
    env = build_env("sft", port=8101, vram_budget_gb=24.0, gpu_id=1)
    assert env["CUDA_VISIBLE_DEVICES"] == "1"


def test_build_env_uses_worker_settings_defaults() -> None:
    env = build_env("sft", port=8101, vram_budget_gb=24.0)
    assert env["ACESTEP_DEVICE"] == "cuda"
    assert env["ACESTEP_INIT_LLM"] == "1"
    assert env["ACESTEP_LM_MODEL_PATH"] == "acestep-5Hz-lm-1.7B"
    assert env["ACESTEP_LM_BACKEND"] == "vllm"
    assert env["ACESTEP_COMPILE_MODEL"] == "0"
    assert env["PYTORCH_CUDA_ALLOC_CONF"] == "expandable_segments:True"


def test_build_env_takes_subprocess_knobs_from_worker_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ACESTEP_LM_BACKEND", "transformers")
    monkeypatch.setenv("ACESTEP_COMPILE_MODEL", "1")
    monkeypatch.setenv("ACESTEP_INIT_LLM", "0")
    monkeypatch.setenv("ACESTEP_LM_MODEL_PATH", "acestep-5Hz-lm-4B")
    env = build_env("sft", port=8101, vram_budget_gb=24.0)
    assert env["ACESTEP_LM_BACKEND"] == "transformers"
    assert env["ACESTEP_COMPILE_MODEL"] == "1"
    assert env["ACESTEP_INIT_LLM"] == "0"
    assert env["ACESTEP_LM_MODEL_PATH"] == "acestep-5Hz-lm-4B"


def test_build_env_vram_budget_wins_over_inherited_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAX_CUDA_VRAM", "8")
    env = build_env("sft", port=8101, vram_budget_gb=24.0)
    assert env["MAX_CUDA_VRAM"] == "24.0"


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


def test_wait_for_health_timeout_includes_log_tail(tmp_path: Path) -> None:
    proc = MagicMock()
    proc.poll.return_value = None
    log_path = tmp_path / "log"
    log_path.write_text("vllm: loading shard 2/4\nstuck waiting for cuda")
    handle = SubprocessHandle(process=proc, stderr_path=log_path, port=8101)
    times = iter([0.0, 100.0])
    with patch("acestep_worker.subprocess_runner.is_acestep_healthy", return_value=False):
        with pytest.raises(SubprocessStartError) as excinfo:
            wait_for_health(
                handle,
                timeout=10,
                sleeper=lambda _: None,
                clock=lambda: next(times),
            )
    msg = str(excinfo.value)
    assert "did not become healthy" in msg
    assert "last log lines" in msg
    assert "stuck waiting for cuda" in msg


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


def _proc_with_empty_stdout() -> MagicMock:
    proc = MagicMock()
    proc.pid = 1234
    proc.poll.return_value = None
    proc.stdout = MagicMock()
    proc.stdout.readline.side_effect = [b""]
    return proc


def test_start_acestep_subprocess_success(tmp_path: Path) -> None:
    proc = _proc_with_empty_stdout()
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
    assert handle.log_thread is not None


def test_start_acestep_health_failure_stops_process(tmp_path: Path) -> None:
    proc = _proc_with_empty_stdout()
    proc.pid = 1
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


def test_start_acestep_subprocess_uses_cwd(tmp_path: Path) -> None:
    proc = _proc_with_empty_stdout()
    proc.pid = 4242
    captured: dict = {}

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["cwd"] = kwargs.get("cwd")
        return proc

    with (
        patch("acestep_worker.subprocess_runner.find_uv", return_value=["uv"]),
        patch("subprocess.Popen", side_effect=fake_popen),
        patch("acestep_worker.subprocess_runner.wait_for_health"),
    ):
        start_acestep_subprocess(
            "sft",
            port=8101,
            checkpoint_dir=tmp_path,
            vram_budget_gb=24.0,
        )

    assert captured["cwd"] == tmp_path
    assert captured["cmd"] == ["uv", "run", "acestep-api", "--port", "8101"]


def _make_stop_proc(*, exit_code: int | None) -> MagicMock:
    proc = MagicMock()
    proc.poll.return_value = exit_code
    proc.pid = 1
    proc.stdout = MagicMock()
    return proc


def test_stop_acestep_subprocess_already_dead() -> None:
    proc = _make_stop_proc(exit_code=0)
    handle = SubprocessHandle(process=proc, stderr_path=None, port=8101)
    stop_acestep_subprocess(handle)
    proc.send_signal.assert_not_called()
    proc.stdout.close.assert_called_once()


def test_stop_acestep_subprocess_graceful() -> None:
    proc = _make_stop_proc(exit_code=None)
    handle = SubprocessHandle(process=proc, stderr_path=None, port=8101)
    stop_acestep_subprocess(handle)
    proc.send_signal.assert_called_once()
    proc.wait.assert_called()


def test_stop_acestep_subprocess_kills_on_timeout() -> None:
    proc = _make_stop_proc(exit_code=None)
    proc.wait.side_effect = [subprocess.TimeoutExpired("a", 1), None]
    handle = SubprocessHandle(process=proc, stderr_path=None, port=8101)
    stop_acestep_subprocess(handle)
    proc.kill.assert_called_once()


def test_stop_acestep_subprocess_handles_lookup_error() -> None:
    proc = _make_stop_proc(exit_code=None)
    proc.send_signal.side_effect = ProcessLookupError
    handle = SubprocessHandle(process=proc, stderr_path=None, port=8101)
    stop_acestep_subprocess(handle)


def test_stop_acestep_subprocess_handles_stdout_close_error() -> None:
    proc = _make_stop_proc(exit_code=0)
    proc.stdout.close.side_effect = OSError("io")
    handle = SubprocessHandle(process=proc, stderr_path=None, port=8101)
    stop_acestep_subprocess(handle)
    proc.stdout.close.assert_called_once()


def test_stop_acestep_subprocess_closes_stderr_file() -> None:
    proc = _make_stop_proc(exit_code=None)
    stderr_file = MagicMock()
    handle = SubprocessHandle(
        process=proc, stderr_path=None, port=8101, stderr_file=stderr_file
    )
    stop_acestep_subprocess(handle)
    stderr_file.close.assert_called_once()
    assert handle.stderr_file is None


def test_stop_acestep_subprocess_closes_stderr_when_already_dead() -> None:
    proc = _make_stop_proc(exit_code=0)
    stderr_file = MagicMock()
    handle = SubprocessHandle(
        process=proc, stderr_path=None, port=8101, stderr_file=stderr_file
    )
    stop_acestep_subprocess(handle)
    stderr_file.close.assert_called_once()


def test_stop_acestep_subprocess_handles_close_error() -> None:
    proc = _make_stop_proc(exit_code=0)
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


def test_make_acestep_runner_passes_on_log_line(tmp_path: Path) -> None:
    captured_kwargs: dict = {}
    fake_handle = SubprocessHandle(process=MagicMock(), stderr_path=None, port=8101)

    def fake_start(mode: str, **kwargs):
        captured_kwargs.update(kwargs)
        return fake_handle

    def sink(line: str) -> None:
        pass

    with patch(
        "acestep_worker.subprocess_runner.start_acestep_subprocess",
        side_effect=fake_start,
    ):
        loader, _ = make_acestep_runner(
            checkpoint_dir=tmp_path,
            base_port=8101,
            vram_budget_gb=24.0,
            on_log_line=sink,
        )
        _run(loader("sft"))
    assert captured_kwargs["on_log_line"] is sink


def test_make_acestep_runner_passes_gpu_id(tmp_path: Path) -> None:
    captured_kwargs: dict = {}
    fake_handle = SubprocessHandle(process=MagicMock(), stderr_path=None, port=8101)

    def fake_start(mode: str, **kwargs):
        captured_kwargs.update(kwargs)
        return fake_handle

    with patch(
        "acestep_worker.subprocess_runner.start_acestep_subprocess",
        side_effect=fake_start,
    ):
        loader, _ = make_acestep_runner(
            checkpoint_dir=tmp_path,
            base_port=8101,
            vram_budget_gb=24.0,
            gpu_id=1,
        )
        _run(loader("sft"))

    assert captured_kwargs["gpu_id"] == 1


def test_open_log_file_none_when_no_log_dir() -> None:
    path, handle = _open_log_file(None, "sft")
    assert path is None
    assert handle is None


def test_open_log_file_appends_with_header(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    path, handle = _open_log_file(log_dir, "sft")
    assert path is not None
    assert handle is not None
    handle.write("first attempt body\n")
    handle.close()

    path2, handle2 = _open_log_file(log_dir, "sft")
    assert path2 == path
    handle2.write("second attempt body\n")
    handle2.close()

    contents = path.read_text()
    assert contents.count("=== sft attempt at ") == 2
    assert "first attempt body" in contents
    assert "second attempt body" in contents


def test_stream_subprocess_logs_writes_to_file_and_callback(tmp_path: Path) -> None:
    proc = MagicMock()
    proc.stdout.readline.side_effect = [
        b"vllm: loading shard 1/4\n",
        b"vllm: loading shard 2/4\n",
        b"",
    ]
    log_path = tmp_path / "ace.log"
    log_handle = log_path.open("w", encoding="utf-8")
    captured: list[str] = []

    _stream_subprocess_logs(
        mode="sft",
        process=proc,
        log_file=log_handle,
        on_log_line=captured.append,
    )
    log_handle.close()

    assert captured == ["vllm: loading shard 1/4", "vllm: loading shard 2/4"]
    body = log_path.read_text()
    assert "shard 1/4" in body
    assert "shard 2/4" in body


def test_stream_subprocess_logs_swallows_callback_exception(tmp_path: Path) -> None:
    proc = MagicMock()
    proc.stdout.readline.side_effect = [b"line\n", b""]

    def boom(_: str) -> None:
        raise RuntimeError("nope")

    _stream_subprocess_logs(mode="sft", process=proc, log_file=None, on_log_line=boom)


def test_stream_subprocess_logs_skips_empty_lines() -> None:
    proc = MagicMock()
    proc.stdout.readline.side_effect = [b"\n", b"  ok\n", b""]
    captured: list[str] = []
    _stream_subprocess_logs(
        mode="sft", process=proc, log_file=None, on_log_line=captured.append,
    )
    assert captured == ["  ok"]


def test_stream_subprocess_logs_no_stdout_returns() -> None:
    proc = MagicMock()
    proc.stdout = None
    _stream_subprocess_logs(mode="sft", process=proc, log_file=None, on_log_line=None)


def test_stream_subprocess_logs_swallows_log_file_write_error() -> None:
    proc = MagicMock()
    proc.stdout.readline.side_effect = [b"line\n", b""]
    log_handle = MagicMock()
    log_handle.write.side_effect = OSError("disk full")
    captured: list[str] = []
    _stream_subprocess_logs(
        mode="sft", process=proc, log_file=log_handle, on_log_line=captured.append,
    )
    assert captured == ["line"]


def test_stream_subprocess_logs_swallows_outer_exception() -> None:
    proc = MagicMock()
    proc.stdout.readline.side_effect = RuntimeError("pipe exploded")
    _stream_subprocess_logs(mode="sft", process=proc, log_file=None, on_log_line=None)


def test_stop_acestep_subprocess_joins_log_thread() -> None:
    proc = _make_stop_proc(exit_code=None)
    fake_thread = MagicMock()
    fake_thread.is_alive.return_value = True
    handle = SubprocessHandle(
        process=proc, stderr_path=None, port=8101, log_thread=fake_thread,
    )
    stop_acestep_subprocess(handle)
    fake_thread.join.assert_called_once_with(timeout=2.0)
    assert handle.log_thread is None


def test_build_env_sets_pythonunbuffered() -> None:
    env = build_env("sft", port=8101, vram_budget_gb=24.0)
    assert env["PYTHONUNBUFFERED"] == "1"
