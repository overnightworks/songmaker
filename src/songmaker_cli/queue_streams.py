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
import shutil
import subprocess
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from math import ceil
from pathlib import Path
from typing import Final, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ValidationError

from songmaker_cli.api_models.queue_streams import (
    QueueStreamManifestResponse,
    QueueStreamTrackResponse,
)
from songmaker_cli.api_models.songs import generation_version_lyrics
from songmaker_cli.app_context import AppContext
from songmaker_cli.audio_paths import resolve_audio_path
from songmaker_cli.db.models import Generation

log = logging.getLogger(__name__)

QUEUE_STREAM_DIRNAME = "queue-streams"
QUEUE_STREAM_TTL = timedelta(hours=8)
QUEUE_STREAM_ORPHAN_MAX_AGE = timedelta(hours=24)
QUEUE_STREAM_MAX_TRACKS = 200
QUEUE_STREAM_FFMPEG_MEASURED_AUDIO_SECONDS_PER_WALL_SECOND = 166.8
QUEUE_STREAM_FFMPEG_MIN_AUDIO_SECONDS_PER_WALL_SECOND = 100
QUEUE_STREAM_FFMPEG_TIMEOUT_RESERVE_SECONDS = 120
QUEUE_STREAM_MAX_DURATION_SECONDS = 60 * 60 * 6
QUEUE_STREAM_MAX_CACHE_BYTES = 1024 * 1024 * 1024
QUEUE_STREAM_PINNED_MAX_BYTES = 4 * 1024 * 1024 * 1024  # 4 GiB server-wide cap for pinned snapshots
QUEUE_STREAM_PIN_MAX_AGE = timedelta(days=30)  # Abandoned pins expire after this age


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


class PinnedBytesExceededError(Exception):
    """Pinning this snapshot would exceed the server-wide pinned bytes cap."""


SnapshotScope = Literal["auth", "shared-playlist", "shared-album"]


@dataclass
class _BuildLockEntry:
    lock: threading.Lock = field(default_factory=threading.Lock)
    waiters: int = 0


_build_locks: dict[str, _BuildLockEntry] = {}
_build_locks_guard = threading.Lock()
_pin_lock = threading.Lock()


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
    pinned: bool = False
    pinned_at: datetime | None = None

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
        pinned=False,
        pinned_at=None,
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
    if manifest.expires_at < now and not _is_active_pin(manifest, now):
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
        if manifest is not None and (manifest.expires_at >= now or _is_active_pin(manifest, now)):
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


def read_audio_duration(audio_path: Path) -> float | None:
    """Read a file's real length in seconds, or None if it can't be read.

    Pure: no HTTP dependency, no request-boundary shape. Safe to call from
    any layer, including a background job or the DB query layer.
    """
    try:
        from mutagen import File as MutagenFile

        audio = MutagenFile(audio_path)
        if audio is None:
            return None
        length = float(audio.info.length)
    except Exception:
        return None
    return length if length > 0 else None


def probe_audio_duration(audio_path: Path) -> float:
    """Request-boundary wrapper: an unreadable file is a 422, not a None."""
    duration = read_audio_duration(audio_path)
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
        update={"tracks": [track.model_copy(update={"lyrics": None}) for track in snapshot.tracks]}
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
    now = datetime.now(timezone.utc)
    pinned_ids = _pinned_snapshot_ids(stream_dir, now)
    # Pinned snapshots are excluded from quota accounting and eviction entirely.
    # Just-built snapshots (protected_snapshot_ids) are counted but never evicted.
    eviction_protected = (protected_snapshot_ids or set()) | pinned_ids

    mp3_files = [path for path in stream_dir.glob("*.mp3") if path.is_file()]
    total_bytes = 0
    sized_files: list[tuple[float, int, Path]] = []
    for path in mp3_files:
        snapshot_id = _snapshot_id_from_cache_file(path)
        if snapshot_id in pinned_ids:
            continue  # Pinned bytes do not count toward the general quota
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


def _is_active_pin(manifest: QueueStreamManifest, now: datetime) -> bool:
    """Return True when the manifest is pinned and the pin has not been abandoned."""
    if not manifest.pinned or manifest.pinned_at is None:
        return False
    return manifest.pinned_at >= now - QUEUE_STREAM_PIN_MAX_AGE


def _pinned_snapshot_ids(stream_dir: Path, now: datetime) -> set[str]:
    """Return the IDs of all snapshots that are currently pinned and not abandoned."""
    pinned: set[str] = set()
    for manifest_path in stream_dir.glob(QUEUE_STREAM_MANIFEST_GLOB):
        manifest = QueueStreamManifest.load(manifest_path)
        if manifest is None:
            continue
        if _is_active_pin(manifest, now):
            pinned.add(manifest_path.stem)
    return pinned


def _sum_pinned_bytes(stream_dir: Path, now: datetime) -> int:
    """Sum the audio bytes of all currently pinned, non-abandoned snapshots."""
    total = 0
    for manifest_path in stream_dir.glob(QUEUE_STREAM_MANIFEST_GLOB):
        manifest = QueueStreamManifest.load(manifest_path)
        if manifest is None:
            continue
        if not _is_active_pin(manifest, now):
            continue
        audio_path = stream_dir / f"{manifest_path.stem}.mp3"
        try:
            total += audio_path.stat().st_size
        except OSError:
            pass
    return total


def pin_snapshot(ctx: AppContext, snapshot_id: str) -> QueueStreamManifest:
    """Pin a snapshot, exempting it from TTL expiry and quota eviction.

    Raises PinnedBytesExceededError when the pinned-bytes cap would be exceeded.
    Idempotent: returns the current manifest state when already pinned.
    """
    if not _valid_snapshot_id(snapshot_id):
        raise HTTPException(404, QUEUE_STREAM_NOT_FOUND_DETAIL)
    stream_dir = _stream_dir(ctx)
    manifest_path = stream_dir / f"{snapshot_id}.json"
    if not manifest_path.exists():
        raise HTTPException(404, QUEUE_STREAM_NOT_FOUND_DETAIL)
    manifest = QueueStreamManifest.load(manifest_path)
    if manifest is None:
        raise HTTPException(404, QUEUE_STREAM_NOT_FOUND_DETAIL)

    if manifest.pinned:
        return manifest  # Already pinned — idempotent fast-path (no lock needed)

    with _pin_lock:
        # Re-read under the lock: another thread may have pinned between the check above and here
        manifest = QueueStreamManifest.load(manifest_path)
        if manifest is None:
            raise HTTPException(404, QUEUE_STREAM_NOT_FOUND_DETAIL)

        if manifest.pinned:
            return manifest  # Already pinned — idempotent

        audio_path = stream_dir / f"{snapshot_id}.mp3"
        if not audio_path.exists():
            raise HTTPException(404, QUEUE_STREAM_AUDIO_NOT_FOUND_DETAIL)
        try:
            new_bytes = audio_path.stat().st_size
        except OSError as exc:
            raise HTTPException(404, QUEUE_STREAM_AUDIO_NOT_FOUND_DETAIL) from exc

        now = datetime.now(timezone.utc)
        if _sum_pinned_bytes(stream_dir, now) + new_bytes > QUEUE_STREAM_PINNED_MAX_BYTES:
            raise PinnedBytesExceededError()

        manifest = manifest.model_copy(update={"pinned": True, "pinned_at": now})
        manifest.save(manifest_path)
    return manifest


def unpin_snapshot(ctx: AppContext, snapshot_id: str) -> QueueStreamManifest:
    """Remove a pin from a snapshot.

    Idempotent: has no effect when the snapshot is already unpinned.
    """
    if not _valid_snapshot_id(snapshot_id):
        raise HTTPException(404, QUEUE_STREAM_NOT_FOUND_DETAIL)
    stream_dir = _stream_dir(ctx)
    manifest_path = stream_dir / f"{snapshot_id}.json"
    if not manifest_path.exists():
        raise HTTPException(404, QUEUE_STREAM_NOT_FOUND_DETAIL)
    manifest = QueueStreamManifest.load(manifest_path)
    if manifest is None:
        raise HTTPException(404, QUEUE_STREAM_NOT_FOUND_DETAIL)

    manifest = manifest.model_copy(update={"pinned": False, "pinned_at": None})
    manifest.save(manifest_path)
    return manifest
