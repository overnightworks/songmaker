from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from random import SystemRandom
from typing import Any

import httpx

log = logging.getLogger(__name__)

REGISTER_PATH = "/api/internal/workers/register"
DEFAULT_TIMEOUT_SECONDS = 10.0

INITIAL_BACKOFF_SCHEDULE: tuple[float, ...] = (1.0, 2.0, 5.0, 10.0, 30.0)
INDEFINITE_BACKOFF_SECONDS = 60.0
JITTER_FRACTION = 0.2

DelaysFactory = Callable[[], Iterator[float]]
_retry_jitter = SystemRandom()


def default_retry_delays() -> Iterator[float]:
    yield from INITIAL_BACKOFF_SCHEDULE
    while True:
        jitter = INDEFINITE_BACKOFF_SECONDS * JITTER_FRACTION * (2 * _retry_jitter.random() - 1)
        yield INDEFINITE_BACKOFF_SECONDS + jitter


class RegistrationFailedError(RuntimeError):
    pass


@dataclass
class WorkerRegistration:
    worker_id: str
    host: str
    port: int
    gpu_id: int | None
    vram_total_gb: float | None

    def to_payload(self) -> dict[str, Any]:
        return {
            "worker_id": self.worker_id,
            "host": self.host,
            "port": self.port,
            "gpu_id": self.gpu_id,
            "vram_total_gb": self.vram_total_gb,
        }


class RegistryClient:
    def __init__(
        self,
        *,
        control_plane_url: str,
        internal_token: str,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        retry_delays_seconds: tuple[float, ...] | None = None,
        delays_factory: DelaysFactory | None = None,
        sleeper: Any = asyncio.sleep,
    ) -> None:
        self._control_plane_url = control_plane_url.rstrip("/")
        self._internal_token = internal_token
        self._timeout = timeout_seconds
        if delays_factory is not None and retry_delays_seconds is not None:
            raise ValueError(
                "Pass either delays_factory or retry_delays_seconds, not both",
            )
        if delays_factory is not None:
            self._delays_factory: DelaysFactory = delays_factory
        elif retry_delays_seconds is not None:
            fixed = tuple(retry_delays_seconds)
            self._delays_factory = lambda: iter(fixed)
        else:
            self._delays_factory = default_retry_delays
        self._sleeper = sleeper

    @property
    def control_plane_url(self) -> str:
        return self._control_plane_url

    async def register(self, registration: WorkerRegistration) -> None:
        url = f"{self._control_plane_url}{REGISTER_PATH}"
        headers = {"X-Internal-Token": self._internal_token}
        payload = registration.to_payload()
        last_error: Exception | None = None
        attempt = 0
        for delay in self._delays_factory():
            attempt += 1
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.post(url, json=payload, headers=headers)
                    response.raise_for_status()
                    log.info(
                        "Worker %s registered with control plane",
                        registration.worker_id,
                    )
                    return
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                last_error = exc
                log.warning(
                    "Registration attempt %d failed: %s. Retrying in %.1fs",
                    attempt,
                    exc,
                    delay,
                )
                await self._sleeper(delay)
        raise RegistrationFailedError(
            f"Could not register worker {registration.worker_id} after "
            f"{attempt} attempts: {last_error}"
        )
