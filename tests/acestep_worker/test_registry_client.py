from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from acestep_worker.registry_client import (
    INDEFINITE_BACKOFF_SECONDS,
    INITIAL_BACKOFF_SCHEDULE,
    JITTER_FRACTION,
    REGISTER_PATH,
    RegistrationFailedError,
    RegistryClient,
    WorkerRegistration,
    default_retry_delays,
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


def test_register_finite_delays_exhausted_raises() -> None:
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

    assert sleep_calls == [1.0, 2.0, 3.0]


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


def test_default_retry_delays_yields_initial_then_indefinite() -> None:
    gen = default_retry_delays()
    initial = [next(gen) for _ in range(len(INITIAL_BACKOFF_SCHEDULE))]
    assert tuple(initial) == INITIAL_BACKOFF_SCHEDULE

    cap_low = INDEFINITE_BACKOFF_SECONDS * (1 - JITTER_FRACTION)
    cap_high = INDEFINITE_BACKOFF_SECONDS * (1 + JITTER_FRACTION)
    for _ in range(20):
        v = next(gen)
        assert cap_low <= v <= cap_high


def test_default_factory_is_fresh_iterator_each_call() -> None:
    a = default_retry_delays()
    b = default_retry_delays()
    assert next(a) == next(b)


def test_register_uses_delays_factory_for_each_call() -> None:
    handler_calls = {"count": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        handler_calls["count"] += 1
        if handler_calls["count"] < 4:
            return httpx.Response(503, text="not ready")
        return httpx.Response(200, json={"ok": True})

    sleep_calls: list[float] = []

    async def recording_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    factory_call_count = {"count": 0}

    def factory_fn():
        factory_call_count["count"] += 1
        return iter([0.1, 0.2, 0.3, 0.4, 0.5])

    client = RegistryClient(
        control_plane_url="http://web:8080",
        internal_token="t",
        delays_factory=factory_fn,
        sleeper=recording_sleep,
    )
    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def http_factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    httpx.AsyncClient = http_factory  # type: ignore[misc]
    try:
        _run(client.register(_make_registration()))
        _run(client.register(_make_registration()))
    finally:
        httpx.AsyncClient = original  # type: ignore[misc]

    assert factory_call_count["count"] == 2
    assert handler_calls["count"] >= 4


def test_register_default_factory_eventually_succeeds_after_failures() -> None:
    attempts = {"count": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] < 7:
            return httpx.Response(503, text="not ready")
        return httpx.Response(200, json={"ok": True})

    async def fake_sleep(_: float) -> None:
        return None

    client = RegistryClient(
        control_plane_url="http://web:8080",
        internal_token="t",
        sleeper=fake_sleep,
    )
    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def http_factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    httpx.AsyncClient = http_factory  # type: ignore[misc]
    try:
        _run(client.register(_make_registration()))
    finally:
        httpx.AsyncClient = original  # type: ignore[misc]

    assert attempts["count"] == 7


def test_register_rejects_both_delays_args() -> None:
    with pytest.raises(ValueError, match="not both"):
        RegistryClient(
            control_plane_url="http://web:8080",
            internal_token="t",
            retry_delays_seconds=(0.0,),
            delays_factory=lambda: iter([0.0]),
        )
