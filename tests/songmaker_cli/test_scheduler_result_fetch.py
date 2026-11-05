"""Music takes a generated take from the worker over HTTP, bounded and without retry."""

from __future__ import annotations

import asyncio
import json
import tempfile
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from songmaker_cli.constants import GENERATION_RESULT_MAX_BYTES
from songmaker_cli.scheduler import (
    DispatchOptions,
    WorkerTaskFailed,
    _PickedWorker,
    dispatch_generation_on_worker,
)
from songmaker_cli.settings import get_settings

_TAKE = b"RIFF" + b"\x01" * 600
_LIMIT = 256


class _Worker:
    """A worker peer: records every request and answers the result route as told."""

    def __init__(self, result: Callable[[httpx.Request], httpx.Response]) -> None:
        self.requests: list[httpx.Request] = []
        self._result = result
        self.done_result = {"mode": "sft", "seed": 7, "cot_caption": "c", "cot_lyrics": "l"}

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.method == "POST" and path == "/generate":
            return httpx.Response(200, json={"task_id": "gen-1"})
        if path == "/tasks/gen-1/stream":
            data = json.dumps({"task_id": "gen-1", "state": "done", "result": self.done_result})
            return httpx.Response(200, text=f"event: done\ndata: {data}\n\n")
        if path == "/tasks/gen-1/result":
            return self._result(request)
        return httpx.Response(404)

    def calls(self, method: str, path: str) -> list[httpx.Request]:
        return [r for r in self.requests if (r.method, r.url.path) == (method, path)]


@pytest.fixture
def music_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "music-tmp"
    directory.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(directory))
    return directory


@pytest.fixture
def small_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENERATION_RESULT_MAX_BYTES", str(_LIMIT))


def _dispatch(worker: _Worker):
    from acestep_engine.models import AceStepConfig

    options = DispatchOptions(
        transport=httpx.MockTransport(worker.handle), initial_reconnect_backoff_seconds=0.0,
    )
    picked = _PickedWorker(id="w1", host="worker", port=8001, loaded_modes=["sft"], queue_depth=0)
    return asyncio.run(dispatch_generation_on_worker(
        worker=picked, ace_config=AceStepConfig(), target_mode="sft", options=options,
    ))


def _serves(body: bytes) -> Callable[[httpx.Request], httpx.Response]:
    def answer(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(200, content=body)

    return answer


def test_the_take_is_fetched_by_task_id_into_musics_own_temp_dir_then_deleted(
    music_tmp: Path,
) -> None:
    worker = _Worker(_serves(_TAKE))

    fetched = _dispatch(worker)

    assert Path(fetched.audio_path).read_bytes() == _TAKE
    assert Path(fetched.audio_path).parent == music_tmp
    assert (fetched.seed, fetched.cot_caption) == (7, "c")
    token = get_settings().songmaker_internal_token.get_secret_value()
    fetch, delete = worker.calls("GET", "/tasks/gen-1/result")[0], worker.calls(
        "DELETE", "/tasks/gen-1/result")[0]
    assert fetch.headers["X-Internal-Token"] == token
    assert delete.headers["X-Internal-Token"] == token
    assert worker.requests.index(delete) > worker.requests.index(fetch)


def test_a_path_the_worker_names_in_its_result_is_never_followed(
    music_tmp: Path, tmp_path: Path,
) -> None:
    planted = tmp_path / "planted.wav"
    planted.write_bytes(b"planted")
    worker = _Worker(_serves(_TAKE))
    worker.done_result["audio_path"] = str(planted)

    fetched = _dispatch(worker)

    assert Path(fetched.audio_path).parent == music_tmp
    assert Path(fetched.audio_path).read_bytes() == _TAKE
    assert planted.read_bytes() == b"planted"
    assert not any(str(planted) in str(request.url) for request in worker.requests)


@pytest.mark.usefixtures("small_limit")
def test_a_take_over_the_limit_aborts_at_the_limit_and_leaves_no_file(music_tmp: Path) -> None:
    served = []

    def endless(request: httpx.Request) -> httpx.Response:
        def chunks():
            for _ in range(10_000):
                served.append(1)
                yield b"x" * 64

        return httpx.Response(200, content=chunks())

    worker = _Worker(endless)

    with pytest.raises(WorkerTaskFailed):
        _dispatch(worker)

    assert len(served) * 64 <= _LIMIT + 64 * 2
    assert list(music_tmp.iterdir()) == []


@pytest.mark.usefixtures("small_limit")
def test_a_take_announced_over_the_limit_is_refused_before_its_body_is_read(
    music_tmp: Path,
) -> None:
    worker = _Worker(lambda request: httpx.Response(
        200, headers={"Content-Length": str(_LIMIT + 1)}, content=b"x" * (_LIMIT + 1),
    ))

    with pytest.raises(WorkerTaskFailed):
        _dispatch(worker)

    assert list(music_tmp.iterdir()) == []


def _cut_off(request: httpx.Request) -> httpx.Response:
    def body():
        yield b"RIFF"
        raise httpx.RemoteProtocolError("peer closed connection")

    return httpx.Response(200, content=body())


def _timed_out(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("slow", request=request)


def _refused(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("refused", request=request)


@pytest.mark.parametrize("answer", [
    pytest.param(lambda request: httpx.Response(503, text="busy"), id="server-error"),
    pytest.param(lambda request: httpx.Response(404, json={"detail": "gone"}), id="gone"),
    pytest.param(_cut_off, id="cut-off"),
    pytest.param(_timed_out, id="timeout"),
    pytest.param(_refused, id="refused"),
])
def test_a_failed_fetch_is_one_failed_take_without_retry_or_leftover(
    music_tmp: Path, answer: Callable[[httpx.Request], httpx.Response],
) -> None:
    worker = _Worker(answer)

    with pytest.raises(WorkerTaskFailed):
        _dispatch(worker)

    assert len(worker.calls("GET", "/tasks/gen-1/result")) == 1
    assert list(music_tmp.iterdir()) == []


def test_a_delete_the_worker_refuses_does_not_fail_the_fetched_take(music_tmp: Path) -> None:
    def refuses_delete(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            return httpx.Response(500)
        return httpx.Response(200, content=_TAKE)

    fetched = _dispatch(_Worker(refuses_delete))

    assert Path(fetched.audio_path).read_bytes() == _TAKE


def test_the_default_limit_admits_the_longest_take_songmaker_allows() -> None:
    longest_take_bytes = 600 * 48_000 * 2 * 4 + 44

    assert GENERATION_RESULT_MAX_BYTES >= longest_take_bytes
    assert get_settings().generation_result_max_bytes == GENERATION_RESULT_MAX_BYTES
