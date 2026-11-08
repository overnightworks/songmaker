"""Music takes a generated take from the worker over HTTP, bounded and without retry."""

from __future__ import annotations

import asyncio
import gzip
import json
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from unittest.mock import MagicMock

import annotated_types
import httpx
import pytest
from support.generation_job_world import (
    failing_first_job_read_after,
    make_generation_dto,
    patch_generation_dispatch,
    run_async,
)

from songmaker_cli.api_models.songs import SongCreateRequest, SongUpdateRequest
from songmaker_cli.db.models import Generation
from songmaker_cli.db.queries.jobs import get_job
from songmaker_cli.jobs import run_generation_job
from songmaker_cli.scheduler import (
    DispatchOptions,
    WorkerTaskFailed,
    _PickedWorker,
    dispatch_generation_on_worker,
)
from songmaker_cli.settings import GENERATION_RESULT_MAX_BYTES, get_settings

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


def _generation_dispatch(worker: _Worker):
    from acestep_engine.models import AceStepConfig

    options = DispatchOptions(
        transport=httpx.MockTransport(worker.handle), initial_reconnect_backoff_seconds=0.0,
    )
    picked = _PickedWorker(id="w1", host="worker", port=8001, loaded_modes=["sft"], queue_depth=0)
    return dispatch_generation_on_worker(
        worker=picked, ace_config=AceStepConfig(prompt="p", lyrics="l"), target_mode="sft",
        options=options,
    )


def _dispatch(worker: _Worker):
    return asyncio.run(_generation_dispatch(worker))


async def _streamed(body: bytes):
    """A body as a real worker sends it: a stream, not content the client already holds."""
    yield body


def _serves(body: bytes) -> Callable[[httpx.Request], httpx.Response]:
    def answer(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(200, content=_streamed(body))

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
    assert fetch.headers["Accept-Encoding"] == "identity"
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
        async def chunks():
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
        200, headers={"Content-Length": str(_LIMIT + 1)}, content=_streamed(b"x" * (_LIMIT + 1)),
    ))

    with pytest.raises(WorkerTaskFailed):
        _dispatch(worker)

    assert list(music_tmp.iterdir()) == []


@pytest.mark.usefixtures("small_limit")
def test_an_encoded_take_is_refused_and_leaves_no_file(music_tmp: Path) -> None:
    body = gzip.compress(b"\0" * (_LIMIT // 2))
    assert len(body) < _LIMIT
    worker = _Worker(lambda request: httpx.Response(
        200, headers={"Content-Encoding": "gzip"}, content=_streamed(body),
    ))

    with pytest.raises(WorkerTaskFailed):
        _dispatch(worker)

    assert list(music_tmp.iterdir()) == []


def _cut_off(request: httpx.Request) -> httpx.Response:
    async def body():
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


@pytest.mark.parametrize("creation", ["succeeds", "fails"])
def test_a_cancel_while_the_take_file_is_being_created_leaves_no_file(
    music_tmp: Path, monkeypatch: pytest.MonkeyPatch, creation: str,
) -> None:
    created, resume = threading.Event(), threading.Event()
    mkstemp = tempfile.mkstemp

    def mkstemp_held_after_creating(*args, **kwargs):
        made = mkstemp(*args, **kwargs) if creation == "succeeds" else None
        created.set()
        resume.wait(timeout=10)
        if made is None:
            raise OSError(28, "No space left on device")
        return made

    monkeypatch.setattr(tempfile, "mkstemp", mkstemp_held_after_creating)

    callback_failures: list[dict] = []

    def record_callback_failure(_loop: asyncio.AbstractEventLoop, context: dict) -> None:
        if "handle" in context:
            callback_failures.append(context)

    async def cancel_while_creating() -> None:
        asyncio.get_running_loop().set_exception_handler(record_callback_failure)
        fetch = asyncio.create_task(_generation_dispatch(_Worker(_serves(_TAKE))))
        assert await asyncio.to_thread(created.wait, 10)
        fetch.cancel()
        resume.set()
        with pytest.raises(asyncio.CancelledError):
            await fetch

    asyncio.run(cancel_while_creating())

    assert list(music_tmp.iterdir()) == []
    assert callback_failures == []


def test_a_delete_the_worker_refuses_does_not_fail_the_fetched_take(music_tmp: Path) -> None:
    def refuses_delete(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            return httpx.Response(500)
        return httpx.Response(200, content=_streamed(_TAKE))

    fetched = _dispatch(_Worker(refuses_delete))

    assert Path(fetched.audio_path).read_bytes() == _TAKE


def test_a_delete_answer_with_an_endless_body_is_never_read(music_tmp: Path) -> None:
    served = []

    def endless_delete_answer(request: httpx.Request) -> httpx.Response:
        if request.method != "DELETE":
            return httpx.Response(200, content=_streamed(_TAKE))

        async def chunks():
            for _ in range(100_000):
                served.append(1)
                yield b"x" * 16

        return httpx.Response(500, content=chunks())

    fetched = _dispatch(_Worker(endless_delete_answer))

    assert Path(fetched.audio_path).read_bytes() == _TAKE
    assert len(served) <= 1


def _longest_requested_seconds() -> int:
    """The duration bound a song request's own Field declares, create or update."""
    return max(
        constraint.le
        for model in (SongCreateRequest, SongUpdateRequest)
        for constraint in model.model_fields["audio_duration"].metadata
        if isinstance(constraint, annotated_types.Le)
    )


def test_the_default_limit_admits_the_longest_take_songmaker_allows() -> None:
    # ACE-Step's WAV: 48 kHz stereo, at most 4 bytes per sample, a 44-byte header.
    longest_take_bytes = _longest_requested_seconds() * 48_000 * 2 * 4 + 44

    assert GENERATION_RESULT_MAX_BYTES >= longest_take_bytes


def _run_generation_whose_terminal_check_fails_after_the_fetch(
    seeded_db, tmp_path: Path, failure: BaseException
) -> Path:
    fetched_take = tmp_path / "songmaker_take_fetched.wav"
    fetched_take.write_bytes(b"RIFF")
    fetched = False

    async def fetch_take(**_kwargs):
        nonlocal fetched
        fetched = True
        return make_generation_dto(audio_path=str(fetched_take))

    dispatch, post_process, defaults = patch_generation_dispatch(fetch_take)
    with (
        dispatch,
        post_process,
        defaults,
    ):
        run_async(
            run_generation_job(
                "j1",
                "s1",
                "v1",
                1,
                "u1",
                db_factory=failing_first_job_read_after(seeded_db, lambda: fetched, failure),
                audio_dir=tmp_path / "audio",
                data_dir=tmp_path / "data",
                redis=MagicMock(),
                target_model="sft",
            )
        )
    return fetched_take


def test_a_fetched_take_is_discarded_when_the_terminal_check_fails(
    seeded_db, tmp_path: Path
) -> None:
    fetched_take = _run_generation_whose_terminal_check_fails_after_the_fetch(
        seeded_db, tmp_path, RuntimeError("database unavailable")
    )

    assert not fetched_take.exists()
    with seeded_db() as session:
        assert get_job(session, "j1").status == "failed"
        assert session.query(Generation).filter_by(song_id="s1").count() == 0


def test_a_fetched_take_is_discarded_when_the_job_is_cancelled_after_the_fetch(
    seeded_db, tmp_path: Path
) -> None:
    fetched_take = tmp_path / "songmaker_take_fetched.wav"
    cancellation = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        _run_generation_whose_terminal_check_fails_after_the_fetch(
            seeded_db, tmp_path, cancellation
        )

    assert not fetched_take.exists()
