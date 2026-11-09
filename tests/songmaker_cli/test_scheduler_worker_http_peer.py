"""The worker peer's own deadlines: startup and proof body are bounded apart."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from support.worker_http_peer import WorkerScenario

from acestep_worker.model_cache import LoadedModel
from songmaker_cli.scheduler import worker_response_cause


def _run(coro):
    return asyncio.run(coro)


def test_generation_worker_peer_deadline_cleans_up(generation_worker_peer):
    """S5-D, L9/L10: A stalled proof names its phase and releases the peer."""

    async def exercise():
        peer = None
        peer_context = generation_worker_peer(deadline_seconds=0.05)
        stalled = asyncio.Event()

        async def wait_for_peer_deadline():
            nonlocal peer
            async with peer_context as peer:
                await stalled.wait()

        operation = wait_for_peer_deadline()
        with pytest.raises(TimeoutError, match="Worker peer timed out during proof body"):
            await operation
        assert not peer.deps.heartbeat.is_running
        assert peer.deps.cache.loaded_modes() == []
        async with httpx.AsyncClient(transport=peer.transport) as client:
            with pytest.raises(RuntimeError, match="Worker peer is closed"):
                await client.get("http://worker/load_model")

    _run(exercise())


def test_generation_worker_peer_body_deadline_ignores_slow_startup(generation_worker_peer):
    """S5-D, L9/L10: The body deadline starts with the proof body, not with startup."""
    body_deadline_seconds = 0.05

    async def load_after_body_deadline(mode):
        # Sleeping is only a lower bound: startup always outlasts the body deadline.
        await asyncio.sleep(body_deadline_seconds * 2)
        return LoadedModel(mode=mode, handle=object(), port=0)

    async def exercise():
        peer_context = generation_worker_peer(
            WorkerScenario(loaded_modes=("sft",), model_loader=load_after_body_deadline),
            deadline_seconds=body_deadline_seconds,
        )
        stalled = asyncio.Event()
        with pytest.raises(TimeoutError, match="Worker peer timed out during proof body"):
            async with peer_context:
                await stalled.wait()

    _run(exercise())


def test_generation_worker_peer_startup_stall_names_startup(generation_worker_peer):
    """S5-D, L9/L10: A stalled startup stays bounded and names its phase."""
    never_loaded = asyncio.Event()

    async def load_never(mode):
        await never_loaded.wait()

    async def exercise():
        peer_context = generation_worker_peer(
            WorkerScenario(loaded_modes=("sft",), model_loader=load_never),
            startup_deadline_seconds=0.05,
        )
        with pytest.raises(TimeoutError, match="Worker peer timed out during startup"):
            async with peer_context:
                pytest.fail("startup must not complete")

    _run(exercise())


@pytest.mark.parametrize(
    ("status", "body", "cause"),
    [
        (500, '{"detail": "model missing"}', "model missing"),
        (502, "<html>Bad Gateway</html>", "<html>Bad Gateway</html>"),
        (422, '[{"msg": "field required"}]', '[{"msg": "field required"}]'),
        (500, '{"detail": ["not", "a", "string"]}', '{"detail": ["not", "a", "string"]}'),
    ],
)
def test_worker_response_cause_is_the_string_detail_else_the_body(status, body, cause):
    response = httpx.Response(status, text=body)

    assert worker_response_cause(response) == cause
