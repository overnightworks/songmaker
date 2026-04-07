from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import httpx

log = logging.getLogger(__name__)

REGISTER_PATH = "/api/internal/workers/register"
DEFAULT_RETRY_DELAYS_SECONDS: tuple[float, ...] = (1.0, 2.0, 5.0, 10.0, 30.0)
DEFAULT_TIMEOUT_SECONDS = 10.0


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
        retry_delays_seconds: tuple[float, ...] = DEFAULT_RETRY_DELAYS_SECONDS,
        sleeper: Any = asyncio.sleep,
    ) -> None:
        self._control_plane_url = control_plane_url.rstrip("/")
        self._internal_token = internal_token
        self._timeout = timeout_seconds
        self._delays = retry_delays_seconds
        self._sleeper = sleeper

    async def register(self, registration: WorkerRegistration) -> None:
        url = f"{self._control_plane_url}{REGISTER_PATH}"
        headers = {"X-Internal-Token": self._internal_token}
        payload = registration.to_payload()
        last_error: Exception | None = None
        total_attempts = len(self._delays)
        for attempt, delay in enumerate(self._delays):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.post(url, json=payload, headers=headers)
                    response.raise_for_status()
                    log.info("Worker %s registered with control plane", registration.worker_id)
                    return
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                last_error = exc
                is_last_attempt = attempt == total_attempts - 1
                if is_last_attempt:
                    log.warning("Registration attempt %d failed: %s", attempt + 1, exc)
                    break
                log.warning(
                    "Registration attempt %d failed: %s. Retrying in %.1fs",
                    attempt + 1,
                    exc,
                    delay,
                )
                await self._sleeper(delay)
        raise RegistrationFailedError(
            f"Could not register worker {registration.worker_id} after "
            f"{total_attempts} attempts: {last_error}"
        )
