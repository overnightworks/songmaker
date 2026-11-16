"""Real songmaker web and music-worker processes for tests that need more than one.

A web process starts through the CLI `server` command and a music worker through the arq
launcher, as a deployment does, each with its own data directory, one shared audio directory,
throwaway secrets, and the database and Redis the case owns; a web process also has its own
port and worker id. Setting and variable names come from the settings classes. A case may add
`StandIns`: a gateway origin, and an HTTPS issuer whose certificate the children trust through
`SSL_CERT_FILE`.
"""

from __future__ import annotations

import asyncio
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
from collections.abc import Awaitable, Callable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import IO, Final, TypeVar
from unittest.mock import patch

import httpx
import pytest
from pydantic_settings import BaseSettings
from redis import Redis
from redis.asyncio import Redis as AsyncRedis
from support.cowriter_gateway import agent_config
from support.owner_lease_epoch import aged_owner_lease_epoch
from tandem import Leases

from acestep_worker.settings import WorkerSettings
from songmaker_cli.settings import Settings
from songmaker_cli.worker_liveness import owner_leases

T = TypeVar("T")

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
OIDC_CLIENT_ID: Final = "songmaker-test"
TRUSTED_CERTIFICATES_VARIABLE: Final = "SSL_CERT_FILE"
MUSIC_WORKER_SETTINGS: Final = "songmaker_cli.music_worker.MusicWorkerSettings"


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


@dataclass(frozen=True)
class StandIns:
    """What the children reach instead of a deployment's gateway and realm."""

    gateway_origin: str
    issuer_url: str
    issuer_certificate: Path


@dataclass
class ChildProcess:
    """One running child and the log it writes."""

    name: str
    process: subprocess.Popen[bytes]
    log: IO[bytes]
    log_path: Path

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


@dataclass
class WebProcess(ChildProcess):
    """One running `songmaker server`."""

    port: int
    worker_id: str

    @property
    def url(self) -> str:
        return f"http://{LOOPBACK}:{self.port}"


@dataclass
class MusicWorkerProcess(ChildProcess):
    """One running music worker and the owner id its lease names."""

    owner_id: str


class WebProcesses:
    """The processes of one case; they share a database, a Redis and an audio directory.

    A web process and a music worker answer to the same case, so a test may run either or both.
    """

    def __init__(
        self, root: Path, *, database_url: str, redis_url: str, stand_ins: StandIns | None = None,
    ) -> None:
        self.root = root
        self._stand_ins = stand_ins
        self.session_secret = secrets.token_hex(32)
        self.audio_dir = root / "audio"
        self.audio_dir.mkdir()
        self._redis = Redis.from_url(redis_url, decode_responses=True)
        self._shared_environment = self._settings_environment(database_url, redis_url)
        self._processes: list[ChildProcess] = []

    def _settings_environment(self, database_url: str, redis_url: str) -> dict[str, str]:
        client_secret = self.root / "oidc-client-secret"
        client_secret.write_text(secrets.token_hex(16), encoding="utf-8")
        values = {
            "database_url": database_url,
            "redis_url": redis_url,
            "session_secret": self.session_secret,
            "songmaker_internal_token": secrets.token_hex(16),
            "oidc_issuer": "https://issuer.invalid/realms/test",
            "oidc_client_id": OIDC_CLIENT_ID,
            "oidc_client_secret_file": str(client_secret),
            "public_base_url": "https://songmaker.invalid",
            "allowed_hosts": LOOPBACK,
            "cookie_secure": "false",
            "audio_dir": str(self.audio_dir),
        }
        environment = {environment_name(Settings, field): value for field, value in values.items()}
        if self._stand_ins is not None:
            environment.update(self._stand_in_environment(self._stand_ins))
        return environment

    def _stand_in_environment(self, stand_ins: StandIns) -> dict[str, str]:
        agent = agent_config(self.root, origin=stand_ins.gateway_origin)
        assert agent.gateway is not None
        prefix = environment_name(Settings, "agent")
        return {
            environment_name(Settings, "oidc_issuer"): stand_ins.issuer_url,
            f"{prefix}__BACKEND": agent.backend.value,
            f"{prefix}__GATEWAY__ORIGIN": agent.gateway.origin,
            f"{prefix}__GATEWAY__KEY_FILE": str(agent.gateway.key_file),
            f"{prefix}__API_GROUP": agent.api_group,
            TRUSTED_CERTIFICATES_VARIABLE: str(stand_ins.issuer_certificate),
        }

    @property
    def environment(self) -> dict[str, str]:
        """The settings every process shares, as the environment a process reads them from."""
        return dict(self._shared_environment)

    def settings(self) -> Settings:
        """The settings every process shares, read the way a process reads them."""
        with patch.dict(os.environ, self._shared_environment):
            return Settings()

    def _launch(
        self, name: str, arguments: list[str], *, environment: dict[str, str],
    ) -> tuple[subprocess.Popen[bytes], IO[bytes], Path]:
        """Start `python <arguments>` in a directory of its own; it dies with the test process."""
        directory = self.root / name
        directory.mkdir()
        (directory / "pyproject.toml").write_text("[project]\nname = 'test'\n", encoding="utf-8")
        (directory / "frontend" / "build").mkdir(parents=True)
        (directory / "frontend" / "build" / "index.html").write_text(
            "<html></html>", encoding="utf-8",
        )
        log_path = directory / "server.log"
        log = log_path.open("wb")
        process = subprocess.Popen(
            [sys.executable, *arguments],
            cwd=directory,
            env={
                **_inherited_environment(),
                **self._shared_environment,
                environment_name(Settings, "data_dir"): str(directory / "data"),
                **environment,
            },
            stdout=log, stderr=subprocess.STDOUT,
            preexec_fn=partial(die_with_parent, os.getpid()),  # noqa: PLW1509 - runs in the child
        )
        return process, log, log_path

    def start(self, name: str, *, redis_url: str | None = None) -> WebProcess:
        """Start one web process and return it once `/health` answers.

        ``redis_url`` gives it a Redis address of its own instead of the case's.
        """
        worker_id = f"{name}-{uuid.uuid4().hex[:8]}"
        port = _free_port()
        environment = {environment_name(WorkerSettings, "worker_id"): worker_id}
        if redis_url is not None:
            environment[environment_name(Settings, "redis_url")] = redis_url
        process, log, log_path = self._launch(
            name,
            [
                "-m", "songmaker_cli.main", "server",
                "--port", str(port), "--root", str(self.root / name),
            ],
            environment=environment,
        )
        web_process = WebProcess(name, process, log, log_path, port, worker_id)
        self._processes.append(web_process)
        _wait_until_ready(
            web_process,
            f"answer {HEALTH_PATH}",
            lambda: httpx.get(f"{web_process.url}{HEALTH_PATH}", timeout=2.0).status_code == 200,
        )
        return web_process

    def start_music_worker(self, name: str) -> MusicWorkerProcess:
        """Start one music worker and return it once its lease names its owner id."""
        known_owner_ids = leased_owner_ids(self._redis)
        process, log, log_path = self._launch(
            name, ["-m", "songmaker_cli.arq_worker", MUSIC_WORKER_SETTINGS], environment={},
        )
        worker = MusicWorkerProcess(name, process, log, log_path, owner_id="")
        self._processes.append(worker)
        _wait_until_ready(
            worker, "hold an owner lease",
            lambda: bool(leased_owner_ids(self._redis) - known_owner_ids),
        )
        [worker.owner_id] = leased_owner_ids(self._redis) - known_owner_ids
        return worker

    def stop_all(self) -> None:
        for child in self._processes:
            child.stop()
        self._redis.close()


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


def age_the_owner_lease_epoch(redis: Redis) -> None:
    """Date the owner leases' epoch one lease span back, so an absent lease reads gone.

    An epoch an earlier test created on the shared Redis is dated back too.
    """
    redis.set(*aged_owner_lease_epoch())


def _on_the_owner_leases(redis: Redis, use: Callable[[Leases], Awaitable[T]]) -> T:
    """Run ``use`` on the production owner leases over the Redis the case's processes share."""
    address = redis.connection_pool.connection_kwargs

    async def run() -> T:
        async with AsyncRedis(
            host=address["host"], port=address["port"], db=address.get("db", 0),
        ) as client:
            return await use(owner_leases(client))

    return asyncio.run(run())


def leased_owner_ids(redis: Redis) -> set[str]:
    """The owner ids whose lease Redis holds, as the production roster reads them."""

    async def read_roster(leases: Leases) -> set[str]:
        return set((await leases.live()).holders)

    return _on_the_owner_leases(redis, read_roster)


def owner_lease_generation(redis: Redis, owner_id: str) -> str | None:
    """The generation of ``owner_id``'s live lease, or None while it has none."""

    async def read_state(leases: Leases) -> str | None:
        return (await leases.state([owner_id]))[owner_id].generation

    return _on_the_owner_leases(redis, read_state)


def start_the_owner_lease(redis: Redis, owner_id: str) -> str:
    """Start ``owner_id``'s lease anew and return its generation, as a renewal after a lapse."""

    async def start(leases: Leases) -> str:
        return (await leases.renew(owner_id)).generation

    return _on_the_owner_leases(redis, start)


def end_the_owner_lease(redis: Redis, owner_id: str, generation: str) -> None:
    """End ``owner_id``'s lease of ``generation``, as a lapse of it does; the process renews."""

    async def end(leases: Leases) -> bool:
        return await leases.end(owner_id, generation)

    assert _on_the_owner_leases(redis, end)


def _wait_until_ready(
    child: ChildProcess, readiness: str, is_ready: Callable[[], bool],
) -> None:
    deadline = time.monotonic() + READY_DEADLINE_SECONDS
    pause = threading.Event()
    while time.monotonic() < deadline:
        exit_code = child.process.poll()
        if exit_code is not None:
            pytest.fail(
                f"{child.name} exited with {exit_code} before it was ready:\n{child.log_tail()}",
                pytrace=False,
            )
        try:
            if is_ready():
                return
        except httpx.TransportError:
            pass
        pause.wait(READY_POLL_SECONDS)
    child.kill()
    pytest.fail(
        f"{child.name} did not {readiness} within {READY_DEADLINE_SECONDS} s:\n{child.log_tail()}",
        pytrace=False,
    )


@contextmanager
def web_processes(
    root: Path, *, database_url: str, redis_url: str, stand_ins: StandIns | None = None,
) -> Iterator[WebProcesses]:
    """The processes of one case; every one is ended when the case ends, however it ends."""
    cluster = WebProcesses(
        root, database_url=database_url, redis_url=redis_url, stand_ins=stand_ins,
    )
    try:
        yield cluster
    finally:
        cluster.stop_all()

