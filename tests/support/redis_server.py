"""Owned Redis process for wire-protocol integration tests."""

import subprocess
import time
from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from redis import Redis
from redis.exceptions import ConnectionError


@pytest.fixture
def redis_socket(tmp_path: Path) -> Iterator[Path]:
    """1301-F1-CODEC-LEGACY: isolate Redis and reap it even on test failure."""
    # Linux limits Unix socket paths to 107 bytes; worktree paths can exceed that.
    with (
        TemporaryDirectory(prefix="arq-", dir="/tmp") as socket_dir,
        (tmp_path / "redis.log").open("w+") as log,
    ):
        socket = Path(socket_dir) / "redis.sock"
        process = subprocess.Popen(
            [
                "redis-server",
                "--port",
                "0",
                "--unixsocket",
                str(socket),
                "--unixsocketperm",
                "700",
                "--save",
                "",
                "--appendonly",
                "no",
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        client = Redis(unix_socket_path=str(socket), socket_timeout=1)
        try:
            deadline = time.monotonic() + 5
            while True:
                if process.poll() is not None:
                    log.seek(0)
                    pytest.fail(f"Redis exited during startup: {log.read()}")
                try:
                    if client.ping():
                        break
                except ConnectionError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.02)
            yield socket
        finally:
            client.close()
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
