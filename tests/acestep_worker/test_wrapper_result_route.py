"""A finished take leaves the worker only through its authenticated result route."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
from test_wrapper import (
    _INTERNAL_HEADERS,
    _make_deps,
    _run,
    real_generate_worker,  # noqa: F401 - the pytest fixture, used by name
)

from acestep_worker.__main__ import build_deps
from acestep_worker.clock import utcnow
from acestep_worker.models import GenerationTaskResult
from acestep_worker.settings import WorkerSettings
from acestep_worker.task_store import TaskStore
from acestep_worker.wrapper import WorkerDeps, create_app

_TAKE_BYTES = b"RIFF-the-take"


async def _finished_take(deps: WorkerDeps, root: Path) -> tuple[str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    task_id = await deps.task_store.create("generate")
    take = root / f"{task_id}-1234abcd.wav"
    take.write_bytes(_TAKE_BYTES)
    await deps.task_store.complete(
        task_id, GenerationTaskResult(mode="sft", seed=1), result_file=take,
    )
    return task_id, take


@pytest.fixture
def world(tmp_path: Path):
    deps, _ = _make_deps(tmp_path)
    root = tmp_path / "local-output"

    async def client() -> AsyncIterator[httpx.AsyncClient]:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(deps)), base_url="http://worker",
        ) as http:
            yield http

    return deps, root, client


def test_result_route_serves_the_take_to_the_internal_token(world) -> None:
    deps, root, client = world

    async def go():
        task_id, _ = await _finished_take(deps, root)
        async for http in client():
            response = await http.get(f"/tasks/{task_id}/result", headers=_INTERNAL_HEADERS)
            assert (response.status_code, response.content) == (200, _TAKE_BYTES)

    _run(go())


@pytest.mark.parametrize("headers, status", [
    ({}, 422),
    ({"X-Internal-Token": "wrong"}, 401),
])
def test_result_route_refuses_a_missing_or_wrong_token_and_serves_no_bytes(
    world, headers: dict[str, str], status: int,
) -> None:
    deps, root, client = world

    async def go():
        task_id, take = await _finished_take(deps, root)
        async for http in client():
            for method in ("GET", "DELETE"):
                response = await http.request(method, f"/tasks/{task_id}/result", headers=headers)
                assert response.status_code == status
                assert _TAKE_BYTES not in response.content
        assert take.read_bytes() == _TAKE_BYTES

    _run(go())


def test_result_route_opens_no_file_the_store_did_not_record(world, tmp_path: Path) -> None:
    deps, root, client = world

    async def go():
        recorded, _ = await _finished_take(deps, root)
        secret = tmp_path / "secret.txt"
        secret.write_bytes(b"not a take")
        (root / "planted.wav").write_bytes(b"PLANTED-BYTES")
        running = await deps.task_store.create("generate")
        failed = await deps.task_store.create("generate")
        await deps.task_store.fail(failed, "boom")
        crafted = ["planted", "../secret.txt", "..%2Fsecret.txt", str(secret), "unknown-id"]
        async for http in client():
            for task_id in (*crafted, running, failed):
                response = await http.get(f"/tasks/{task_id}/result", headers=_INTERNAL_HEADERS)
                assert response.status_code == 404, task_id
                assert b"PLANTED-BYTES" not in response.content
                assert b"not a take" not in response.content
        assert recorded

    _run(go())


def test_delete_removes_the_take_and_a_second_fetch_finds_nothing(world) -> None:
    deps, root, client = world

    async def go():
        task_id, take = await _finished_take(deps, root)
        async for http in client():
            deleted = await http.delete(f"/tasks/{task_id}/result", headers=_INTERNAL_HEADERS)
            again = await http.get(f"/tasks/{task_id}/result", headers=_INTERNAL_HEADERS)
            snapshot = await http.get(f"/tasks/{task_id}", headers=_INTERNAL_HEADERS)
        assert deleted.status_code == 204
        assert not take.exists()
        assert again.status_code == 404
        assert snapshot.json()["state"] == "done"

    _run(go())


def test_the_expiry_sweep_removes_the_take_with_its_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def go():
        deps, _ = _make_deps(tmp_path)
        store = TaskStore(retention_seconds=0.0)
        deps.task_store = store
        _, take = await _finished_take(deps, tmp_path / "out")
        monkeypatch.setattr(
            "acestep_worker.task_store.utcnow", lambda: utcnow() + timedelta(seconds=1),
        )
        assert await store.cleanup_terminal() == 1
        assert not take.exists()

    _run(go())


async def _get_releasing_after_the_start(
    app, path: str, release: Callable[[], Awaitable[None]],
) -> tuple[int, bytes]:
    """GET over raw ASGI: ``release`` runs once the headers left, before any body byte."""
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
        "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": b"",
        "root_path": "", "server": ("worker", 80), "client": ("music", 1),
        "headers": [(b"host", b"worker"), *(
            (name.lower().encode(), value.encode()) for name, value in _INTERNAL_HEADERS.items()
        )],
    }
    requested = False
    status, body = 0, bytearray()

    async def receive() -> dict:
        nonlocal requested
        if not requested:
            requested = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await asyncio.Event().wait()
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        nonlocal status
        if message["type"] == "http.response.start":
            status = message["status"]
            await release()
        elif message["type"] == "http.response.body":
            body.extend(message.get("body", b""))

    await app(scope, receive, send)
    return status, bytes(body)


@pytest.mark.parametrize("release", ["delete", "sweep"])
def test_a_result_stream_survives_a_delete_or_sweep_after_it_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, release: str,
) -> None:
    async def go():
        deps, _ = _make_deps(tmp_path)
        deps.task_store = TaskStore(retention_seconds=0.0)
        task_id, take = await _finished_take(deps, tmp_path / "out")
        app = create_app(deps)

        async def release_the_take() -> None:
            if release == "delete":
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://worker",
                ) as http:
                    deleted = await http.delete(
                        f"/tasks/{task_id}/result", headers=_INTERNAL_HEADERS,
                    )
                assert deleted.status_code == 204
            else:
                monkeypatch.setattr(
                    "acestep_worker.task_store.utcnow", lambda: utcnow() + timedelta(seconds=1),
                )
                assert await deps.task_store.cleanup_terminal() == 1
            assert not take.exists()

        status, body = await _get_releasing_after_the_start(
            app, f"/tasks/{task_id}/result", release_the_take,
        )
        assert (status, body) == (200, _TAKE_BYTES)

    _run(go())


@pytest.fixture
def removal_fails_once(monkeypatch: pytest.MonkeyPatch) -> Callable[[Path], None]:
    """The next removal of the named file raises; later ones remove it."""
    unlink = Path.unlink
    failing: set[Path] = set()

    def flaky_unlink(path: Path, missing_ok: bool = False) -> None:
        if path in failing:
            failing.discard(path)
            raise PermissionError(13, "Permission denied", str(path))
        unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)
    return failing.add


def test_a_delete_whose_removal_fails_answers_an_error_and_a_retry_removes_the_take(
    world, removal_fails_once: Callable[[Path], None],
) -> None:
    deps, root, client = world

    async def go():
        task_id, take = await _finished_take(deps, root)
        removal_fails_once(take)
        async for http in client():
            failed = await http.delete(f"/tasks/{task_id}/result", headers=_INTERNAL_HEADERS)
            assert failed.status_code >= 500
            assert str(root) not in failed.text
            assert take.exists()
            retried = await http.delete(f"/tasks/{task_id}/result", headers=_INTERNAL_HEADERS)
        assert retried.status_code == 204
        assert not take.exists()

    _run(go())


def test_a_sweep_whose_removal_fails_keeps_the_take_for_the_next_sweep(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, removal_fails_once: Callable[[Path], None],
) -> None:
    async def go():
        deps, _ = _make_deps(tmp_path)
        store = TaskStore(retention_seconds=0.0)
        deps.task_store = store
        task_id, take = await _finished_take(deps, tmp_path / "out")
        removal_fails_once(take)
        monkeypatch.setattr(
            "acestep_worker.task_store.utcnow", lambda: utcnow() + timedelta(seconds=1),
        )
        assert await store.cleanup_terminal() == 0
        assert take.exists()
        assert await store.get(task_id) is not None
        assert await store.cleanup_terminal() == 1
        assert not take.exists()

    _run(go())


def test_the_real_runner_writes_only_its_local_root_and_names_no_path(
    real_generate_worker,  # noqa: F811 - the fixture imported above
) -> None:
    async def go():
        async with real_generate_worker() as (client, deps, boundary, generate):
            boundary.succeed()
            snapshot = await generate(client)
            written = [take.read_bytes() for take in deps.audio_output_dir.iterdir()]
            assert written == [boundary.wav_bytes]
            wire = json.dumps(snapshot)
            assert "audio_path" not in wire
            assert str(deps.audio_output_dir) not in wire

    _run(go())


def test_a_failed_result_write_names_no_worker_path(
    real_generate_worker,  # noqa: F811 - the fixture imported above
) -> None:
    async def go():
        async with real_generate_worker() as (client, deps, boundary, generate):
            boundary.succeed()
            deps.audio_output_dir.write_text("occupied")
            snapshot = await generate(client)
            assert snapshot["state"] == "error"
            assert snapshot["error"].startswith("FileExistsError:")
            assert str(deps.audio_output_dir) not in snapshot["error"]

    _run(go())


def test_a_done_snapshot_names_no_worker_path(tmp_path: Path) -> None:
    async def go():
        deps, _ = _make_deps(tmp_path)
        task_id, take = await _finished_take(deps, tmp_path / "out")
        snapshot = await deps.task_store.get(task_id)
        wire = json.dumps(snapshot.model_dump(mode="json"))
        assert str(take.parent) not in wire
        assert take.name not in wire
        assert "audio_path" not in wire

    _run(go())


def _settings_with_roots(output_dir: Path, shared_root: Path) -> WorkerSettings:
    return WorkerSettings(
        worker_id="acestep-worker-0", redis_url="redis://fake", songmaker_internal_token="secret",
        audio_output_dir=str(output_dir), shared_audio_root=str(shared_root),
    )


def _build(settings: WorkerSettings) -> WorkerDeps:
    with (
        patch("acestep_worker.__main__.Redis.from_url", return_value=MagicMock()),
        patch(
            "acestep_worker.__main__.make_acestep_runner",
            return_value=(MagicMock(), MagicMock()),
        ),
    ):
        return build_deps(settings)


def test_a_worker_start_empties_its_output_root_and_touches_nothing_shared(tmp_path: Path) -> None:
    root, shared = tmp_path / "local-output", tmp_path / "shared"
    (root / "nested").mkdir(parents=True)
    (root / "stale.wav").write_bytes(b"stale")
    (root / "nested" / "stale.wav").write_bytes(b"stale")
    shared.mkdir()
    (shared / "kept.mp3").write_bytes(b"kept")

    _build(_settings_with_roots(root, shared))

    assert root.is_dir()
    assert list(root.iterdir()) == []
    assert (shared / "kept.mp3").read_bytes() == b"kept"


@pytest.mark.parametrize("relative", ["", "worker_output"])
def test_a_worker_start_refuses_an_output_root_on_the_shared_volume(
    tmp_path: Path, relative: str,
) -> None:
    shared = tmp_path / "shared"
    root = shared / relative if relative else shared
    root.mkdir(parents=True)
    (shared / "kept.mp3").write_bytes(b"kept")

    with pytest.raises(ValueError, match="shared"):
        _build(_settings_with_roots(root, shared))

    assert (shared / "kept.mp3").read_bytes() == b"kept"
