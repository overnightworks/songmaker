"""Fixtures shared by the ACE-Step worker wrapper tests."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from support.acestep_http import acestep_http
from support.wrapper_deps import INTERNAL_HEADERS, make_deps

from acestep_worker.model_cache import LoadedModel
from acestep_worker.wrapper import create_app, default_generate_runner


@pytest.fixture
def real_generate_worker(tmp_path: Path):
    """Use the public dependency seam while retaining the production runner."""
    with acestep_http() as boundary:
        async def loader(mode: str) -> LoadedModel:
            return LoadedModel(mode=mode, handle="test-model", port=boundary.port)

        deps, _ = make_deps(tmp_path, model_loader=loader)
        completed = asyncio.Event()

        async def runner(store, task_id, **kwargs):
            try:
                await default_generate_runner(store, task_id, **kwargs)
            finally:
                # Observe the route's resource-release edge after the runner returns.
                asyncio.get_running_loop().call_soon(completed.set)

        deps.generate_runner = runner

        async def generate(client):
            completed.clear()
            response = await client.post(
                "/generate", json={"mode": "sft", "config": {"prompt": "x", "lyrics": ""}},
            )
            assert response.status_code == 200
            await asyncio.wait_for(completed.wait(), timeout=10)
            assert deps.cache.in_use_count("sft") == 0
            assert not deps.gpu_hold_generation_tasks
            snapshot = await client.get(f"/tasks/{response.json()['task_id']}")
            assert snapshot.status_code == 200
            return snapshot.json()

        @asynccontextmanager
        async def worker():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=create_app(deps)),
                base_url="http://worker", headers=INTERNAL_HEADERS,
            ) as client:
                loaded = await client.post("/load_model", json={"mode": "sft"})
                assert loaded.status_code == 200
                yield client, deps, boundary, generate

        yield worker
