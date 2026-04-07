from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from acestep_worker.registry_client import (
    REGISTER_PATH,
    RegistrationFailedError,
    RegistryClient,
    WorkerRegistration,
)


def _run(coro):
    return asyncio.run(coro)


def _make_registration() -> WorkerRegistration:
    return WorkerRegistration(
        worker_id="acestep-worker-0",
        host="acestep-worker-0",
        port=8001,
        gpu_id=0,
        vram_total_gb=24.0,
    )


def _client_with_transport(transport: httpx.MockTransport) -> RegistryClient:
    async def fake_sleep(_: float) -> None:
        return None

    client = RegistryClient(
        control_plane_url="http://web:8080",
        internal_token="secret",
        retry_delays_seconds=(0.0, 0.0, 0.0),
        sleeper=fake_sleep,
    )
    original_async_client = httpx.AsyncClient

    def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original_async_client(*args, **kwargs)

    client._async_client_factory = factory  # type: ignore[attr-defined]
    return client


def test_payload_shape() -> None:
    payload = _make_registration().to_payload()
    assert payload["worker_id"] == "acestep-worker-0"
    assert payload["host"] == "acestep-worker-0"
    assert payload["port"] == 8001
    assert payload["gpu_id"] == 0
    assert payload["vram_total_gb"] == 24.0


def test_register_success_first_try() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = request.content
        return httpx.Response(200, json={"ok": True})

    async def fake_sleep(_: float) -> None:
        return None

    client = RegistryClient(
        control_plane_url="http://web:8080",
        internal_token="secret",
        retry_delays_seconds=(0.0,),
        sleeper=fake_sleep,
    )
    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    httpx.AsyncClient = factory  # type: ignore[misc]
    try:
        _run(client.register(_make_registration()))
    finally:
        httpx.AsyncClient = original  # type: ignore[misc]

    assert captured["url"].endswith(REGISTER_PATH)
    assert captured["headers"]["x-internal-token"] == "secret"


def test_register_retries_then_succeeds() -> None:
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] < 2:
            return httpx.Response(503, text="not ready")
        return httpx.Response(200, json={"ok": True})

    async def fake_sleep(_: float) -> None:
        return None

    client = RegistryClient(
        control_plane_url="http://web:8080",
        internal_token="t",
        retry_delays_seconds=(0.0, 0.0),
        sleeper=fake_sleep,
    )
    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    httpx.AsyncClient = factory  # type: ignore[misc]
    try:
        _run(client.register(_make_registration()))
    finally:
        httpx.AsyncClient = original  # type: ignore[misc]

    assert attempts["count"] == 2


def test_register_all_attempts_fail_raises_without_final_sleep() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="permanent")

    sleep_calls: list[float] = []

    async def recording_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    client = RegistryClient(
        control_plane_url="http://web:8080",
        internal_token="t",
        retry_delays_seconds=(1.0, 2.0, 3.0),
        sleeper=recording_sleep,
    )
    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    httpx.AsyncClient = factory  # type: ignore[misc]
    try:
        with pytest.raises(RegistrationFailedError):
            _run(client.register(_make_registration()))
    finally:
        httpx.AsyncClient = original  # type: ignore[misc]

    assert sleep_calls == [1.0, 2.0]


def test_register_handles_transport_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    async def fake_sleep(_: float) -> None:
        return None

    client = RegistryClient(
        control_plane_url="http://web:8080",
        internal_token="t",
        retry_delays_seconds=(0.0,),
        sleeper=fake_sleep,
    )
    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    httpx.AsyncClient = factory  # type: ignore[misc]
    try:
        with pytest.raises(RegistrationFailedError):
            _run(client.register(_make_registration()))
    finally:
        httpx.AsyncClient = original  # type: ignore[misc]
