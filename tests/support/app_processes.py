"""Real songmaker web processes for tests that need more than one.

Each process starts through the CLI `server` command, as a deployment does, with its own
port, worker id and data directory, one shared audio directory, throwaway secrets, and the
database and Redis the case owns. Setting and variable names come from the settings classes.
"""

from __future__ import annotations

import ctypes
import os
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import IO, Final
from unittest.mock import patch

import httpx
import pytest
from pydantic_settings import BaseSettings

from acestep_worker.settings import WorkerSettings
from songmaker_cli.settings import Settings

HEALTH_PATH: Final = "/health"
READY_DEADLINE_SECONDS: Final = 60.0
READY_POLL_SECONDS: Final = 0.25
TERMINATE_DEADLINE_SECONDS: Final = 15.0
LOOPBACK: Final = "127.0.0.1"
PR_SET_PDEATHSIG: Final = 1
LOG_TAIL_BYTES: Final = 4000
# The test runner's variables a child needs to start and to be measured: the interpreter's
# search path and coverage's hook (`patch = subprocess` reads COVERAGE_*). Nothing else leaks in.
INHERITED_VARIABLES: Final = ("PATH", "HOME", "LANG", "VIRTUAL_ENV")
INHERITED_PREFIX: Final = "COVERAGE_"


def environment_name(settings_class: type[BaseSettings], field_name: str) -> str:
    """The variable a settings field is read from: its alias, else the upper-cased field name."""
    return settings_class.model_fields[field_name].alias or field_name.upper()


def die_with_parent(parent_pid: int) -> None:
    """Run in a forked child: die with the parent, or at once when it is already gone.

    The signal follows the thread that forked and arrives only when that parent dies after
    this call; a parent that died before it left the child reparented, so `getppid()` tells.
    """
    ctypes.CDLL(None, use_errno=True).prctl(PR_SET_PDEATHSIG, signal.SIGKILL)
    if os.getppid() != parent_pid:
        os.kill(os.getpid(), signal.SIGKILL)


def _free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as probe:
        probe.bind((LOOPBACK, 0))
        return probe.getsockname()[1]


@dataclass
class WebProcess:
    """One running `songmaker server` and the files it writes."""

    name: str
    port: int
    worker_id: str
    process: subprocess.Popen[bytes]
    log: IO[bytes]
    log_path: Path

    @property
    def url(self) -> str:
        return f"http://{LOOPBACK}:{self.port}"

    def log_text(self) -> str:
        self.log.flush()
        return self.log_path.read_text(encoding="utf-8", errors="replace")

    def log_tail(self) -> str:
        return self.log_text()[-LOG_TAIL_BYTES:]

    def kill(self) -> None:
        """End the process at once, as a crash does."""
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait()

    def stop(self) -> None:
        """Ask the process to end with SIGTERM, and kill it when the deadline passes."""
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=TERMINATE_DEADLINE_SECONDS)
            except subprocess.TimeoutExpired:
                self.kill()
        self.log.close()


class WebProcesses:
    """The processes of one case; they share a database, a Redis and an audio directory."""

    def __init__(self, root: Path, *, database_url: str, redis_url: str) -> None:
        self.root = root
        self.session_secret = secrets.token_hex(32)
        self.audio_dir = root / "audio"
        self.audio_dir.mkdir()
        self._shared_environment = self._settings_environment(database_url, redis_url)
        self._processes: list[WebProcess] = []

    def _settings_environment(self, database_url: str, redis_url: str) -> dict[str, str]:
        client_secret = self.root / "oidc-client-secret"
        client_secret.write_text(secrets.token_hex(16), encoding="utf-8")
        values = {
            "database_url": database_url,
            "redis_url": redis_url,
            "session_secret": self.session_secret,
            "songmaker_internal_token": secrets.token_hex(16),
            "oidc_issuer": "https://issuer.invalid/realms/test",
            "oidc_client_id": "songmaker-test",
            "oidc_client_secret_file": str(client_secret),
            "public_base_url": "https://songmaker.invalid",
            "allowed_hosts": LOOPBACK,
            "cookie_secure": "false",
            "audio_dir": str(self.audio_dir),
        }
        return {environment_name(Settings, field): value for field, value in values.items()}

    def settings(self) -> Settings:
        """The settings every process shares, read the way a process reads them."""
        with patch.dict(os.environ, self._shared_environment):
            return Settings()

    def start(self, name: str) -> WebProcess:
        """Start one process and return it once `/health` answers."""
        directory = self.root / name
        directory.mkdir()
        (directory / "pyproject.toml").write_text("[project]\nname = 'test'\n", encoding="utf-8")
        (directory / "frontend" / "build").mkdir(parents=True)
        (directory / "frontend" / "build" / "index.html").write_text(
            "<html></html>", encoding="utf-8",
        )
        worker_id = f"{name}-{uuid.uuid4().hex[:8]}"
        port = _free_port()
        data_dir = directory / "data"
        environment = {
            **_inherited_environment(),
            **self._shared_environment,
            environment_name(Settings, "data_dir"): str(data_dir),
            environment_name(WorkerSettings, "worker_id"): worker_id,
        }
        log_path = directory / "server.log"
        log = log_path.open("wb")
        process = subprocess.Popen(
            [
                sys.executable, "-m", "songmaker_cli.main", "server",
                "--port", str(port), "--root", str(directory),
            ],
            cwd=directory, env=environment, stdout=log, stderr=subprocess.STDOUT,
            preexec_fn=partial(die_with_parent, os.getpid()),  # noqa: PLW1509 - runs in the child
        )
        web_process = WebProcess(name, port, worker_id, process, log, log_path)
        self._processes.append(web_process)
        _wait_until_ready(web_process)
        return web_process

    def stop_all(self) -> None:
        for web_process in self._processes:
            web_process.stop()


def _inherited_environment() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if key in INHERITED_VARIABLES or key.startswith(INHERITED_PREFIX)
    }


def poll_until(
    condition: Callable[[], bool], *, deadline_seconds: float, poll_seconds: float = 0.1,
) -> bool:
    """Whether `condition` held before the deadline; it is checked once more at the deadline."""
    deadline = time.monotonic() + deadline_seconds
    pause = threading.Event()
    while not condition():
        if time.monotonic() >= deadline:
            return False
        pause.wait(poll_seconds)
    return True


def _wait_until_ready(web_process: WebProcess) -> None:
    deadline = time.monotonic() + READY_DEADLINE_SECONDS
    pause = threading.Event()
    while time.monotonic() < deadline:
        exit_code = web_process.process.poll()
        if exit_code is not None:
            pytest.fail(
                f"{web_process.name} exited with {exit_code} before it was ready:\n"
                f"{web_process.log_tail()}",
                pytrace=False,
            )
        try:
            if httpx.get(f"{web_process.url}{HEALTH_PATH}", timeout=2.0).status_code == 200:
                return
        except httpx.TransportError:
            pass
        pause.wait(READY_POLL_SECONDS)
    web_process.kill()
    pytest.fail(
        f"{web_process.name} did not answer {HEALTH_PATH} within {READY_DEADLINE_SECONDS} s:\n"
        f"{web_process.log_tail()}",
        pytrace=False,
    )


@contextmanager
def web_processes(
    root: Path, *, database_url: str, redis_url: str,
) -> Iterator[WebProcesses]:
    """The processes of one case; every one is ended when the case ends, however it ends."""
    cluster = WebProcesses(root, database_url=database_url, redis_url=redis_url)
    try:
        yield cluster
    finally:
        cluster.stop_all()

