from __future__ import annotations

import asyncio
import signal
import subprocess
from collections import deque
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from acestep_engine.constants import MODEL_CONFIG_PATHS
from acestep_worker.constants import SECRET_ENV_KEYS
from acestep_worker.model_cache import LoadedModel
from acestep_worker.subprocess_runner import (
    SubprocessHandle,
    SubprocessStartError,
    _stream_subprocess_logs,
    build_env,
    find_uv,
    inner_port_for_mode,
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


def test_build_env_strips_mismatched_virtual_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIRTUAL_ENV", "/app/.venv")
    env = build_env("sft", port=8101, vram_budget_gb=24.0)
    assert "VIRTUAL_ENV" not in env


def test_build_env_binds_configured_gpu() -> None:
    env = build_env("sft", port=8101, vram_budget_gb=24.0, gpu_id=1)
    assert env["CUDA_VISIBLE_DEVICES"] == "1"


def test_build_env_uses_worker_settings_defaults() -> None:
    env = build_env("sft", port=8101, vram_budget_gb=24.0)
    assert env["ACESTEP_DEVICE"] == "cuda"
    assert env["ACESTEP_INIT_LLM"] == "1"
    assert env["ACESTEP_LM_MODEL_PATH"] == "acestep-5Hz-lm-4B"
    assert env["ACESTEP_LM_BACKEND"] == "vllm"
    assert env["ACESTEP_COMPILE_MODEL"] == "0"
    assert env["PYTORCH_CUDA_ALLOC_CONF"] == "expandable_segments:True"


def test_build_env_loads_the_models_before_the_child_serves() -> None:
    env = build_env("sft", port=8101, vram_budget_gb=24.0)
    assert env["ACESTEP_NO_INIT"] == "0"


def test_build_env_takes_subprocess_knobs_from_worker_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ACESTEP_LM_BACKEND", "transformers")
    monkeypatch.setenv("ACESTEP_COMPILE_MODEL", "1")
    monkeypatch.setenv("ACESTEP_INIT_LLM", "0")
    monkeypatch.setenv("ACESTEP_LM_MODEL_PATH", "acestep-5Hz-lm-1.7B")
    env = build_env("sft", port=8101, vram_budget_gb=24.0)
    assert env["ACESTEP_LM_BACKEND"] == "transformers"
    assert env["ACESTEP_COMPILE_MODEL"] == "1"
    assert env["ACESTEP_INIT_LLM"] == "0"
    assert env["ACESTEP_LM_MODEL_PATH"] == "acestep-5Hz-lm-1.7B"


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
    handle = SubprocessHandle(process=MagicMock(), port=8101)
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
    handle = SubprocessHandle(process=proc, port=8101)
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


def _handle_after_child_output(process: MagicMock, *lines: bytes) -> SubprocessHandle:
    process.stdout.readline.side_effect = [*(line + b"\n" for line in lines), b""]
    handle = SubprocessHandle(process=process, port=8101)
    _stream_subprocess_logs(
        mode="sft", process=process, recent_lines=handle.recent_lines, on_log_line=None,
    )
    return handle


def test_wait_for_health_timeout_includes_log_tail() -> None:
    proc = MagicMock()
    proc.poll.return_value = None
    handle = _handle_after_child_output(proc, b"vllm: loading shard 2/4", b"stuck waiting for cuda")
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


def test_wait_for_health_subprocess_died_carries_last_lines() -> None:
    proc = MagicMock()
    proc.poll.return_value = 1
    handle = _handle_after_child_output(proc, b"crash log")
    times = iter([0.0, 0.0])
    with patch("acestep_worker.subprocess_runner.is_acestep_healthy", return_value=False):
        with pytest.raises(SubprocessStartError, match="exited: crash log"):
            wait_for_health(
                handle,
                timeout=10,
                sleeper=lambda _: None,
                clock=lambda: next(times),
            )


def test_failed_start_keeps_only_the_newest_lines_past_the_bound() -> None:
    proc = MagicMock()
    proc.poll.return_value = 1
    handle = _handle_after_child_output(
        proc, *(f"line {number}".encode() for number in range(200)),
    )
    with patch("acestep_worker.subprocess_runner.is_acestep_healthy", return_value=False):
        with pytest.raises(SubprocessStartError) as excinfo:
            wait_for_health(handle, timeout=10, clock=iter([0.0, 0.0]).__next__)
    assert "line 199" in str(excinfo.value)
    assert "line 0\n" not in str(excinfo.value)
    assert len(handle.recent_lines) < 200


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
        )
    assert handle.port == 8101
    assert handle.process is proc
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


class _StopProcess:
    pid = 1

    def __init__(self, outcome: str, stdout: BytesIO) -> None:
        self.outcome = outcome
        self.stdout = stdout
        self.returncode = 0 if outcome == "already-exited" else None
        self.reaped = self.returncode is not None

    def poll(self) -> int | None:
        return self.returncode

    def send_signal(self, sig: int) -> None:
        if self.returncode is not None:
            raise AssertionError("An exited process must not be signalled")
        if self.outcome == "lookup-race":
            self.returncode = 0
            self.reaped = True
            raise ProcessLookupError
        if self.outcome != "timeout":
            self.returncode = -sig

    def wait(self, timeout: float) -> int:
        if self.returncode is None:
            raise subprocess.TimeoutExpired("acestep", timeout)
        self.reaped = True
        return self.returncode

    def kill(self) -> None:
        self.returncode = -signal.SIGKILL


class _CloseErrorBytesIO(BytesIO):
    def close(self) -> None:
        super().close()
        raise OSError("stdout close failed")


class _DrainingLogThread:
    def __init__(self) -> None:
        self.pending = "last log line"

    def is_alive(self) -> bool:
        return bool(self.pending)

    def join(self, timeout: float) -> None:
        self.pending = ""


@pytest.mark.parametrize(
    ("outcome", "expected_exit"),
    [
        ("already-exited", 0),
        ("graceful", -signal.SIGTERM),
        ("timeout", -signal.SIGKILL),
        ("lookup-race", 0),
    ],
)
@pytest.mark.parametrize("close_error", [None, "stdout"])
def test_stop_terminates_and_reaps_process_and_releases_resources(
    outcome: str, expected_exit: int, close_error: str | None,
) -> None:
    """1346-F4-stop, 1346-F5-cleanup: exit and cleanup survive races and I/O errors."""
    stdout = _CloseErrorBytesIO() if close_error == "stdout" else BytesIO()
    process = _StopProcess(outcome, stdout)
    log_thread = _DrainingLogThread()
    handle = SubprocessHandle(
        process=process, port=8101, log_thread=log_thread,
    )

    stop_acestep_subprocess(handle)

    assert process.poll() == expected_exit
    assert process.reaped
    assert stdout.closed
    assert not log_thread.is_alive()
    assert handle.log_thread is None


def test_make_acestep_runner_loader_unloader(tmp_path: Path) -> None:
    expected_port = inner_port_for_mode(8101, "sft")
    fake_handle = SubprocessHandle(process=MagicMock(), port=expected_port)

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
    assert loaded.port == expected_port
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


def test_inner_port_for_mode_unknown_mode_raises() -> None:
    with pytest.raises(SubprocessStartError, match="Unknown mode"):
        inner_port_for_mode(8101, "ghost")


@pytest.mark.parametrize("mode", list(MODEL_CONFIG_PATHS))
def test_make_acestep_runner_derives_a_distinct_port_per_mode(
    tmp_path: Path, mode: str,
) -> None:
    """Regression pin for #205: each mode must get its own inner port so a
    second load's health check can never be satisfied by a different mode's
    still-running server."""
    expected_port = inner_port_for_mode(8101, mode)
    captured_ports: list[int] = []

    def fake_start(mode_arg: str, **kwargs):
        captured_ports.append(kwargs["port"])
        return SubprocessHandle(process=MagicMock(), port=kwargs["port"])

    with patch(
        "acestep_worker.subprocess_runner.start_acestep_subprocess",
        side_effect=fake_start,
    ):
        loader, _ = make_acestep_runner(
            checkpoint_dir=tmp_path, base_port=8101, vram_budget_gb=24.0,
        )
        loaded = _run(loader(mode))

    assert captured_ports == [expected_port]
    assert loaded.port == expected_port


def test_two_different_modes_get_two_different_ports(tmp_path: Path) -> None:
    started_ports: list[int] = []

    def fake_start(mode_arg: str, **kwargs):
        started_ports.append(kwargs["port"])
        return SubprocessHandle(process=MagicMock(), port=kwargs["port"])

    with patch(
        "acestep_worker.subprocess_runner.start_acestep_subprocess",
        side_effect=fake_start,
    ):
        loader, _ = make_acestep_runner(
            checkpoint_dir=tmp_path, base_port=8101, vram_budget_gb=24.0,
        )
        loaded_turbo = _run(loader("turbo"))
        loaded_sft = _run(loader("sft"))

    assert loaded_turbo.port != loaded_sft.port
    assert started_ports[0] != started_ports[1]


def test_second_mode_load_is_not_fooled_by_first_modes_leftover_health(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression pin for #205.

    Before the fix every mode shared one inner port, so loading a second
    mode's health check saw the FIRST mode's still-running server answer
    200 and reported itself ready — even though its own subprocess never
    bound the port (EADDRINUSE). This test fails red against the pre-fix
    code (which always requests ``base_port`` regardless of mode, so the
    stale 200 makes the second load succeed instantly) and passes green
    once each mode gets its own port and must wait out its own timeout.

    Mutation check: reverting subprocess_runner.py's loader to
    ``port=base_port`` turns this red again — verified locally.
    """
    monkeypatch.setenv("ACESTEP_STARTUP_TIMEOUT_SECONDS", "1")
    monkeypatch.setenv("ACESTEP_HEALTH_POLL_SECONDS", "0.05")

    proc_turbo = _proc_with_empty_stdout()
    proc_turbo.pid = 111
    proc_sft = _proc_with_empty_stdout()
    proc_sft.pid = 222
    procs = iter([proc_turbo, proc_sft])

    healthy_ports = {inner_port_for_mode(8101, "turbo")}

    def fake_is_healthy(port: int, timeout: float = 5.0) -> bool:
        return port in healthy_ports

    with (
        patch("acestep_worker.subprocess_runner.find_uv", return_value=["uv"]),
        patch("subprocess.Popen", side_effect=lambda *a, **k: next(procs)),
        patch(
            "acestep_worker.subprocess_runner.is_acestep_healthy",
            side_effect=fake_is_healthy,
        ),
    ):
        loader, _ = make_acestep_runner(
            checkpoint_dir=tmp_path, base_port=8101, vram_budget_gb=24.0,
        )
        loaded_turbo = _run(loader("turbo"))
        assert loaded_turbo.port == 8101

        load_operation = loader("sft")
        with pytest.raises(SubprocessStartError, match="did not become healthy"):
            _run(load_operation)


def test_make_acestep_runner_passes_on_log_line(tmp_path: Path) -> None:
    captured_kwargs: dict = {}
    fake_handle = SubprocessHandle(process=MagicMock(), port=8101)

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
    fake_handle = SubprocessHandle(process=MagicMock(), port=8101)

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


def test_stream_subprocess_logs_keeps_recent_lines_and_calls_back() -> None:
    proc = MagicMock()
    proc.stdout.readline.side_effect = [
        b"vllm: loading shard 1/4\n",
        b"vllm: loading shard 2/4\n",
        b"",
    ]
    recent_lines: deque[str] = deque(maxlen=50)
    captured: list[str] = []

    _stream_subprocess_logs(
        mode="sft",
        process=proc,
        recent_lines=recent_lines,
        on_log_line=captured.append,
    )

    assert captured == ["vllm: loading shard 1/4", "vllm: loading shard 2/4"]
    assert list(recent_lines) == captured


def test_stream_subprocess_logs_swallows_callback_exception(tmp_path: Path) -> None:
    proc = MagicMock()
    proc.stdout.readline.side_effect = [b"line\n", b""]

    def boom(_: str) -> None:
        raise RuntimeError("nope")

    _stream_subprocess_logs(mode="sft", process=proc, recent_lines=deque(), on_log_line=boom)


def test_stream_subprocess_logs_skips_empty_lines() -> None:
    proc = MagicMock()
    proc.stdout.readline.side_effect = [b"\n", b"  ok\n", b""]
    captured: list[str] = []
    _stream_subprocess_logs(
        mode="sft", process=proc, recent_lines=deque(), on_log_line=captured.append,
    )
    assert captured == ["  ok"]


def test_stream_subprocess_logs_no_stdout_returns() -> None:
    proc = MagicMock()
    proc.stdout = None
    _stream_subprocess_logs(mode="sft", process=proc, recent_lines=deque(), on_log_line=None)


def test_stream_subprocess_logs_swallows_outer_exception() -> None:
    proc = MagicMock()
    proc.stdout.readline.side_effect = RuntimeError("pipe exploded")
    _stream_subprocess_logs(mode="sft", process=proc, recent_lines=deque(), on_log_line=None)


def test_build_env_sets_pythonunbuffered() -> None:
    env = build_env("sft", port=8101, vram_budget_gb=24.0)
    assert env["PYTHONUNBUFFERED"] == "1"
