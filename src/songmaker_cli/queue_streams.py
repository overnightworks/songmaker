"""Build and serve cached continuous queue streams.

This module owns queue-stream duration and ffmpeg timeout limits. A host
measurement on 2026-09-03 concatenated 900.049 seconds of synthetic MP3 audio
in 5.394 seconds (166.8 audio seconds per wall second). The 100x minimum rate
and 120-second reserve keep the six-hour product cap within a measured,
conservative ffmpeg budget.
"""

from __future__ import annotations

import hashlib
import logging
import random
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from math import ceil
from pathlib import Path
from typing import Final, Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session
from webauth.ports import AuthenticatedUser
from webauth.rate_limit import RedisRateLimitBackend

import songmaker_cli.constants as _consts
from songmaker_cli import audio_files
from songmaker_cli.api_helpers import (
    RateLimiterUnavailable,
    RateLimitRejected,
    check_generation_access,
    enforce_rate_limit,
    get_cached_limiter,
)
from songmaker_cli.api_models.queue_streams import (
    LibraryTakePool,
    QueueStreamManifestResponse,
    QueueStreamSkipResponse,
    QueueStreamTrackResponse,
)
from songmaker_cli.api_models.songs import generation_version_lyrics
from songmaker_cli.app_context import AppContext
from songmaker_cli.audio_paths import (
    AudioFileNotFoundError,
    AudioPathRejectedError,
    canonical_audio_path,
    resolve_audio_path,
)
from songmaker_cli.constants import REDIS_RL_QUEUE_STREAM_PREFIX, LimiterFailurePolicy
from songmaker_cli.db.models import Generation, Song
from songmaker_cli.db.queries.songs import list_songs
from songmaker_cli.object_store import ObjectMissingError, StoredObject
from songmaker_cli.queue_stream_build_lock import build_lock as _build_lock
from songmaker_cli.refusals import Refusal
from songmaker_cli.timestamps import utcnow

log = logging.getLogger(__name__)

QUEUE_STREAM_KEY_PREFIX = "queue-streams/"
QUEUE_STREAM_TTL = timedelta(hours=8)
QUEUE_STREAM_ORPHAN_MAX_AGE = timedelta(hours=24)
QUEUE_STREAM_MAX_TRACKS = 200
QUEUE_STREAM_FFMPEG_MIN_AUDIO_SECONDS_PER_WALL_SECOND = 100
QUEUE_STREAM_FFMPEG_TIMEOUT_RESERVE_SECONDS = 120
QUEUE_STREAM_MAX_DURATION_SECONDS = 60 * 60 * 6
QUEUE_STREAM_MAX_CACHE_BYTES = 1024 * 1024 * 1024


def queue_stream_ffmpeg_timeout_seconds(duration_seconds: float) -> int:
    return (
        ceil(duration_seconds / QUEUE_STREAM_FFMPEG_MIN_AUDIO_SECONDS_PER_WALL_SECOND)
        + QUEUE_STREAM_FFMPEG_TIMEOUT_RESERVE_SECONDS
    )


FFMPEG_TIMEOUT_SECONDS = queue_stream_ffmpeg_timeout_seconds(QUEUE_STREAM_MAX_DURATION_SECONDS)
QUEUE_STREAM_DURATION_LIMIT_DETAIL = "Queue duration exceeds the maximum stream duration"
QUEUE_STREAM_REDIS_PREFIX: Final = f"{_consts.REDIS_KEY_PREFIX}:queue-stream"
QUEUE_STREAM_MANIFEST_SUFFIX: Final = ".json"
QUEUE_STREAM_AUDIO_SUFFIX: Final = ".mp3"
QUEUE_STREAM_AUDIO_CONTENT_TYPE: Final = "audio/mpeg"
QUEUE_STREAM_MANIFEST_CONTENT_TYPE: Final = "application/json"
QUEUE_STREAM_NOT_FOUND_DETAIL: Final = "Queue stream not found"
QUEUE_STREAM_AUDIO_NOT_FOUND_DETAIL: Final = "Queue stream audio not found"


SnapshotScope = Literal["auth", "shared-playlist", "shared-album"]


class QueueStreamManifest(BaseModel):
    """The record of one queue-stream snapshot, stored beside its audio in the bucket.

    ``parse`` is the only deserializer, so a truncated or field-missing object fails
    validation once, in one place, instead of raising a raw ``KeyError`` deep in a caller.
    """

    snapshot_id: str
    scope: SnapshotScope
    scope_id: str
    content_hash: str
    expires_at: datetime
    total_duration: float
    tracks: list[QueueStreamTrackResponse]
    windowed: bool = False

    @classmethod
    def parse(cls, snapshot_id: str, raw: bytes) -> QueueStreamManifest | None:
        try:
            return cls.model_validate_json(raw)
        except ValidationError as exc:
            log.warning("Queue stream manifest %s failed validation: %s", snapshot_id, exc)
            return None

    def response(self, stream_url: str) -> QueueStreamManifestResponse:
        return QueueStreamManifestResponse(
            snapshot_id=self.snapshot_id,
            stream_url=stream_url,
            expires_at=self.expires_at.isoformat(),
            total_duration=self.total_duration,
            windowed=self.windowed,
            tracks=self.tracks,
        )


@dataclass(frozen=True)
class QueueStreamSource:
    key: str
    index: int
    entry_id: str | None
    generation: Generation
    audio_url: str


@dataclass(frozen=True)
class QueueStreamPreparedSource:
    source: QueueStreamSource
    audio_path: Path
    duration: float
    size: int
    mtime_ns: int


@dataclass(frozen=True)
class QueueStreamAdmission:
    prepared_sources: list[QueueStreamPreparedSource]
    windowed_by_count: bool


def track_source_from_generation(
    gen: Generation,
    *,
    key: str,
    index: int,
    entry_id: str | None,
    audio_url: str,
) -> QueueStreamSource:
    return QueueStreamSource(
        key=key,
        index=index,
        entry_id=entry_id,
        generation=gen,
        audio_url=audio_url,
    )


def ensure_sources_detachable(sources: list[QueueStreamSource]) -> None:
    """Force-load the ORM relations a build touches after the caller's DB
    session closes: ``generation.song``, ``song.album``, and
    ``generation.version``.

    Call this while the request's session is still open, right before
    closing it. Sources whose query already eager-loaded these relations
    are unaffected -- accessing an already-loaded attribute never touches
    the session.
    """
    for source in sources:
        gen = source.generation
        _ = gen.song.album
        _ = gen.version


def build_queue_stream_snapshot(
    ctx: AppContext,
    sources: list[QueueStreamSource],
    *,
    scope: SnapshotScope,
    scope_id: str,
    stream_url: str,
) -> QueueStreamManifestResponse:
    admission = prepare_queue_stream_admission(ctx, sources)
    windowed_by_count = admission.windowed_by_count
    prepared_sources = admission.prepared_sources
    content_hash = _content_hash(scope, scope_id, prepared_sources, windowed=windowed_by_count)
    with _build_lock(ctx, content_hash):
        reusable = _find_reusable_snapshot(ctx, content_hash, stream_url)
        if reusable:
            return reusable
        return _build_queue_stream_snapshot(
            ctx,
            prepared_sources,
            scope=scope,
            scope_id=scope_id,
            stream_url=stream_url,
            content_hash=content_hash,
            windowed_by_count=windowed_by_count,
        )


def _build_queue_stream_snapshot(
    ctx: AppContext,
    prepared_sources: list[QueueStreamPreparedSource],
    *,
    scope: SnapshotScope,
    scope_id: str,
    stream_url: str,
    content_hash: str,
    windowed_by_count: bool = False,
) -> QueueStreamManifestResponse:
    snapshot_id = uuid.uuid4().hex
    audio_paths: list[Path] = []
    tracks: list[QueueStreamTrackResponse] = []
    offset = 0.0
    for prepared in prepared_sources:
        source = prepared.source
        end = offset + prepared.duration
        tracks.append(_track_response(source, source.generation, prepared.duration, offset, end))
        audio_paths.append(prepared.audio_path)
        offset = end
    _render_and_store_snapshot_audio(ctx, snapshot_id, audio_paths)
    manifest = QueueStreamManifest(
        snapshot_id=snapshot_id,
        scope=scope,
        scope_id=scope_id,
        content_hash=content_hash,
        expires_at=utcnow() + QUEUE_STREAM_TTL,
        total_duration=round(offset, 3),
        windowed=windowed_by_count,
        tracks=tracks,
    )
    ctx.object_store.put_bytes(
        queue_stream_manifest_object_key(snapshot_id),
        manifest.model_dump_json().encode("utf-8"),
        content_type=QUEUE_STREAM_MANIFEST_CONTENT_TYPE,
    )
    _publish_content_hash(ctx, manifest)
    _enforce_cache_quota(ctx, protected_snapshot_ids={snapshot_id})

    return manifest.response(stream_url)


def prepare_queue_stream_admission(
    ctx: AppContext,
    sources: list[QueueStreamSource],
) -> QueueStreamAdmission:
    if not sources:
        raise HTTPException(422, "Queue has no playable tracks")  # unread: share
    windowed_by_count = len(sources) > QUEUE_STREAM_MAX_TRACKS
    sources = sources[:QUEUE_STREAM_MAX_TRACKS]
    prepared: list[QueueStreamPreparedSource] = []
    total_duration = 0.0
    for source in sources:
        gen = source.generation
        if not gen.mp3_path:
            raise HTTPException(422, "Queue contains a generation without audio")  # unread: share
        audio_path = canonical_audio_path(ctx.audio_dir, gen.mp3_path)
        try:
            stat = audio_path.stat()
        except FileNotFoundError as exc:
            raise AudioFileNotFoundError(gen.mp3_path) from exc
        duration = probe_audio_duration(audio_path)
        total_duration += duration
        if total_duration > QUEUE_STREAM_MAX_DURATION_SECONDS:
            raise HTTPException(422, QUEUE_STREAM_DURATION_LIMIT_DETAIL)  # unread: share
        prepared.append(
            QueueStreamPreparedSource(
                source=source,
                audio_path=audio_path,
                duration=duration,
                size=stat.st_size,
                mtime_ns=stat.st_mtime_ns,
            )
        )
    return QueueStreamAdmission(
        prepared_sources=prepared,
        windowed_by_count=windowed_by_count,
    )


def _content_hash(
    scope: SnapshotScope,
    scope_id: str,
    prepared_sources: list[QueueStreamPreparedSource],
    *,
    windowed: bool,
) -> str:
    hasher = hashlib.sha256()
    hasher.update(scope.encode("utf-8"))
    hasher.update(b"\0")
    hasher.update(scope_id.encode("utf-8"))
    hasher.update(b"\0")
    hasher.update(str(windowed).encode("ascii"))
    for prepared in prepared_sources:
        source = prepared.source
        gen = source.generation
        parts = [
            str(source.index),
            source.key,
            source.entry_id or "",
            gen.id,
            gen.version_id or "",
            gen.mp3_path or "",
            source.audio_url,
            str(prepared.size),
            str(prepared.mtime_ns),
            f"{prepared.duration:.3f}",
        ]
        hasher.update(b"\0")
        hasher.update("\x1f".join(parts).encode("utf-8"))
    return hasher.hexdigest()


def _render_and_store_snapshot_audio(
    ctx: AppContext, snapshot_id: str, audio_paths: list[Path],
) -> None:
    """Concatenate the takes in a temporary directory and put the result in the bucket."""
    with tempfile.TemporaryDirectory(prefix="queue-stream-") as work_dir:
        concat_path = Path(work_dir) / "concat.txt"
        output_path = Path(work_dir) / "stream.mp3"
        write_concat_file(concat_path, audio_paths)
        run_ffmpeg_concat(concat_path, output_path)
        ctx.object_store.put_file(
            queue_stream_audio_object_key(snapshot_id), output_path,
            content_type=QUEUE_STREAM_AUDIO_CONTENT_TYPE,
        )


def queue_stream_audio_object_key(snapshot_id: str) -> str:
    return f"{QUEUE_STREAM_KEY_PREFIX}{snapshot_id}{QUEUE_STREAM_AUDIO_SUFFIX}"


def queue_stream_manifest_object_key(snapshot_id: str) -> str:
    return f"{QUEUE_STREAM_KEY_PREFIX}{snapshot_id}{QUEUE_STREAM_MANIFEST_SUFFIX}"


def _content_hash_key(content_hash: str) -> str:
    return f"{QUEUE_STREAM_REDIS_PREFIX}:content:{content_hash}"


def _publish_content_hash(ctx: AppContext, manifest: QueueStreamManifest) -> None:
    ctx.redis.set(
        _content_hash_key(manifest.content_hash), manifest.snapshot_id, ex=QUEUE_STREAM_TTL,
    )


def _stored_manifest(ctx: AppContext, snapshot_id: str) -> QueueStreamManifest | None:
    """The snapshot's record in the bucket; None when it is absent or unreadable."""
    try:
        raw = ctx.object_store.get_bytes(queue_stream_manifest_object_key(snapshot_id))
    except ObjectMissingError:
        return None
    return QueueStreamManifest.parse(snapshot_id, raw)


def _find_reusable_snapshot(
    ctx: AppContext, content_hash: str, stream_url: str,
) -> QueueStreamManifestResponse | None:
    snapshot_id = ctx.redis.get(_content_hash_key(content_hash))
    manifest = None if snapshot_id is None else _stored_manifest(ctx, snapshot_id)
    if manifest is None or manifest.expires_at < utcnow():
        return None
    return manifest.response(stream_url)


def load_queue_stream_manifest(ctx: AppContext, snapshot_id: str) -> QueueStreamManifest:
    if not _valid_snapshot_id(snapshot_id):
        raise HTTPException(404, QUEUE_STREAM_NOT_FOUND_DETAIL)  # unread: share
    manifest = _stored_manifest(ctx, snapshot_id)
    if manifest is None:
        raise HTTPException(404, QUEUE_STREAM_NOT_FOUND_DETAIL)  # unread: share
    if manifest.expires_at < utcnow():
        delete_snapshot_files(ctx, snapshot_id)
        raise HTTPException(404, "Queue stream expired")  # unread: share
    return manifest


def cleanup_expired_queue_streams(ctx: AppContext) -> None:
    now = utcnow()
    stored = list(ctx.object_store.list(QUEUE_STREAM_KEY_PREFIX))
    live_snapshot_ids = _remove_expired_queue_stream_snapshots(ctx, stored, now)
    _remove_expired_queue_stream_orphans(ctx, stored, live_snapshot_ids, now)
    _enforce_cache_quota(ctx)


def _remove_expired_queue_stream_snapshots(
    ctx: AppContext, stored: list[StoredObject], now: datetime,
) -> set[str]:
    live_snapshot_ids: set[str] = set()
    for entry in stored:
        snapshot_id = _snapshot_id_of_object(entry.key, QUEUE_STREAM_MANIFEST_SUFFIX)
        if snapshot_id is None:
            continue
        manifest = _stored_manifest(ctx, snapshot_id)
        if manifest is not None and manifest.expires_at >= now:
            live_snapshot_ids.add(snapshot_id)
        else:
            delete_snapshot_files(ctx, snapshot_id)
    return live_snapshot_ids


def _remove_expired_queue_stream_orphans(
    ctx: AppContext, stored: list[StoredObject], live_snapshot_ids: set[str], now: datetime,
) -> None:
    """Delete objects no live snapshot owns, once too old for a build to still be writing them."""
    orphan_cutoff = now - QUEUE_STREAM_ORPHAN_MAX_AGE
    ctx.object_store.delete([
        entry.key for entry in stored
        if entry.last_modified < orphan_cutoff
        and _owner_snapshot_id(entry.key) not in live_snapshot_ids
    ])


def delete_snapshot_files(ctx: AppContext, snapshot_id: str) -> None:
    """Delete the record before the audio, so a record never outlives the audio it names."""
    ctx.object_store.delete([queue_stream_manifest_object_key(snapshot_id)])
    ctx.object_store.delete([queue_stream_audio_object_key(snapshot_id)])


def probe_audio_duration(audio_path: Path) -> float:
    """Request-boundary wrapper: an unreadable file is a 422, not a None."""
    duration = audio_files.read_audio_duration(audio_path)
    if duration is None:
        raise HTTPException(422, "Could not read audio duration")  # unread: share
    return duration


def write_concat_file(concat_path: Path, audio_paths: list[Path]) -> None:
    lines = [f"file '{_escape_concat_path(path)}'" for path in audio_paths]
    concat_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_ffmpeg_concat(concat_path: Path, output_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise HTTPException(503, "ffmpeg is not available")  # unread: share

    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_path),
        "-c:a",
        "libmp3lame",
        "-b:a",
        "192k",
        str(output_path),
    ]
    try:
        subprocess.run(  # noqa: S603 - ffmpeg argv without a shell and both paths lie in the build's temporary directory
            cmd,
            check=True,
            capture_output=True,
            text=True,
            timeout=FFMPEG_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        output_path.unlink(missing_ok=True)
        raise HTTPException(504, "Queue stream build timed out") from exc  # unread: share
    except subprocess.CalledProcessError as exc:
        output_path.unlink(missing_ok=True)
        detail = str.strip(exc.stderr or exc.stdout or "")
        log.warning("ffmpeg queue stream build failed: %s", detail)
        raise HTTPException(422, "Could not build queue stream") from exc  # unread: share


def public_queue_stream_manifest(
    snapshot: QueueStreamManifestResponse,
) -> QueueStreamManifestResponse:
    return snapshot.model_copy(
        update={
            "tracks": [
                track.model_copy(update={"lyrics": None, "seed": None, "mp3_path": ""})
                for track in snapshot.tracks
            ]
        }
    )


def _track_response(
    source: QueueStreamSource,
    gen: Generation,
    duration: float,
    start: float,
    end: float,
) -> QueueStreamTrackResponse:
    song = gen.song
    album = song.album if song else None
    return QueueStreamTrackResponse(
        key=source.key,
        index=source.index,
        entry_id=source.entry_id,
        generation_id=gen.id,
        song_id=song.id if song else "",
        song_title=song.title if song else "",
        artist=album.artist if album else "",
        album_title=album.title if album else "",
        lyrics=generation_version_lyrics(gen),
        generation_number=gen.generation_number,
        mp3_path=gen.mp3_path,
        audio_url=source.audio_url,
        seed=gen.seed,
        model_mode=gen.model_mode,
        duration=round(duration, 3),
        start_offset=round(start, 3),
        end_offset=round(end, 3),
    )


def _enforce_cache_quota(
    ctx: AppContext,
    *,
    protected_snapshot_ids: set[str] | None = None,
) -> None:
    # Just-built snapshots (protected_snapshot_ids) are counted but never evicted.
    eviction_protected = protected_snapshot_ids or set()

    total_bytes = 0
    sized_snapshots: list[tuple[datetime, int, str]] = []
    for entry in ctx.object_store.list(QUEUE_STREAM_KEY_PREFIX):
        snapshot_id = _snapshot_id_of_object(entry.key, QUEUE_STREAM_AUDIO_SUFFIX)
        if snapshot_id is None:
            continue
        total_bytes += entry.size
        sized_snapshots.append((entry.last_modified, entry.size, snapshot_id))

    for _, size, snapshot_id in sorted(sized_snapshots):
        if total_bytes <= QUEUE_STREAM_MAX_CACHE_BYTES:
            break
        if snapshot_id in eviction_protected:
            continue
        delete_snapshot_files(ctx, snapshot_id)
        total_bytes -= size


def _snapshot_id_of_object(key: str, suffix: str) -> str | None:
    """The snapshot id a key of this kind names, or None for any other object."""
    name = key.removeprefix(QUEUE_STREAM_KEY_PREFIX)
    snapshot_id = name.removesuffix(suffix)
    return snapshot_id if name.endswith(suffix) and _valid_snapshot_id(snapshot_id) else None


def _owner_snapshot_id(key: str) -> str | None:
    return _snapshot_id_of_object(key, QUEUE_STREAM_AUDIO_SUFFIX) or _snapshot_id_of_object(
        key, QUEUE_STREAM_MANIFEST_SUFFIX,
    )


def _valid_snapshot_id(snapshot_id: str) -> bool:
    return len(snapshot_id) == 32 and all(c in "0123456789abcdef" for c in snapshot_id)


def _escape_concat_path(path: Path) -> str:
    return str(path).replace("'", r"'\''")


LIBRARY_QUEUE_STREAM_SCAN_LIMIT = 1_000

# Library pool reads fail closed so an unavailable limiter cannot permit
# unbounded database and audio-file scans.
_QUEUE_STREAM_LIMITER_FAILURE_POLICY = LimiterFailurePolicy.FAIL_CLOSED


def _get_queue_stream_limiter(request: Request) -> RedisRateLimitBackend:
    def _build() -> RedisRateLimitBackend:
        ctx: AppContext = request.app.state.ctx
        return RedisRateLimitBackend(
            ctx.redis,
            REDIS_RL_QUEUE_STREAM_PREFIX,
        )

    return get_cached_limiter(request, "_queue_stream_limiter", _build)


def check_queue_stream_rate_limit(request: Request, user: AuthenticatedUser) -> None:
    try:
        enforce_rate_limit(
            _get_queue_stream_limiter(request),
            user.id,
            policy=_QUEUE_STREAM_LIMITER_FAILURE_POLICY,
            limit=_consts.QUEUE_STREAM_AUTH_RATE_LIMIT,
            window_seconds=_consts.QUEUE_STREAM_AUTH_RATE_WINDOW_SECONDS,
            unavailable_log_message="Queue stream rate limiter unavailable -- rejecting request",
        )
    except RateLimitRejected as rejected:
        raise Refusal(
            429, "libraryQueueRefusal.tooManyRequests",
            headers={"Retry-After": str(rejected.retry_after_seconds)},
        ) from rejected
    except RateLimiterUnavailable as unavailable:
        raise Refusal(503, "libraryQueueRefusal.limiterUnavailable") from unavailable


def generation_matches_pool(generation: Generation, pool: LibraryTakePool) -> bool:
    if generation.is_archived:
        return False
    if pool == "mix":
        return bool(generation.is_picked or generation.is_kept)
    if pool == "picks":
        return bool(generation.is_picked)
    return True


def _take_sort_key(generation: Generation) -> tuple[float, str]:
    created = generation.created_at
    timestamp = -created.timestamp() if created is not None else 0.0
    return (timestamp, generation.id)


def collect_library_pool_generations(
    songs: list[Song],
    pool: LibraryTakePool,
    start_gen: Generation | None,
) -> list[Generation]:
    selected: list[Generation] = []
    seen: set[str] = set()
    for song in songs:
        takes = [gen for gen in song.generations if generation_matches_pool(gen, pool)]
        takes.sort(key=_take_sort_key)
        for gen in takes:
            seen.add(gen.id)
            selected.append(gen)
    if start_gen is not None and start_gen.id not in seen and not start_gen.is_archived:
        selected.insert(0, start_gen)
    return selected


def _library_skip(ctx: AppContext, generation: Generation) -> QueueStreamSkipResponse | None:
    if not generation.mp3_path:
        return QueueStreamSkipResponse(
            song_id=generation.song_id,
            generation_id=generation.id,
            reason="missing_path",
        )
    try:
        audio_path = resolve_audio_path(ctx.audio_dir, generation.mp3_path)
    except (AudioPathRejectedError, OSError):
        return QueueStreamSkipResponse(
            song_id=generation.song_id,
            generation_id=generation.id,
            reason="missing_file",
        )
    try:
        with audio_path.open("rb") as audio_file:
            audio_file.read(1)
        probe_audio_duration(audio_path)
    except (HTTPException, OSError):
        return QueueStreamSkipResponse(
            song_id=generation.song_id,
            generation_id=generation.id,
            reason="unreadable_file",
        )
    return None


@dataclass
class LibraryPoolMembership:
    pool: LibraryTakePool
    sources: list[QueueStreamSource]
    skipped: list[QueueStreamSkipResponse]
    skipped_complete: bool


def shuffle_library_sources(
    sources: list[QueueStreamSource],
    start_generation_id: str | None,
    shuffle_seq: Callable[[list[QueueStreamSource]], None] | None = None,
) -> list[QueueStreamSource]:
    seen: set[str] = set()
    unique: list[QueueStreamSource] = []
    for source in sources:
        generation_id = source.generation.id
        if generation_id in seen:
            continue
        seen.add(generation_id)
        unique.append(source)
    mix = shuffle_seq if shuffle_seq is not None else random.shuffle
    if start_generation_id is None:
        mix(unique)
        return unique
    start = unique.pop(_source_position(unique, start_generation_id))
    mix(unique)
    return [start, *unique]


def resolve_library_pool_membership(
    session: Session,
    user: AuthenticatedUser,
    ctx: AppContext,
    *,
    pool: LibraryTakePool,
    start_generation_id: str | None,
    shuffle: bool,
) -> LibraryPoolMembership:
    songs = list_songs(
        session,
        user_id=user.id,
        light=True,
        with_generations=True,
        exclude_archived_albums=True,
    )
    songs = sorted(
        songs,
        key=lambda song: (
            song.album.title if song.album is not None else "",
            song.track_number,
            song.id,
        ),
    )

    start_gen: Generation | None = None
    if start_generation_id is not None:
        start_gen = check_generation_access(session, start_generation_id, user)
        if start_gen.is_archived:
            raise Refusal(422, "libraryQueueRefusal.startUnplayable")

    pool_generations = collect_library_pool_generations(songs, pool, start_gen)
    candidate_sources = _library_candidate_sources(pool_generations)
    canonical_rank = {source.generation.id: rank for rank, source in enumerate(candidate_sources)}
    candidate_sources = _order_library_candidates(candidate_sources, start_gen, shuffle)

    skipped, playable_sources, unscanned_tail = _scan_library_candidates(
        ctx, candidate_sources, start_gen,
    )
    if not playable_sources:
        _raise_empty_library_pool(pool, unscanned_tail)

    skipped.sort(key=lambda item: canonical_rank[item.generation_id])
    sources = [replace(source, index=index) for index, source in enumerate(playable_sources)]
    return LibraryPoolMembership(
        pool=pool,
        sources=sources,
        skipped=skipped,
        skipped_complete=not unscanned_tail,
    )


def _library_candidate_sources(pool_generations: list[Generation]) -> list[QueueStreamSource]:
    return [
        track_source_from_generation(
            gen,
            key=gen.id,
            index=index,
            entry_id=None,
            audio_url=f"/audio/{gen.mp3_path}",
        )
        for index, gen in enumerate(pool_generations)
    ]


def _order_library_candidates(
    sources: list[QueueStreamSource],
    start_gen: Generation | None,
    shuffle: bool,
) -> list[QueueStreamSource]:
    if shuffle:
        return shuffle_library_sources(sources, start_gen.id if start_gen is not None else None)
    if start_gen is None:
        return sources
    return _rotate_sources_to_start(sources, start_gen.id)


def _rotate_sources_to_start(
    sources: list[QueueStreamSource],
    start_generation_id: str,
) -> list[QueueStreamSource]:
    rotation_pos = _source_position(sources, start_generation_id)
    return sources[rotation_pos:] + sources[:rotation_pos]


def _source_position(sources: list[QueueStreamSource], generation_id: str) -> int:
    return [source.generation.id for source in sources].index(generation_id)


def _scan_library_candidates(
    ctx: AppContext,
    candidate_sources: list[QueueStreamSource],
    start_gen: Generation | None,
) -> tuple[list[QueueStreamSkipResponse], list[QueueStreamSource], bool]:
    skipped: list[QueueStreamSkipResponse] = []
    playable_sources: list[QueueStreamSource] = []
    scanned = 0
    playable_scan_limit = QUEUE_STREAM_MAX_TRACKS + 1
    for source in candidate_sources:
        if (
            scanned >= LIBRARY_QUEUE_STREAM_SCAN_LIMIT
            or len(playable_sources) >= playable_scan_limit
        ):
            break
        scanned += 1
        skip = _library_skip(ctx, source.generation)
        if skip is not None:
            if start_gen is not None and source.generation.id == start_gen.id:
                raise Refusal(422, "libraryQueueRefusal.startUnplayable")
            skipped.append(skip)
        else:
            playable_sources.append(source)
    return skipped, playable_sources, scanned < len(candidate_sources)


def _raise_empty_library_pool(pool: LibraryTakePool, unscanned_tail: bool) -> None:
    if unscanned_tail:
        raise Refusal(422, "libraryQueueRefusal.emptyWindow")
    raise Refusal(422, "libraryQueueRefusal.emptyPool", pool=pool)
