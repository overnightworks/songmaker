"""Build and serve cached continuous queue streams.

This module owns queue-stream duration and ffmpeg timeout limits. A host
measurement on 2026-09-03 concatenated 900.049 seconds of synthetic MP3 audio
in 5.394 seconds (166.8 audio seconds per wall second). The 100x minimum rate
and 120-second reserve keep the six-hour product cap within a measured,
conservative ffmpeg budget.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import shutil
import subprocess
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
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
from songmaker_cli.audio_paths import AudioPathRejectedError, resolve_audio_path
from songmaker_cli.constants import REDIS_RL_QUEUE_STREAM_PREFIX, LimiterFailurePolicy
from songmaker_cli.db.models import Generation, Song
from songmaker_cli.db.queries.songs import list_songs

log = logging.getLogger(__name__)

QUEUE_STREAM_DIRNAME = "queue-streams"
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
QUEUE_STREAM_MANIFEST_GLOB: Final = "*.json"
QUEUE_STREAM_MANIFEST_SUFFIX: Final = ".json"
QUEUE_STREAM_TEMP_AUDIO_SUFFIX: Final = ".tmp.mp3"
QUEUE_STREAM_CONCAT_SUFFIX: Final = ".concat.txt"
QUEUE_STREAM_NOT_FOUND_DETAIL: Final = "Queue stream not found"
QUEUE_STREAM_AUDIO_NOT_FOUND_DETAIL: Final = "Queue stream audio not found"


SnapshotScope = Literal["auth", "shared-playlist", "shared-album"]


@dataclass
class _BuildLockEntry:
    lock: threading.Lock = field(default_factory=threading.Lock)
    waiters: int = 0


_build_locks: dict[str, _BuildLockEntry] = {}
_build_locks_guard = threading.Lock()


class QueueStreamManifest(BaseModel):
    """The on-disk record for one queue-stream snapshot.

    ``load``/``save`` are the only (de)serializers for the manifest file --
    every read or write of a snapshot's ``.json`` file goes through this
    model, so a truncated or field-missing file fails validation once, in
    one place, instead of raising a raw ``KeyError`` deep in a caller.
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
    def load(cls, manifest_path: Path) -> QueueStreamManifest | None:
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            log.warning("Queue stream manifest %s unreadable: %s", manifest_path, exc)
            return None
        try:
            return cls.model_validate(payload)
        except ValidationError as exc:
            log.warning("Queue stream manifest %s failed validation: %s", manifest_path, exc)
            return None

    def save(self, manifest_path: Path) -> None:
        """Write the manifest atomically via a temp file, then rename into place."""
        tmp_path = manifest_path.with_name(f"{manifest_path.name}.tmp")
        try:
            tmp_path.write_text(self.model_dump_json(), encoding="utf-8")
            tmp_path.replace(manifest_path)
        finally:
            tmp_path.unlink(missing_ok=True)


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
        song = gen.song
        if song is not None:
            _ = song.album
        _ = gen.version


def build_queue_stream_snapshot(
    ctx: AppContext,
    sources: list[QueueStreamSource],
    *,
    scope: SnapshotScope,
    scope_id: str,
    stream_url: str,
    force_windowed: bool = False,
    admission: QueueStreamAdmission | None = None,
) -> QueueStreamManifestResponse:
    admission = admission or prepare_queue_stream_admission(ctx, sources)
    windowed_by_count = force_windowed or admission.windowed_by_count

    stream_dir = _stream_dir(ctx)
    stream_dir.mkdir(parents=True, exist_ok=True)

    prepared_sources = admission.prepared_sources
    windowed = windowed_by_count
    content_hash = _content_hash(scope, scope_id, prepared_sources, windowed=windowed)
    with _build_lock(content_hash):
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
    stream_dir = _stream_dir(ctx)
    snapshot_id = uuid.uuid4().hex
    output_path = stream_dir / f"{snapshot_id}.mp3"
    output_tmp_path = stream_dir / f"{snapshot_id}.tmp.mp3"
    concat_path = stream_dir / f"{snapshot_id}.concat.txt"
    manifest_path = stream_dir / f"{snapshot_id}.json"

    audio_paths: list[Path] = []
    tracks: list[QueueStreamTrackResponse] = []
    offset = 0.0

    for prepared in prepared_sources:
        source = prepared.source
        gen = source.generation
        duration = prepared.duration
        start = offset
        end = start + duration
        tracks.append(_track_response(source, gen, duration, start, end))
        audio_paths.append(prepared.audio_path)
        offset = end

    windowed = windowed_by_count

    try:
        write_concat_file(concat_path, audio_paths)
        run_ffmpeg_concat(concat_path, output_tmp_path)
        output_tmp_path.replace(output_path)
    finally:
        concat_path.unlink(missing_ok=True)
        output_tmp_path.unlink(missing_ok=True)

    expires_at = datetime.now(timezone.utc) + QUEUE_STREAM_TTL
    manifest = QueueStreamManifest(
        snapshot_id=snapshot_id,
        scope=scope,
        scope_id=scope_id,
        content_hash=content_hash,
        expires_at=expires_at,
        total_duration=round(offset, 3),
        windowed=windowed,
        tracks=tracks,
    )
    manifest.save(manifest_path)
    _enforce_cache_quota(stream_dir, protected_snapshot_ids={snapshot_id})

    return QueueStreamManifestResponse(
        snapshot_id=snapshot_id,
        stream_url=stream_url,
        expires_at=manifest.expires_at.isoformat(),
        total_duration=manifest.total_duration,
        windowed=windowed,
        tracks=tracks,
    )


def prepare_queue_stream_admission(
    ctx: AppContext,
    sources: list[QueueStreamSource],
) -> QueueStreamAdmission:
    if not sources:
        raise HTTPException(422, "Queue has no playable tracks")
    windowed_by_count = len(sources) > QUEUE_STREAM_MAX_TRACKS
    sources = sources[:QUEUE_STREAM_MAX_TRACKS]
    prepared: list[QueueStreamPreparedSource] = []
    total_duration = 0.0
    for source in sources:
        gen = source.generation
        if not gen.mp3_path:
            raise HTTPException(422, "Queue contains a generation without audio")
        audio_path = resolve_audio_path(ctx.audio_dir, gen.mp3_path)
        try:
            stat = audio_path.stat()
        except OSError as exc:
            raise HTTPException(404, "Audio file not found") from exc
        duration = probe_audio_duration(audio_path)
        total_duration += duration
        if total_duration > QUEUE_STREAM_MAX_DURATION_SECONDS:
            raise HTTPException(422, QUEUE_STREAM_DURATION_LIMIT_DETAIL)
        prepared.append(
            QueueStreamPreparedSource(
                source=source,
                audio_path=audio_path,
                duration=duration,
                size=stat.st_size,
                mtime_ns=stat.st_mtime_ns,
            )
        )
    if not queue_stream_duration_fits_ffmpeg_timeout(total_duration):
        raise RuntimeError("Queue stream duration exceeds the ffmpeg timeout budget")
    return QueueStreamAdmission(
        prepared_sources=prepared,
        windowed_by_count=windowed_by_count,
    )


def queue_stream_duration_fits_ffmpeg_timeout(duration_seconds: float) -> bool:
    return queue_stream_ffmpeg_timeout_seconds(duration_seconds) <= FFMPEG_TIMEOUT_SECONDS


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


@contextmanager
def _build_lock(content_hash: str) -> Iterator[None]:
    """Serialize concurrent builds that share a content hash.

    Entries are reference-counted and removed once no caller still
    references them, so ``_build_locks`` does not grow without bound over
    the server's lifetime. The removal is race-free: a waiter always
    registers itself (incrementing ``waiters`` under the guard) before it
    can block on the lock, so a builder can only delete the entry once no
    other thread still holds a reference to it.
    """
    with _build_locks_guard:
        entry = _build_locks.setdefault(content_hash, _BuildLockEntry())
        entry.waiters += 1
    entry.lock.acquire()
    try:
        yield
    finally:
        entry.lock.release()
        with _build_locks_guard:
            entry.waiters -= 1
            if entry.waiters == 0 and _build_locks.get(content_hash) is entry:
                del _build_locks[content_hash]


def _find_reusable_snapshot(
    ctx: AppContext,
    content_hash: str,
    stream_url: str,
) -> QueueStreamManifestResponse | None:
    stream_dir = _stream_dir(ctx)
    if not stream_dir.exists():
        return None
    now = datetime.now(timezone.utc)
    manifests = sorted(
        stream_dir.glob(QUEUE_STREAM_MANIFEST_GLOB),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for manifest_path in manifests:
        manifest = QueueStreamManifest.load(manifest_path)
        if manifest is None:
            continue
        if manifest.content_hash != content_hash or manifest.expires_at < now:
            continue
        audio_path = queue_stream_audio_path(ctx, manifest.snapshot_id)
        if not audio_path.exists():
            continue
        return QueueStreamManifestResponse(
            snapshot_id=manifest.snapshot_id,
            stream_url=stream_url,
            expires_at=manifest.expires_at.isoformat(),
            total_duration=manifest.total_duration,
            windowed=manifest.windowed,
            tracks=manifest.tracks,
        )
    return None


def load_queue_stream_manifest(ctx: AppContext, snapshot_id: str) -> QueueStreamManifest:
    if not _valid_snapshot_id(snapshot_id):
        raise HTTPException(404, QUEUE_STREAM_NOT_FOUND_DETAIL)
    manifest_path = _stream_dir(ctx) / f"{snapshot_id}.json"
    if not manifest_path.exists():
        raise HTTPException(404, QUEUE_STREAM_NOT_FOUND_DETAIL)
    manifest = QueueStreamManifest.load(manifest_path)
    if manifest is None:
        raise HTTPException(404, QUEUE_STREAM_NOT_FOUND_DETAIL)

    now = datetime.now(timezone.utc)
    if manifest.expires_at < now:
        delete_snapshot_files(ctx, snapshot_id)
        raise HTTPException(404, "Queue stream expired")

    audio_path = queue_stream_audio_path(ctx, snapshot_id)
    if not audio_path.exists():
        raise HTTPException(404, QUEUE_STREAM_AUDIO_NOT_FOUND_DETAIL)
    return manifest


def queue_stream_audio_path(ctx: AppContext, snapshot_id: str) -> Path:
    if not _valid_snapshot_id(snapshot_id):
        raise HTTPException(404, QUEUE_STREAM_NOT_FOUND_DETAIL)
    path = (_stream_dir(ctx) / f"{snapshot_id}.mp3").resolve()
    root = _stream_dir(ctx).resolve()
    if not path.is_relative_to(root):
        raise HTTPException(403, "Path traversal denied")
    return path


def cleanup_expired_queue_streams(ctx: AppContext) -> None:
    stream_dir = _stream_dir(ctx)
    if not stream_dir.exists():
        return
    now = datetime.now(timezone.utc)
    live_snapshot_ids = _remove_expired_queue_stream_snapshots(ctx, stream_dir, now)
    _remove_expired_queue_stream_orphans(stream_dir, live_snapshot_ids, now)
    _enforce_cache_quota(stream_dir)


def _remove_expired_queue_stream_snapshots(
    ctx: AppContext,
    stream_dir: Path,
    now: datetime,
) -> set[str]:
    live_snapshot_ids: set[str] = set()
    for manifest_path in stream_dir.glob(QUEUE_STREAM_MANIFEST_GLOB):
        snapshot_id = manifest_path.stem
        manifest = QueueStreamManifest.load(manifest_path)
        if manifest is not None and manifest.expires_at >= now:
            live_snapshot_ids.add(snapshot_id)
            continue
        delete_snapshot_files(ctx, snapshot_id)
    return live_snapshot_ids


def _remove_expired_queue_stream_orphans(
    stream_dir: Path,
    live_snapshot_ids: set[str],
    now: datetime,
) -> None:
    orphan_cutoff = now - QUEUE_STREAM_ORPHAN_MAX_AGE
    for cache_file in stream_dir.iterdir():
        if not cache_file.is_file():
            continue
        snapshot_id = _snapshot_id_from_cache_file(cache_file)
        if not snapshot_id or snapshot_id in live_snapshot_ids:
            continue
        try:
            modified_at = datetime.fromtimestamp(cache_file.stat().st_mtime, tz=timezone.utc)
        except OSError:
            modified_at = None
        if modified_at is not None and modified_at < orphan_cutoff:
            cache_file.unlink(missing_ok=True)


def delete_snapshot_files(ctx: AppContext, snapshot_id: str) -> None:
    if not _valid_snapshot_id(snapshot_id):
        return
    root = _stream_dir(ctx)
    for suffix in (
        QUEUE_STREAM_MANIFEST_SUFFIX,
        ".mp3",
        QUEUE_STREAM_TEMP_AUDIO_SUFFIX,
        QUEUE_STREAM_CONCAT_SUFFIX,
    ):
        (root / f"{snapshot_id}{suffix}").unlink(missing_ok=True)


def probe_audio_duration(audio_path: Path) -> float:
    """Request-boundary wrapper: an unreadable file is a 422, not a None."""
    duration = audio_files.read_audio_duration(audio_path)
    if duration is None:
        raise HTTPException(422, "Could not read audio duration")
    return duration


def write_concat_file(concat_path: Path, audio_paths: list[Path]) -> None:
    lines = [f"file '{_escape_concat_path(path)}'" for path in audio_paths]
    concat_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_ffmpeg_concat(concat_path: Path, output_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise HTTPException(503, "ffmpeg is not available")

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
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            timeout=FFMPEG_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise HTTPException(503, "ffmpeg is not available") from exc
    except subprocess.TimeoutExpired as exc:
        output_path.unlink(missing_ok=True)
        raise HTTPException(504, "Queue stream build timed out") from exc
    except subprocess.CalledProcessError as exc:
        output_path.unlink(missing_ok=True)
        detail = (exc.stderr or exc.stdout or "").strip()
        log.warning("ffmpeg queue stream build failed: %s", detail)
        raise HTTPException(422, "Could not build queue stream") from exc


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


def _stream_dir(ctx: AppContext) -> Path:
    return ctx.data_dir / QUEUE_STREAM_DIRNAME


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
    stream_dir: Path,
    *,
    protected_snapshot_ids: set[str] | None = None,
) -> None:
    # Just-built snapshots (protected_snapshot_ids) are counted but never evicted.
    eviction_protected = protected_snapshot_ids or set()

    mp3_files = [path for path in stream_dir.glob("*.mp3") if path.is_file()]
    total_bytes = 0
    sized_files: list[tuple[float, int, Path]] = []
    for path in mp3_files:
        try:
            stat = path.stat()
        except OSError:
            continue
        total_bytes += stat.st_size
        sized_files.append((stat.st_mtime, stat.st_size, path))

    if total_bytes <= QUEUE_STREAM_MAX_CACHE_BYTES:
        return

    for _, size, path in sorted(sized_files):
        if total_bytes <= QUEUE_STREAM_MAX_CACHE_BYTES:
            break
        snapshot_id = _snapshot_id_from_cache_file(path)
        if snapshot_id in eviction_protected:
            continue
        if snapshot_id:
            delete_snapshot_files_from_dir(stream_dir, snapshot_id)
        else:
            path.unlink(missing_ok=True)
        total_bytes -= size


def delete_snapshot_files_from_dir(stream_dir: Path, snapshot_id: str) -> None:
    if not _valid_snapshot_id(snapshot_id):
        return
    for suffix in (
        QUEUE_STREAM_MANIFEST_SUFFIX,
        ".mp3",
        QUEUE_STREAM_TEMP_AUDIO_SUFFIX,
        QUEUE_STREAM_CONCAT_SUFFIX,
    ):
        (stream_dir / f"{snapshot_id}{suffix}").unlink(missing_ok=True)


def _snapshot_id_from_cache_file(path: Path) -> str | None:
    for suffix in (
        QUEUE_STREAM_TEMP_AUDIO_SUFFIX,
        QUEUE_STREAM_CONCAT_SUFFIX,
        ".json.tmp",
        QUEUE_STREAM_MANIFEST_SUFFIX,
        ".mp3",
    ):
        if not path.name.endswith(suffix):
            continue
        snapshot_id = path.name[: -len(suffix)]
        return snapshot_id if _valid_snapshot_id(snapshot_id) else None
    return None


def _valid_snapshot_id(snapshot_id: str) -> bool:
    return len(snapshot_id) == 32 and all(c in "0123456789abcdef" for c in snapshot_id)


def _escape_concat_path(path: Path) -> str:
    return str(path).replace("'", r"'\''")


LIBRARY_QUEUE_STREAM_SCAN_LIMIT = 1_000

# Authenticated queue-stream creation fails closed: an unenforced limit here
# could let one user exhaust storage or worker capacity unbounded.
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
    enforce_rate_limit(
        _get_queue_stream_limiter(request),
        user.id,
        policy=_QUEUE_STREAM_LIMITER_FAILURE_POLICY,
        reject_detail="Too many queue stream requests",
        limit=_consts.QUEUE_STREAM_AUTH_RATE_LIMIT,
        window_seconds=_consts.QUEUE_STREAM_AUTH_RATE_WINDOW_SECONDS,
        unavailable_log_message="Queue stream rate limiter unavailable -- rejecting request",
        unavailable_detail="Queue stream rate limiter unavailable",
    )


def generation_matches_pool(generation: Generation, pool: LibraryTakePool) -> bool:
    if generation.is_archived:
        return False
    if pool == "mix":
        return bool(generation.is_picked or generation.is_kept)
    if pool == "picks":
        return bool(generation.is_picked)
    if pool == "keeps":
        return bool(generation.is_kept)
    if pool == "all":
        return True
    raise ValueError(f"Unknown library take pool: {pool}")


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
            if gen.id in seen:
                continue
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
        if not audio_path.exists():
            return QueueStreamSkipResponse(
                song_id=generation.song_id,
                generation_id=generation.id,
                reason="missing_file",
            )
    except (AudioPathRejectedError, OSError):
        return QueueStreamSkipResponse(
            song_id=generation.song_id,
            generation_id=generation.id,
            reason="missing_file",
        )
    try:
        if not audio_path.is_file():
            return QueueStreamSkipResponse(
                song_id=generation.song_id,
                generation_id=generation.id,
                reason="unreadable_file",
            )
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
    if len(sources) <= 1:
        return list(sources)
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
    start: QueueStreamSource | None = None
    rest: list[QueueStreamSource] = []
    for item in unique:
        if start is None and item.generation.id == start_generation_id:
            start = item
        else:
            rest.append(item)
    mix(rest)
    if start is None:
        return rest
    return [start, *rest]


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
            raise HTTPException(422, _consts.QUEUE_STREAM_UNPLAYABLE_START_DETAIL)

    pool_generations = collect_library_pool_generations(
        songs,
        pool,
        start_gen,
    )
    candidate_sources = _library_candidate_sources(pool_generations)
    canonical_rank = {source.generation.id: rank for rank, source in enumerate(candidate_sources)}
    candidate_sources = _order_library_candidates(
        candidate_sources,
        start_gen,
        shuffle,
    )

    skipped, playable_sources, unscanned_tail = _scan_library_candidates(
        ctx,
        candidate_sources,
        start_gen,
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
    rotation_pos = next(
        (
            index
            for index, source in enumerate(sources)
            if source.generation.id == start_generation_id
        ),
        None,
    )
    if rotation_pos is None:
        return sources
    return sources[rotation_pos:] + sources[:rotation_pos]


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
                raise HTTPException(422, _consts.QUEUE_STREAM_UNPLAYABLE_START_DETAIL)
            skipped.append(skip)
        else:
            playable_sources.append(source)
    return skipped, playable_sources, scanned < len(candidate_sources)


def _raise_empty_library_pool(pool: LibraryTakePool, unscanned_tail: bool) -> None:
    if unscanned_tail:
        raise HTTPException(422, "No playable takes in scanned library window")
    raise HTTPException(422, f"{_consts.QUEUE_STREAM_EMPTY_POOL_DETAIL} '{pool}'")
