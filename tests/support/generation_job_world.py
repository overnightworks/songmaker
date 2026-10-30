"""A seeded job database and the generation dispatch doubles the job-runner tests share."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from songmaker_cli.db.engine import init_test_db as init_db
from songmaker_cli.db.models import Album, Job, Song, User, Version
from songmaker_cli.jobs import _persist_generation_row
from songmaker_cli.scheduler import GenerationTaskResultDTO


def run_async(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def make_generation_dto(
    seed: int = 42,
    audio_path: str = "/tmp/fake.wav",
    delivered_batch_size: int | None = None,
) -> GenerationTaskResultDTO:
    return GenerationTaskResultDTO(
        mode="turbo",
        audio_path=audio_path,
        seed=seed,
        cot_caption="",
        cot_lyrics="",
        delivered_batch_size=delivered_batch_size,
    )


def persist_via_post_process(*, ctx, generation_id, db_factory, **kwargs):
    return _persist_generation_row(
        db_factory=db_factory,
        ctx=ctx,
        generation_id=generation_id,
        seed=kwargs.get("worker_seed", 0),
        cot_caption=kwargs.get("worker_cot_caption", ""),
        cot_lyrics=kwargs.get("worker_cot_lyrics", ""),
        delivered_batch_size=kwargs.get("worker_delivered_batch_size"),
        job_id=kwargs["job_id"],
    )


def persist_with_output_files(*, ctx, generation_id, db_factory, on_outputs_written, **kwargs):
    """Stand in for post_process_generation's files: outputs first, the worker audio last."""
    outputs = [
        ctx.audio_dir / ctx.user_id / f"{generation_id}{suffix}"
        for suffix in (".mp3", ".wav", ".raw.wav")
    ]
    for output in outputs:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"audio")
    on_outputs_written(outputs)
    try:
        return persist_via_post_process(
            ctx=ctx, generation_id=generation_id, db_factory=db_factory, **kwargs,
        )
    finally:
        Path(kwargs["worker_audio_path"]).unlink(missing_ok=True)


@pytest.fixture
def db_factory(tmp_path: Path):
    factory = init_db(tmp_path / "test.db")
    return factory


@pytest.fixture
def seeded_db(db_factory, tmp_path: Path):
    with db_factory() as session:
        session.add(User(id="u1", username="user1", role="user"))
        session.flush()
        session.add(Album(id="rock", title="Rock", artist="Band", created_by="u1"))
        session.add(
            Song(
                id="s1",
                title="Song One",
                album_id="rock",
                track_number=1,
                vocal_language="en",
            )
        )
        session.add(
            Version(
                id="v1",
                song_id="s1",
                version_number=1,
                lyrics="Hello world",
                prompt="rock style",
                bpm=120,
                audio_duration=60,
                key_scale="Am",
            )
        )
        session.add(Job(id="j1", type="generate", status="queued", user_id="u1"))
        session.add(Job(id="j2", type="score", status="queued"))
        session.commit()

    mp3_dir = tmp_path / "audio" / "user1"
    mp3_dir.mkdir(parents=True)
    mp3 = mp3_dir / "g_seed42.mp3"
    mp3.write_bytes(b"\xff\xfb\x90\x00" * 100)

    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    return db_factory


def patch_generation_dispatch(dto_or_side_effect, post_process=persist_via_post_process):
    if isinstance(dto_or_side_effect, list):
        dispatch = AsyncMock(side_effect=dto_or_side_effect)
    elif callable(dto_or_side_effect) or isinstance(dto_or_side_effect, BaseException):
        dispatch = AsyncMock(side_effect=dto_or_side_effect)
    else:
        dispatch = AsyncMock(return_value=dto_or_side_effect)

    @contextmanager
    def patch_dispatch():
        with (
            patch.multiple(
                "songmaker_cli.jobs",
                admit_generation_worker=AsyncMock(return_value=MagicMock(id="w1")),
                dispatch_generation_on_worker=dispatch,
            ),
            patch("songmaker_cli.jobs.generation.decr_queue_depth", AsyncMock()),
        ):
            yield

    return (
        patch_dispatch(),
        patch("songmaker_cli.jobs.post_process_generation", side_effect=post_process),
        patch("songmaker_cli.jobs.load_generation_defaults", return_value={}),
    )
