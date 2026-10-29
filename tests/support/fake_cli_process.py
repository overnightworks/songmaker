"""A pipe-backed stand-in for the ``subprocess.Popen`` handle of an agent CLI."""

from __future__ import annotations

import os
from unittest.mock import MagicMock

_fake_cli_processes: list[MagicMock] = []


def close_fake_cli_processes() -> None:
    """Close the pipe-backed streams of every process built since the last close."""
    for proc in _fake_cli_processes:
        for stream_name in (
            "stdin", "stdout", "stderr", "_stdin_reader", "_stdout_writer", "_stderr_writer",
        ):
            stream = getattr(proc, stream_name)
            if not stream.closed:
                stream.close()
    _fake_cli_processes.clear()


def fake_cli_process(
    first_line: bytes | None, *, still_running: bool = False, stdin_blocked: bool = False,
) -> MagicMock:
    """Build a pipe-backed stand-in for the ``subprocess.Popen`` CLI handle."""
    proc = MagicMock()
    proc.pid = 4343
    proc.poll.return_value = None if still_running else 0
    stdin_reader, stdin_writer = os.pipe()
    stdout_reader, stdout_writer = os.pipe()
    stderr_reader, stderr_writer = os.pipe()
    proc.stdin = os.fdopen(stdin_writer, "wb", buffering=0)
    proc.stdout = os.fdopen(stdout_reader, "rb", buffering=0)
    proc.stderr = os.fdopen(stderr_reader, "rb", buffering=0)
    proc._stdin_reader = os.fdopen(stdin_reader, "rb", buffering=0)
    proc._stdout_writer = os.fdopen(stdout_writer, "wb", buffering=0)
    proc._stderr_writer = os.fdopen(stderr_writer, "wb", buffering=0)
    proc._stderr_writer.close()
    if stdin_blocked:
        os.set_blocking(proc.stdin.fileno(), False)
        try:
            while True:
                os.write(proc.stdin.fileno(), b"x" * 65536)
        except BlockingIOError:
            pass
    if first_line is not None:
        proc._stdout_writer.write(first_line)
        proc._stdout_writer.close()
    proc.wait.return_value = None
    _fake_cli_processes.append(proc)
    return proc
