"""Build and serve cached continuous queue streams."""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import subprocess
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import HTTPException

from songmaker_cli.api_models.queue_streams import (
    QueueStreamManifestResponse,
    QueueStreamTrackResponse,
)
from songmaker_cli.app_context import AppContext
from songmaker_cli.db.models import Generation

log = logging.getLogger(__name__)

QUEUE_STREAM_DIRNAME = "queue-streams"
QUEUE_STREAM_TTL = timedelta(hours=8)
QUEUE_STREAM_ORPHAN_MAX_AGE = timedelta(hours=24)
QUEUE_STREAM_MAX_TRACKS = 200
QUEUE_STREAM_MAX_DURATION_SECONDS = 60 * 60 * 6
QUEUE_STREAM_MAX_CACHE_BYTES = 1024 * 1024 * 1024
QUEUE_STREAM_PINNED_MAX_BYTES = 4 * 1024 * 1024 * 1024  # 4 GiB server-wide cap for pinned snapshots
QUEUE_STREAM_PIN_MAX_AGE = timedelta(days=30)  # Abandoned pins expire after this age
FFMPEG_TIMEOUT_SECONDS = 600


class PinnedBytesExceededError(Exception):
    """Pinning this snapshot would exceed the server-wide pinned bytes cap."""

SnapshotScope = Literal["auth", "shared-playlist", "shared-album"]
_build_locks: dict[str, threading.Lock] = {}
_build_locks_guard = threading.Lock()
_pin_lock = threading.Lock()


def _load_manifest_json(manifest_path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _manifest_expiry(manifest: dict[str, Any]) -> datetime | None:
    raw = manifest.get("expires_at")
    if raw is None:
        return None
    try:
        return datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None


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


def build_queue_stream_snapshot(
    ctx: AppContext,
    sources: list[QueueStreamSource],
    *,
    scope: SnapshotScope,
    scope_id: str,
    stream_url: str,
) -> QueueStreamManifestResponse:
    if not sources:
        raise HTTPException(422, "Queue has no playable tracks")
    windowed_by_count = len(sources) > QUEUE_STREAM_MAX_TRACKS
    if windowed_by_count:
        sources = sources[:QUEUE_STREAM_MAX_TRACKS]

    stream_dir = _stream_dir(ctx)
    stream_dir.mkdir(parents=True, exist_ok=True)
    cleanup_expired_queue_streams(ctx)

    prepared_sources, windowed_by_duration = _prepare_sources(ctx, sources)
    if not prepared_sources:
        raise HTTPException(422, "Queue is too long for stream playback")
    content_hash = _content_hash(scope, scope_id, prepared_sources)
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
            windowed_by_duration=windowed_by_duration,
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
    windowed_by_duration: bool = False,
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
        song = gen.song
        album = song.album if song else None
        start = offset
        end = start + duration
        tracks.append(
            QueueStreamTrackResponse(
                key=source.key,
                index=source.index,
                entry_id=source.entry_id,
                generation_id=gen.id,
                song_id=song.id if song else "",
                song_title=song.title if song else "",
                artist=album.artist if album else "",
                generation_number=gen.generation_number,
                mp3_path=gen.mp3_path,
                audio_url=source.audio_url,
                seed=gen.seed,
                model_mode=gen.model_mode,
                duration=round(duration, 3),
                start_offset=round(start, 3),
                end_offset=round(end, 3),
            )
        )
        audio_paths.append(prepared.audio_path)
        offset = end

    if not tracks:
        raise HTTPException(422, "Queue is too long for stream playback")

    windowed = windowed_by_count or windowed_by_duration

    try:
        write_concat_file(concat_path, audio_paths)
        run_ffmpeg_concat(concat_path, output_tmp_path)
        output_tmp_path.replace(output_path)
    finally:
        concat_path.unlink(missing_ok=True)
        output_tmp_path.unlink(missing_ok=True)

    expires_at = datetime.now(timezone.utc) + QUEUE_STREAM_TTL
    manifest = {
        "snapshot_id": snapshot_id,
        "scope": scope,
        "scope_id": scope_id,
        "content_hash": content_hash,
        "expires_at": expires_at.isoformat(),
        "total_duration": round(offset, 3),
        "windowed": windowed,
        "pinned": False,
        "pinned_at": None,
        "tracks": [t.model_dump() for t in tracks],
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    _enforce_cache_quota(stream_dir, protected_snapshot_ids={snapshot_id})

    return QueueStreamManifestResponse(
        snapshot_id=snapshot_id,
        stream_url=stream_url,
        expires_at=manifest["expires_at"],
        total_duration=manifest["total_duration"],
        windowed=windowed,
        tracks=tracks,
    )


def _prepare_sources(
    ctx: AppContext,
    sources: list[QueueStreamSource],
) -> tuple[list[QueueStreamPreparedSource], bool]:
    """Probe sources one at a time, stopping before the track that would
    exceed the duration cap.

    Returns (prepared, windowed_by_duration). Sources beyond the window are never probed,
    so a corrupt track outside the window does not fail the build.
    """
    prepared: list[QueueStreamPreparedSource] = []
    offset = 0.0
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
        if offset + duration > QUEUE_STREAM_MAX_DURATION_SECONDS:
            return prepared, True
        prepared.append(
            QueueStreamPreparedSource(
                source=source,
                audio_path=audio_path,
                duration=duration,
                size=stat.st_size,
                mtime_ns=stat.st_mtime_ns,
            )
        )
        offset += duration
    return prepared, False


def _content_hash(
    scope: SnapshotScope,
    scope_id: str,
    prepared_sources: list[QueueStreamPreparedSource],
) -> str:
    hasher = hashlib.sha256()
    hasher.update(scope.encode("utf-8"))
    hasher.update(b"\0")
    hasher.update(scope_id.encode("utf-8"))
    for prepared in prepared_sources:
        source = prepared.source
        gen = source.generation
        parts = [
            str(source.index),
            source.key,
            source.entry_id or "",
            gen.id,
            gen.mp3_path or "",
            source.audio_url,
            str(prepared.size),
            str(prepared.mtime_ns),
            f"{prepared.duration:.3f}",
        ]
        hasher.update(b"\0")
        hasher.update("\x1f".join(parts).encode("utf-8"))
    return hasher.hexdigest()


def _build_lock(content_hash: str) -> threading.Lock:
    with _build_locks_guard:
        lock = _build_locks.get(content_hash)
        if lock is None:
            lock = threading.Lock()
            _build_locks[content_hash] = lock
        return lock


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
        stream_dir.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for manifest_path in manifests:
        manifest = _load_manifest_json(manifest_path)
        if manifest is None:
            continue
        expires_at = _manifest_expiry(manifest)
        if expires_at is None:
            continue
        if manifest.get("content_hash") != content_hash or expires_at < now:
            continue
        snapshot_id = str(manifest.get("snapshot_id") or manifest_path.stem)
        audio_path = queue_stream_audio_path(ctx, snapshot_id)
        if not audio_path.exists():
            continue
        return QueueStreamManifestResponse(
            snapshot_id=snapshot_id,
            stream_url=stream_url,
            expires_at=str(manifest["expires_at"]),
            total_duration=float(manifest["total_duration"]),
            windowed=bool(manifest.get("windowed", False)),
            tracks=[
                QueueStreamTrackResponse.model_validate(track)
                for track in manifest.get("tracks", [])
            ],
        )
    return None


def load_queue_stream_manifest(ctx: AppContext, snapshot_id: str) -> dict[str, Any]:
    if not _valid_snapshot_id(snapshot_id):
        raise HTTPException(404, "Queue stream not found")
    manifest_path = _stream_dir(ctx) / f"{snapshot_id}.json"
    if not manifest_path.exists():
        raise HTTPException(404, "Queue stream not found")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raise HTTPException(404, "Queue stream not found")

    expires_at = datetime.fromisoformat(str(manifest["expires_at"]))
    now = datetime.now(timezone.utc)
    if expires_at < now and not _is_active_pin(manifest, now):
        delete_snapshot_files(ctx, snapshot_id)
        raise HTTPException(404, "Queue stream expired")

    audio_path = queue_stream_audio_path(ctx, snapshot_id)
    if not audio_path.exists():
        raise HTTPException(404, "Queue stream audio not found")
    return manifest


def queue_stream_audio_path(ctx: AppContext, snapshot_id: str) -> Path:
    if not _valid_snapshot_id(snapshot_id):
        raise HTTPException(404, "Queue stream not found")
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
    live_snapshot_ids: set[str] = set()
    for manifest_path in stream_dir.glob("*.json"):
        snapshot_id = manifest_path.stem
        manifest = _load_manifest_json(manifest_path)
        expires_at = _manifest_expiry(manifest) if manifest is not None else None
        if expires_at is not None and expires_at >= now:
            live_snapshot_ids.add(snapshot_id)
        elif manifest is not None and _is_active_pin(manifest, now):
            # Pinned and not abandoned — exempt from TTL sweep
            live_snapshot_ids.add(snapshot_id)
        else:
            delete_snapshot_files(ctx, snapshot_id)

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

    _enforce_cache_quota(stream_dir)


def delete_snapshot_files(ctx: AppContext, snapshot_id: str) -> None:
    if not _valid_snapshot_id(snapshot_id):
        return
    root = _stream_dir(ctx)
    for suffix in (".json", ".mp3", ".tmp.mp3", ".concat.txt"):
        (root / f"{snapshot_id}{suffix}").unlink(missing_ok=True)


def resolve_audio_path(audio_dir: Path, rel_path: str) -> Path:
    audio_root = audio_dir.resolve()
    audio_path = (audio_root / rel_path).resolve()
    if not audio_path.is_relative_to(audio_root):
        raise HTTPException(403, "Path traversal denied")
    if not audio_path.exists():
        raise HTTPException(404, "Audio file not found")
    return audio_path


def probe_audio_duration(audio_path: Path) -> float:
    try:
        from mutagen import File as MutagenFile

        audio = MutagenFile(audio_path)
        duration = float(getattr(getattr(audio, "info", None), "length", 0) or 0)
    except Exception as exc:
        raise HTTPException(422, "Could not read audio duration") from exc
    if duration <= 0:
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


def _stream_dir(ctx: AppContext) -> Path:
    return ctx.data_dir / QUEUE_STREAM_DIRNAME


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
    for suffix in (".json", ".mp3", ".tmp.mp3", ".concat.txt"):
        (stream_dir / f"{snapshot_id}{suffix}").unlink(missing_ok=True)


def _snapshot_id_from_cache_file(path: Path) -> str | None:
    for suffix in (".tmp.mp3", ".concat.txt", ".json.tmp", ".json", ".mp3"):
        if not path.name.endswith(suffix):
            continue
        snapshot_id = path.name[: -len(suffix)]
        return snapshot_id if _valid_snapshot_id(snapshot_id) else None
    return None


def _valid_snapshot_id(snapshot_id: str) -> bool:
    return len(snapshot_id) == 32 and all(c in "0123456789abcdef" for c in snapshot_id)


def _escape_concat_path(path: Path) -> str:
    return str(path).replace("'", r"'\''")


def _is_active_pin(manifest: dict[str, Any], now: datetime) -> bool:
    """Return True when the manifest is pinned and the pin has not been abandoned."""
    if not manifest.get("pinned", False):
        return False
    pinned_at_str = manifest.get("pinned_at")
    if not pinned_at_str:
        return False
    try:
        pinned_at = datetime.fromisoformat(str(pinned_at_str))
        return pinned_at >= now - QUEUE_STREAM_PIN_MAX_AGE
    except (ValueError, TypeError):
        return False


def _pinned_snapshot_ids(stream_dir: Path, now: datetime) -> set[str]:
    """Return the IDs of all snapshots that are currently pinned and not abandoned."""
    pinned: set[str] = set()
    for manifest_path in stream_dir.glob("*.json"):
        manifest = _load_manifest_json(manifest_path)
        if manifest is None:
            continue
        if _is_active_pin(manifest, now):
            pinned.add(manifest_path.stem)
    return pinned


def _sum_pinned_bytes(stream_dir: Path, now: datetime) -> int:
    """Sum the audio bytes of all currently pinned, non-abandoned snapshots."""
    total = 0
    for manifest_path in stream_dir.glob("*.json"):
        manifest = _load_manifest_json(manifest_path)
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


def _atomic_write_manifest(stream_dir: Path, snapshot_id: str, manifest: dict[str, Any]) -> None:
    """Write manifest atomically via a temp file, then rename into place."""
    manifest_path = stream_dir / f"{snapshot_id}.json"
    tmp_path = stream_dir / f"{snapshot_id}.json.tmp"
    try:
        tmp_path.write_text(json.dumps(manifest), encoding="utf-8")
        tmp_path.replace(manifest_path)
    finally:
        tmp_path.unlink(missing_ok=True)


def pin_snapshot(ctx: AppContext, snapshot_id: str) -> dict[str, Any]:
    """Pin a snapshot, exempting it from TTL expiry and quota eviction.

    Raises PinnedBytesExceededError when the pinned-bytes cap would be exceeded.
    Idempotent: returns the current manifest state when already pinned.
    """
    if not _valid_snapshot_id(snapshot_id):
        raise HTTPException(404, "Queue stream not found")
    stream_dir = _stream_dir(ctx)
    manifest_path = stream_dir / f"{snapshot_id}.json"
    if not manifest_path.exists():
        raise HTTPException(404, "Queue stream not found")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raise HTTPException(404, "Queue stream not found")

    if manifest.get("pinned", False):
        return manifest  # Already pinned — idempotent fast-path (no lock needed)

    with _pin_lock:
        # Re-read under the lock: another thread may have pinned between the check above and here
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            raise HTTPException(404, "Queue stream not found")

        if manifest.get("pinned", False):
            return manifest  # Already pinned — idempotent

        audio_path = stream_dir / f"{snapshot_id}.mp3"
        if not audio_path.exists():
            raise HTTPException(404, "Queue stream audio not found")
        try:
            new_bytes = audio_path.stat().st_size
        except OSError as exc:
            raise HTTPException(404, "Queue stream audio not found") from exc

        now = datetime.now(timezone.utc)
        if _sum_pinned_bytes(stream_dir, now) + new_bytes > QUEUE_STREAM_PINNED_MAX_BYTES:
            raise PinnedBytesExceededError()

        manifest["pinned"] = True
        manifest["pinned_at"] = now.isoformat()
        _atomic_write_manifest(stream_dir, snapshot_id, manifest)
    return manifest


def unpin_snapshot(ctx: AppContext, snapshot_id: str) -> dict[str, Any]:
    """Remove a pin from a snapshot.

    Idempotent: has no effect when the snapshot is already unpinned.
    """
    if not _valid_snapshot_id(snapshot_id):
        raise HTTPException(404, "Queue stream not found")
    stream_dir = _stream_dir(ctx)
    manifest_path = stream_dir / f"{snapshot_id}.json"
    if not manifest_path.exists():
        raise HTTPException(404, "Queue stream not found")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raise HTTPException(404, "Queue stream not found")

    manifest["pinned"] = False
    manifest["pinned_at"] = None
    _atomic_write_manifest(stream_dir, snapshot_id, manifest)
    return manifest
