"""The web runner's queue: what it claims, what it leaves, and what a restart recovers."""

from __future__ import annotations

import asyncio
import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Final

import pytest
from agents.backend.fake_gateway import picture
from PIL import Image
from support.cowriter_gateway import (
    CowriterStack,
    HeldGateway,
    attach_cowriter_gateway,
    raises,
)
from support.web_app import make_authenticated_user, make_router_app, make_router_ctx, web_client

import songmaker_cli.cover_runner as cover_runner
from songmaker_cli.constants import COVER_PROMPT_MAX_CHARS, COVER_PROMPT_SONG_FIELD_MAX_CHARS
from songmaker_cli.db.models import Album, AlbumCoverSuggestion, Job, Song, User, Version
from songmaker_cli.db.queries.albums import soft_delete_album
from songmaker_cli.db.queries.jobs import JobStatusUpdate, update_job_status
from songmaker_cli.health_types import BackgroundLoopName, BackgroundLoopRegistry
from songmaker_cli.job_types import JobStatus, JobType

HANG_GUARD_SECONDS: Final = 30
OWNER: Final = "u1"


def _png_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (16, 16), (20, 80, 160)).save(output, format="PNG")
    return output.getvalue()


def _cover_world(tmp_path: Path, factory, *, song_field: str = "words"):
    with factory() as session:
        session.add(User(id=OWNER, username="owner"))
        session.flush()
        album = Album(id="album", title="Album", artist="Artist", created_by=OWNER)
        song = Song(id="song", album_id=album.id, title="Song", track_number=1)
        version = Version(
            id="version", song_id=song.id, version_number=1, prompt=song_field, lyrics=song_field,
        )
        session.add_all([album, song, version])
        session.commit()
    ctx = make_router_ctx(tmp_path, db=factory)
    client = web_client(make_router_app(ctx, user=make_authenticated_user(OWNER)))
    stack = attach_cowriter_gateway(client, factory, tmp_path, OWNER)
    stack.replies(picture(_png_bytes()))
    return client.app, factory, ctx.audio_dir, stack


def _queue(factory, stack: CowriterStack, job_id: str = "job") -> str:
    with factory() as session:
        session.add(Job(
            id=job_id, type=JobType.COVER, user_id=OWNER, album_id="album",
            session_id=stack.session_id,
        ))
        session.commit()
    return job_id


def test_cancelled_queued_web_cover_job_is_never_claimed(tmp_path: Path, pg_factory) -> None:
    app, factory, _audio_dir, stack = _cover_world(tmp_path, pg_factory)
    job_id = _queue(factory, stack)
    with factory() as session:
        assert update_job_status(session, job_id, JobStatusUpdate(JobStatus.CANCELLED))
        session.commit()

    assert not asyncio.run(cover_runner.run_next_cover_job(app))

    with factory() as session:
        assert session.get(Job, job_id).status == JobStatus.CANCELLED
    assert stack.gateway_requests == []


def _add_pending_suggestion(factory, audio_dir: Path) -> Path:
    """Publish one earlier suggestion from a completed cover job."""
    pending_png = audio_dir / "cover-suggestions" / "album" / "pending.png"
    pending_png.parent.mkdir(parents=True, exist_ok=True)
    pending_png.write_bytes(_png_bytes())
    with factory() as session:
        session.add(Job(
            id="earlier",
            type=JobType.COVER,
            album_id="album",
            user_id=OWNER,
            status=JobStatus.COMPLETED,
        ))
        session.flush()
        session.add(AlbumCoverSuggestion(
            id="pending",
            album_id="album",
            job_id="earlier",
            png_path="cover-suggestions/album/pending.png",
        ))
        session.commit()
    return pending_png


def test_web_runner_exclusively_claims_and_adds_one_suggestion_to_the_pending_ones(
    tmp_path: Path, pg_factory,
) -> None:
    """1301-F3-C1-ATOMIC: image and terminal state agree with usage."""
    app, factory, audio_dir, stack = _cover_world(tmp_path, pg_factory)
    job_id = _queue(factory, stack)
    pending_png = _add_pending_suggestion(factory, audio_dir)
    held = HeldGateway(picture(_png_bytes()))
    stack.uses(held)

    async def run_race() -> tuple[bool, bool]:
        winner = asyncio.create_task(cover_runner.run_next_cover_job(app))
        assert await asyncio.to_thread(held.received.wait, HANG_GUARD_SECONDS)
        loser = await cover_runner.run_next_cover_job(app)
        held.released.set()
        return await winner, loser

    winner, loser = asyncio.run(run_race())

    with factory() as session:
        job = session.get(Job, job_id)
        suggestions = list(job.album.cover_suggestions)
        assert job.status == JobStatus.COMPLETED
        assert job.progress == 1.0
        assert session.query(Job).filter(
            Job.album_id == "album",
            Job.type == JobType.COVER,
            Job.status == JobStatus.COMPLETED,
            Job.started_at >= job.started_at,
        ).count() == 2
        assert sorted(item.job_id for item in suggestions) == ["earlier", job_id]
        assert all((audio_dir / item.png_path).is_file() for item in suggestions)
    assert len(held.requests) == 1
    assert pending_png.is_file()
    assert winner is True
    assert loser is False
    assert not list(audio_dir.rglob(".*.staging"))


def test_web_recovery_fails_interrupted_work_cleans_only_its_suggestion_and_leaves_queue_for_runner(
    tmp_path: Path, pg_factory,
) -> None:
    app, factory, audio_dir, stack = _cover_world(tmp_path, pg_factory)
    running_job_id = _queue(factory, stack)
    pending_png = _add_pending_suggestion(factory, audio_dir)
    interrupted_png = audio_dir / "cover-suggestions" / "album" / "interrupted.png"
    interrupted_png.write_bytes(_png_bytes())
    interrupted_staging_dir = cover_runner._staging_path(audio_dir, "album", running_job_id)
    interrupted_staging_dir.mkdir()
    (interrupted_staging_dir / "partial.png").write_bytes(_png_bytes())
    with factory() as session:
        assert update_job_status(session, running_job_id, JobStatusUpdate(JobStatus.RUNNING))
        session.add(AlbumCoverSuggestion(
            id="interrupted",
            album_id="album",
            job_id=running_job_id,
            png_path="cover-suggestions/album/interrupted.png",
        ))
        session.commit()
    _queue(factory, stack, "queued")

    assert cover_runner.recover_web_cover_jobs(factory, audio_dir) == 1

    with factory() as session:
        interrupted = session.get(Job, running_job_id)
        assert (interrupted.status, interrupted.error_type) == (JobStatus.FAILED, "server_restart")
        assert interrupted.session_id is None
        assert session.get(Job, "queued").status == JobStatus.QUEUED
        assert [item.id for item in session.query(AlbumCoverSuggestion)] == ["pending"]
    assert not interrupted_png.exists()
    assert pending_png.is_file()
    assert not interrupted_staging_dir.exists()

    assert asyncio.run(cover_runner.run_next_cover_job(app))
    with factory() as session:
        assert session.get(Job, "queued").status == JobStatus.COMPLETED


def test_cover_prompt_quotes_and_bounds_song_data(tmp_path: Path, pg_factory) -> None:
    _app, factory, _audio_dir, _stack = _cover_world(
        tmp_path, pg_factory, song_field="p" * (COVER_PROMPT_SONG_FIELD_MAX_CHARS + 10),
    )
    with factory() as session:
        album = session.get(Album, "album")
        prompt = cover_runner.build_cover_prompt(album, album.songs)

    assert len(prompt) <= COVER_PROMPT_MAX_CHARS
    assert '"style_prompt":"' + "p" * COVER_PROMPT_SONG_FIELD_MAX_CHARS in prompt
    assert '"lyrics_excerpt":"' + "p" * COVER_PROMPT_SONG_FIELD_MAX_CHARS in prompt
    assert "p" * (COVER_PROMPT_SONG_FIELD_MAX_CHARS + 1) not in prompt


def _prompt_song(track_number: int, field: str | None) -> SimpleNamespace:
    version = None if field is None else SimpleNamespace(prompt=field, lyrics=field)
    return SimpleNamespace(
        id=f"song-{track_number}", track_number=track_number, latest_version=version,
    )


def _prompt_tracks(songs: list[SimpleNamespace]) -> list[dict]:
    album = SimpleNamespace(title="T" * 200, artist="A" * 200)
    prompt = cover_runner.build_cover_prompt(album, songs)
    assert len(prompt) <= COVER_PROMPT_MAX_CHARS
    return json.loads(prompt.removeprefix("ALBUM_DATA="))["tracks"]


def test_a_song_without_a_version_contributes_no_track() -> None:
    tracks = _prompt_tracks([_prompt_song(1, None), _prompt_song(2, "words")])

    assert [track["track_number"] for track in tracks] == [2]


def test_tracks_stop_in_track_order_at_the_first_that_does_not_fit() -> None:
    long_field = "x" * COVER_PROMPT_SONG_FIELD_MAX_CHARS
    songs = [_prompt_song(number, long_field) for number in range(1, 9)]
    songs.append(_prompt_song(9, "short"))

    tracks = _prompt_tracks(list(reversed(songs)))

    numbers = [track["track_number"] for track in tracks]
    assert 0 < len(numbers) < len(songs) - 1
    assert numbers == list(range(1, len(numbers) + 1))


def test_recovery_of_a_job_whose_staging_directory_is_gone_counts_it_and_raises_nothing(
    tmp_path: Path, pg_factory,
) -> None:
    _app, factory, audio_dir, stack = _cover_world(tmp_path, pg_factory)
    job_id = _queue(factory, stack)
    with factory() as session:
        assert update_job_status(session, job_id, JobStatusUpdate(JobStatus.RUNNING))
        session.commit()
    assert not cover_runner._staging_path(audio_dir, "album", job_id).exists()

    assert cover_runner.recover_web_cover_jobs(factory, audio_dir) == 1

    with factory() as session:
        assert session.get(Job, job_id).status == JobStatus.FAILED


def test_a_failing_tick_is_recorded_on_the_registry_and_the_loop_goes_on(
    tmp_path: Path, pg_factory, monkeypatch,
) -> None:
    app, _factory, _audio_dir, _stack = _cover_world(tmp_path, pg_factory)
    registry = BackgroundLoopRegistry(tuple(BackgroundLoopName))
    ticks: list[int] = []
    failures_seen: list[int] = []

    async def tick_that_fails_then_succeeds(_app) -> bool:
        ticks.append(1)
        health = registry.loop_health()[BackgroundLoopName.COVER_RUNNER]
        failures_seen.append(health.consecutive_failures)
        if len(ticks) == 1:
            raise RuntimeError("database unavailable")
        return False

    async def end_after_the_second_tick(_seconds: float) -> None:
        if len(ticks) == 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(cover_runner, "run_next_cover_job", tick_that_fails_then_succeeds)
    monkeypatch.setattr(cover_runner.asyncio, "sleep", end_after_the_second_tick)

    loop = cover_runner.cover_runner_loop(app, registry)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(loop)

    assert failures_seen == [0, 1]
    health = registry.loop_health()[BackgroundLoopName.COVER_RUNNER]
    assert (health.consecutive_failures, health.last_error) == (0, None)


def test_a_picture_run_that_raises_ends_the_job_failed_and_leaves_no_suggestion(
    tmp_path: Path, pg_factory,
) -> None:
    app, factory, _audio_dir, stack = _cover_world(tmp_path, pg_factory)
    job_id = _queue(factory, stack)
    stack.behaves(raises(RuntimeError("gateway broke")))

    assert asyncio.run(cover_runner.run_next_cover_job(app))

    with factory() as session:
        assert session.get(Job, job_id).status == JobStatus.FAILED
        assert session.query(AlbumCoverSuggestion).count() == 0


def _cancel_the_job(factory) -> None:
    with factory() as session:
        assert update_job_status(session, "job", JobStatusUpdate(JobStatus.CANCELLED))
        session.commit()


def _delete_the_album(factory) -> None:
    with factory() as session:
        soft_delete_album(session, "album")
        session.commit()


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(_cancel_the_job, id="job-cancelled-before-the-start"),
        pytest.param(_delete_the_album, id="album-deleted-before-the-start"),
    ],
)
def test_a_job_or_album_gone_at_the_start_refuses_the_start(
    tmp_path: Path, pg_factory, change,
) -> None:
    _app, factory, _audio_dir, stack = _cover_world(tmp_path, pg_factory)
    job_id = _queue(factory, stack)
    with factory() as session:
        assert update_job_status(session, job_id, JobStatusUpdate(JobStatus.RUNNING))
        session.commit()
    change(factory)

    with pytest.raises(cover_runner.CoverSuggestionJobError):
        cover_runner._load_cover_start(factory, job_id)
