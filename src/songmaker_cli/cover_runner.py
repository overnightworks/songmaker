"""The web executor for cover jobs: claim, draw through the gateway, publish and recover."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import threading
import uuid
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from PIL import Image
from redis.exceptions import RedisError
from sqlalchemy import or_
from webauth.ports import AuthenticatedUser

from songmaker_cli.agent.backend import TurnCaller, TurnProblem, run_cover_picture
from songmaker_cli.api_models import AgentProblem
from songmaker_cli.constants import (
    ALBUM_COVER_SUGGESTIONS_DIRNAME,
    COVER_PROMPT_MAX_CHARS,
    COVER_PROMPT_SONG_FIELD_MAX_CHARS,
    REDIS_KEY_PREFIX,
)
from songmaker_cli.cover_job_errors import CoverSuggestionJobError
from songmaker_cli.cover_suggestions import remove_cover_suggestion_files, suggestion_png_path
from songmaker_cli.covers import CoverRejectedError, ai_mark_png_info, decode_cover_image
from songmaker_cli.db.models import AlbumCoverSuggestion, Job
from songmaker_cli.db.queries.albums import get_album
from songmaker_cli.db.queries.auth import get_user
from songmaker_cli.db.queries.cover_suggestions import delete_job_cover_suggestions
from songmaker_cli.db.queries.jobs import (
    JobStatusUpdate,
    claim_next_cover_job,
    get_job,
    update_job_status,
)
from songmaker_cli.db.queries.songs import list_songs
from songmaker_cli.health_types import BackgroundLoopName, BackgroundLoopRegistry
from songmaker_cli.job_timing import JOB_HEARTBEAT_INTERVAL_SECONDS
from songmaker_cli.job_types import JobStatus, JobType
from songmaker_cli.jobs._runtime import _touch_heartbeat, _update_job

log = logging.getLogger(__name__)

COVER_RUNNER_POLL_INTERVAL_SECONDS = 1.0
COVER_PICTURE_CANCELLED_LOG: Final = "Cover job %s was cancelled during its picture"
# The job's ``error`` is a closed sentence per problem; the editor words ``error_type`` itself.
_PROBLEM_SENTENCES: Final[dict[AgentProblem, str]] = {
    AgentProblem.UNAVAILABLE: "Cover suggestions are unavailable right now. Try again later.",
    AgentProblem.BUSY: "Cover suggestions are busy. Try again when Suggest opens.",
    AgentProblem.BUDGET_SPENT: "The budget for cover suggestions is used up. Try again later.",
    AgentProblem.NOT_ENABLED: (
        "Cover suggestions are not enabled for your account. Ask an admin to enable them."
    ),
    AgentProblem.SIGN_IN_AGAIN: "Log in again to get cover suggestions.",
}
_PICTURE_REJECTED: Final = TurnProblem(AgentProblem.UNAVAILABLE, "picture_rejected")
_RUN_FAILED: Final = TurnProblem(AgentProblem.UNAVAILABLE, "cover run failed")

# A cancel commits to PostgreSQL, then names the job id on this channel: the process that
# draws the picture receives it, reads the job and stops the picture. Delivery is
# at-most-once; the committed status is the truth the publication checks.
COVER_CANCEL_CHANNEL: Final = f"{REDIS_KEY_PREFIX}:cover_cancel"
_CANCEL_POLL_SECONDS: Final = 1.0
_SUBSCRIPTION_CONFIRMATION_SECONDS: Final = 5.0


@dataclass(frozen=True)
class _CoverStart:
    """What a claimed job needs before its picture: read once, in one short DB session."""

    album_id: str
    album_data: str
    user: AuthenticatedUser | None
    session_id: str | None


def publish_cover_cancel(redis, job_id: str) -> None:
    """Tell every web process that a cover job's cancellation has committed.

    Only the id travels. An unreachable Redis leaves the committed cancel standing: the
    picture then ends on its own and its publication refuses the cancelled job.
    """
    try:
        redis.publish(COVER_CANCEL_CHANNEL, job_id)
    except RedisError:
        log.warning("A cover job's cancel could not reach the process drawing it")


def _subscribe_to_cancellations(redis):
    """Subscribe to the cancel channel; ``None`` when Redis does not confirm it."""
    pubsub = redis.pubsub()
    try:
        pubsub.subscribe(COVER_CANCEL_CHANNEL)
        if pubsub.get_message(timeout=_SUBSCRIPTION_CONFIRMATION_SECONDS) is not None:
            return pubsub
    except RedisError:
        log.warning("Cover cancel channel unreachable; a cancel will not stop the picture")
    pubsub.close()
    return None


def _wait_for_cancellation(pubsub, db_factory, job_id: str, stop: threading.Event) -> bool:
    """Block until ``job_id`` is named and cancelled in the database, or ``stop`` is set."""
    try:
        while not stop.is_set():
            message = pubsub.get_message(timeout=_CANCEL_POLL_SECONDS)
            if (
                message is not None
                and message["type"] == "message"
                and message["data"] == job_id
                and _is_cancelled(db_factory, job_id)
            ):
                return True
    except RedisError:
        log.warning("Cover cancel channel lost; a cancel will not stop the picture")
    finally:
        pubsub.close()
    return False


_ENDED_WITHOUT_COVER: Final = (JobStatus.FAILED, JobStatus.CANCELLED)
_STAGING_SUFFIX: Final = ".staging"
_STAGING_DIRECTORY_PATTERN: Final = f".*{_STAGING_SUFFIX}"


def reconcile_reaped_cover_jobs(db_factory, audio_dir: Path) -> int:
    """Remove the suggestion and staging directory a failed or cancelled cover left.

    A COMPLETED job's suggestion stays pending. The rows are deleted and
    committed before the files go, so a crash between the two leaves files no
    row points to and the next run removes them.
    Returns the number of cover jobs cleaned.
    """
    staged_job_ids = [
        path.name.removeprefix(".").removesuffix(_STAGING_SUFFIX)
        for path in (audio_dir / ALBUM_COVER_SUGGESTIONS_DIRNAME).glob(_STAGING_DIRECTORY_PATTERN)
    ]
    with db_factory() as session:
        ended_job_ids = {
            job_id for (job_id,) in session.query(Job.id).filter(
                Job.type == JobType.COVER,
                Job.status.in_(_ENDED_WITHOUT_COVER),
                or_(
                    Job.id.in_(staged_job_ids),
                    Job.id.in_(
                        session.query(AlbumCoverSuggestion.job_id).filter(
                            AlbumCoverSuggestion.job_id.isnot(None),
                        ),
                    ),
                ),
            )
        }
        staging_dirs = [cover_staging_path(audio_dir, job_id) for job_id in ended_job_ids]
        suggestion_paths = delete_job_cover_suggestions(session, list(ended_job_ids))
        session.commit()
    remove_cover_suggestion_files(audio_dir, suggestion_paths)
    for staging_dir in staging_dirs:
        shutil.rmtree(staging_dir, ignore_errors=True)
    return len(ended_job_ids)


async def run_next_cover_job(app) -> bool:
    """Claim and run one queued cover job."""
    ctx = app.state.ctx
    job_id = await asyncio.to_thread(_claim_next_cover_job, ctx.db, ctx.owner_id)
    if job_id is None:
        return False
    await run_claimed_cover_suggestion_job(app, job_id)
    return True


async def cover_runner_loop(app, registry: BackgroundLoopRegistry) -> None:
    """Poll the cover queue and publish one completed suggestion per tick."""
    while True:
        try:
            await run_next_cover_job(app)
        except Exception as exc:
            registry.record_failure(BackgroundLoopName.COVER_RUNNER, exc)
            log.exception("Cover runner tick failed")
        else:
            registry.record_success(BackgroundLoopName.COVER_RUNNER)
        await asyncio.sleep(COVER_RUNNER_POLL_INTERVAL_SECONDS)


async def run_claimed_cover_suggestion_job(app, job_id: str) -> None:
    """Draw and publish the one suggestion of an already-running cover job.

    The caller alone owns claiming the queued job; this owner owns all
    subsequent heartbeats, the picture, atomic publish, cleanup, and terminal
    status. An explicit cancel has already written the terminal status.
    """
    db_factory = app.state.ctx.db
    audio_dir = app.state.ctx.audio_dir
    await asyncio.to_thread(_touch_heartbeat, db_factory, job_id)
    heartbeat_task = asyncio.create_task(_keep_heartbeats(db_factory, job_id))
    staging_dir: Path | None = None
    try:
        start = await asyncio.to_thread(_load_cover_start, db_factory, job_id)
        drawn = await _draw(app, job_id, start)
        if drawn is None:
            return
        image = await asyncio.to_thread(_checked_picture, drawn)
        if isinstance(image, TurnProblem):
            await asyncio.to_thread(_end_with_problem, db_factory, job_id, image)
            return
        suggestion_id = str(uuid.uuid4())
        staging_dir = await asyncio.to_thread(_staging_directory, audio_dir, job_id)
        await asyncio.to_thread(_write_staged_png, staging_dir, suggestion_id, image)
        await asyncio.to_thread(_touch_heartbeat, db_factory, job_id)

        publication = asyncio.create_task(asyncio.to_thread(
            _publish_suggestion,
            db_factory,
            audio_dir,
            start.album_id,
            job_id,
            suggestion_id,
            staging_dir,
        ))
        try:
            await asyncio.shield(publication)
        except asyncio.CancelledError:
            # The thread owns rollback; let it settle before removing staging.
            with suppress(Exception):
                await _await_thread_completion(publication)
            raise
        await asyncio.to_thread(shutil.rmtree, staging_dir)
        staging_dir = None
    except asyncio.CancelledError:
        await asyncio.to_thread(_remove_staging_directory, staging_dir)
        raise
    except Exception:
        log.exception("Cover job %s failed", job_id)
        await asyncio.to_thread(_remove_staging_directory, staging_dir)
        await asyncio.to_thread(_end_with_problem, db_factory, job_id, _RUN_FAILED)
    finally:
        await _stop_heartbeats(heartbeat_task)


async def _draw(app, job_id: str, start: _CoverStart) -> bytes | TurnProblem | None:
    """The picture for ``start``, why there is none, or ``None`` after an explicit cancel.

    The picture runs as its own task so a cancel stops it without cancelling this runner.
    """
    if start.user is None:
        return TurnProblem(AgentProblem.NOT_ENABLED, "user gone")
    if start.session_id is None:
        return TurnProblem(AgentProblem.SIGN_IN_AGAIN, "no asking session")
    caller = TurnCaller(app, start.session_id, start.user)
    ctx = app.state.ctx
    # Subscribed before the picture reads the job: a cancel committed after that read is heard.
    pubsub = await asyncio.to_thread(_subscribe_to_cancellations, ctx.redis)
    stop_listening = threading.Event()
    picture = asyncio.create_task(
        _picture_while_running(ctx.db, job_id, caller, start.album_data),
    )
    cancellation = (
        None if pubsub is None else asyncio.ensure_future(asyncio.to_thread(
            _wait_for_cancellation, pubsub, ctx.db, job_id, stop_listening,
        ))
    )
    try:
        await asyncio.wait(
            {picture} if cancellation is None else {picture, cancellation},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if (
            not picture.done()
            and cancellation is not None
            and cancellation.done()
            and cancellation.result()
        ):
            picture.cancel()
        await asyncio.wait({picture})
    finally:
        stop_listening.set()
        if not picture.done():
            picture.cancel()
            await asyncio.wait({picture})
    if picture.cancelled():
        log.info(COVER_PICTURE_CANCELLED_LOG, job_id)
        return None
    error = picture.exception()
    if error is not None:
        log.error("Cover job %s: the picture run raised %s", job_id, type(error).__qualname__)
        return _RUN_FAILED
    return picture.result()


async def _picture_while_running(
    db_factory, job_id: str, caller: TurnCaller, album_data: str,
) -> bytes | TurnProblem | None:
    # This task is registered before it runs: a cancel committed after the read below reaches
    # it through the cancel channel, and one committed before it leaves no request to send.
    if not await asyncio.to_thread(_is_still_running, db_factory, job_id):
        log.info("Cover job %s was cancelled before its picture", job_id)
        return None
    return await run_cover_picture(caller, album_data)


def _checked_picture(drawn: bytes | TurnProblem) -> Image.Image | TurnProblem:
    if isinstance(drawn, TurnProblem):
        return drawn
    try:
        image, _format = decode_cover_image(drawn)
    except CoverRejectedError:
        return _PICTURE_REJECTED
    return image


def _end_with_problem(db_factory, job_id: str, problem: TurnProblem) -> None:
    log.warning("Cover job %s ended %s: %s", job_id, problem.problem.value, problem.detail)
    _update_job(
        db_factory,
        job_id,
        JobStatus.FAILED,
        error=_PROBLEM_SENTENCES[problem.problem],
        error_type=problem.problem.value,
        retry_after_seconds=problem.retry_after_seconds,
    )


def build_cover_prompt(album, songs) -> str:
    """Build the bounded, deterministic album data the picture agent draws from."""
    header = "ALBUM_DATA="
    album_data = {"title": album.title, "artist": album.artist, "tracks": []}
    base = header + json.dumps(album_data, ensure_ascii=False, separators=(",", ":"))
    track_budget = max(COVER_PROMPT_MAX_CHARS - len(base), 0)
    tracks: list[dict[str, object]] = []
    for song in sorted(songs, key=lambda item: (item.track_number, item.id)):
        version = song.latest_version
        if version is None:
            continue
        candidate = {
            "track_number": song.track_number,
            "style_prompt": version.prompt[:COVER_PROMPT_SONG_FIELD_MAX_CHARS],
            "lyrics_excerpt": version.lyrics[:COVER_PROMPT_SONG_FIELD_MAX_CHARS],
        }
        candidate_length = len(json.dumps(candidate, ensure_ascii=False, separators=(",", ":")))
        separator_length = 1 if tracks else 0
        if candidate_length + separator_length > track_budget:
            break
        tracks.append(candidate)
        track_budget -= candidate_length + separator_length
    album_data["tracks"] = tracks
    return header + json.dumps(album_data, ensure_ascii=False, separators=(",", ":"))


def _claim_next_cover_job(db_factory, owner_id: str) -> str | None:
    with db_factory() as session:
        job = claim_next_cover_job(session, owner_id)
        session.commit()
        return None if job is None else job.id


def _load_cover_start(db_factory, job_id: str) -> _CoverStart:
    # Closed before the picture: its group read renews the session and needs no open
    # transaction on that row.
    with db_factory() as session:
        job = get_job(session, job_id)
        if job is None or job.status != JobStatus.RUNNING or job.album_id is None:
            raise CoverSuggestionJobError()
        album = get_album(session, job.album_id)
        if album is None:
            raise CoverSuggestionJobError()
        return _CoverStart(
            album_id=album.id,
            album_data=build_cover_prompt(album, list_songs(session, album_id=album.id)),
            user=_user_or_none(session, job.user_id),
            session_id=job.session_id,
        )


def _is_cancelled(db_factory, job_id: str) -> bool:
    with db_factory() as session:
        job = get_job(session, job_id)
        return job is not None and job.status == JobStatus.CANCELLED


def _is_still_running(db_factory, job_id: str) -> bool:
    with db_factory() as session:
        job = get_job(session, job_id)
        return job is not None and job.status == JobStatus.RUNNING


def _user_or_none(session, user_id: str | None) -> AuthenticatedUser | None:
    user = None if user_id is None else get_user(session, user_id)
    if user is None:
        return None
    return AuthenticatedUser(id=user.id, username=user.username, role=user.role, agent=None)


def _staging_directory(audio_dir: Path, job_id: str) -> Path:
    staging_dir = cover_staging_path(audio_dir, job_id)
    staging_dir.parent.mkdir(parents=True, exist_ok=True)
    staging_dir.mkdir()
    return staging_dir


def cover_staging_path(audio_dir: Path, job_id: str) -> Path:
    """The directory a cover job draws into; its name holds the job id alone."""
    return audio_dir / ALBUM_COVER_SUGGESTIONS_DIRNAME / f".{job_id}{_STAGING_SUFFIX}"


def _write_staged_png(staging_dir: Path, suggestion_id: str, image: Image.Image) -> None:
    image.save(staging_dir / f"{suggestion_id}.png", format="PNG", pnginfo=ai_mark_png_info())


def _publish_suggestion(
    db_factory,
    audio_dir: Path,
    album_id: str,
    job_id: str,
    suggestion_id: str,
    staging_dir: Path,
) -> None:
    path = f"{ALBUM_COVER_SUGGESTIONS_DIRNAME}/{album_id}/{suggestion_id}.png"
    target = suggestion_png_path(audio_dir, album_id, suggestion_id)
    moved = False
    try:
        with db_factory() as session:
            if not update_job_status(
                session, job_id, JobStatusUpdate(JobStatus.COMPLETED, progress=1.0),
            ):
                raise CoverSuggestionJobError()
            target.parent.mkdir(parents=True, exist_ok=True)
            (staging_dir / f"{suggestion_id}.png").replace(target)
            moved = True
            session.add(AlbumCoverSuggestion(
                id=suggestion_id,
                album_id=album_id,
                job_id=job_id,
                png_path=path,
            ))
            session.commit()
    except Exception:
        if moved:
            remove_cover_suggestion_files(audio_dir, [path])
        raise


def _remove_staging_directory(staging_dir: Path | None) -> None:
    if staging_dir is not None:
        shutil.rmtree(staging_dir, ignore_errors=True)


async def _keep_heartbeats(db_factory, job_id: str) -> None:
    while True:
        await asyncio.sleep(JOB_HEARTBEAT_INTERVAL_SECONDS)
        await asyncio.to_thread(_touch_heartbeat, db_factory, job_id)


async def _await_thread_completion[T](task: asyncio.Task[T]) -> T:
    """Let a thread settle before cleanup, despite repeat task cancellation."""
    current_task = asyncio.current_task()
    while True:
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if current_task is None:
                raise
            current_task.uncancel()


async def _stop_heartbeats(task: asyncio.Task[None]) -> None:
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
