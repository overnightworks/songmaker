# Migration: Local Filesystem → Object Storage

> **Status: NOT STARTED** — only needed when API and worker run on different machines.
> **Depends on: Celery migration (worker is a separate process)**

## Problem

Audio files (MP3, WAV) are stored on local disk at `output_dir / album / filename`. The API server serves them via `FileResponse`. If the API and GPU worker are on different machines, the worker writes files that the API can't read. Even on one machine, Docker containers need shared volumes.

## Goal

Abstract file storage behind an interface that supports both local disk (current) and S3-compatible object storage (MinIO for self-hosted, S3/R2 for cloud).

## Scope

This is the lowest-priority migration. For single-machine Docker Compose, a shared volume works fine. This plan is for when you need multi-machine deployment or want CDN-backed audio streaming.

## Complete File Operation Inventory

Every location that reads, writes, or deletes files. File:line references are exact.

### File writes (generation output)

| Location | Operation | Files written |
|----------|-----------|---------------|
| `generate.py:106` | `write_stereo_wav(str(paths.wav), ...)` | WAV file |
| `generate.py:118-121` | `encode_mp3(...)` | MP3 file |

### File reads (serving and scoring)

| Location | Operation | Files read |
|----------|-----------|------------|
| `server.py:567-589` | `FileResponse(audio_path)` | Authenticated audio download |
| `server.py:646-673` | `FileResponse(audio_path)` | Shared album audio download |
| `scoring/pipeline.py:157` | `librosa.load(mp3_path, sr=..., mono=True)` | MP3 for scoring pipeline |

**Critical note on scoring reads**: The scoring pipeline (`pipeline.py:157`) reads MP3 files synchronously via `librosa.load()` which expects a local file path. For S3 storage, the scoring task must download the file to a temp path first, then pass the temp path to the pipeline. Presigned URLs won't work here — librosa can't read from URLs.

### File deletes

| Location | Operation | What's deleted |
|----------|-----------|----------------|
| `songs.py:430-438` `_delete_generation_files()` | `path.unlink()` | MP3, WAV, .md, .whisper files |
| `songs.py:493-495` `delete_album()` | `shutil.rmtree(album_dir)` | Entire album directory |

### File moves

| Location | Operation | What's moved |
|----------|-----------|-------------|
| `songs.py:547-564` `_move_file_and_update_path()` | `shutil.move(src, dst)` | MP3/WAV between album directories |

### Path traversal guards (must be preserved)

| Location | Guard |
|----------|-------|
| `server.py:579-580` | `.resolve()` + `.is_relative_to(output_dir)` |
| `server.py:663-664` | Same |
| `songs.py:433-434` | Same (delete) |
| `songs.py:552-553` | Same (move) |
| `songs.py:493-494` | Same (album delete) |

For S3: path traversal guards are replaced by key validation (no `..` in S3 keys). The `is_relative_to` pattern doesn't apply to S3 keys.

## Steps

### Phase 1: Storage abstraction

- [ ] Create `src/songmaker_cli/storage.py`:
  ```python
  class Storage(Protocol):
      def write(self, key: str, data: bytes) -> None: ...
      def read(self, key: str) -> bytes: ...
      def delete(self, key: str) -> None: ...
      def delete_prefix(self, prefix: str) -> int: ...
      def exists(self, key: str) -> bool: ...
      def move(self, src_key: str, dst_key: str) -> None: ...
      def local_path(self, key: str) -> Path: ...  # for librosa/scoring
      def serve_url(self, key: str) -> str | None: ...  # presigned URL or None

  class LocalStorage:
      def __init__(self, base_dir: Path): ...
      def local_path(self, key: str) -> Path:
          return self._base / key  # direct path
      def serve_url(self, key: str) -> str | None:
          return None  # use FileResponse

  class S3Storage:
      def __init__(self, bucket: str, endpoint: str, ...): ...
      def local_path(self, key: str) -> Path:
          # Download to temp file, return temp path
          # Cache in /tmp/songmaker-cache/{key_hash} with TTL
          ...
      def serve_url(self, key: str) -> str | None:
          return self._client.generate_presigned_url(...)
  ```

- [ ] `local_path()` is the critical method for scoring compatibility. `LocalStorage` returns the direct path. `S3Storage` downloads to a temp file and returns that path. The scoring pipeline doesn't need to know about storage backends.

- [ ] Factory: `create_storage(url: str | None) -> Storage`:
  - `None` or `file:///path` → `LocalStorage(path)`
  - `s3://bucket?endpoint=...` → `S3Storage(bucket, endpoint)`

- [ ] Add `storage: Storage` to `AppContext` (replace `output_dir: Path`)

- [ ] **File suffixes**: Generation files have multiple associated files per MP3 path:
  - `album/track_v1.mp3` (audio)
  - `album/track_v1.wav` (lossless audio)
  - `album/track_v1.md` (metadata)
  - `album/track_v1.whisper` (transcription)

  The storage key IS the relative path. Associated files share the same stem with different extensions. `delete(key)` should delete just the one file; `_delete_generation_files()` calls delete for each suffix.

### Phase 2: Replace direct Path operations

- [ ] `generate.py:106,118` — Use `storage.write(key, data)` instead of direct file writes. The `_write_output` function needs to write to a temp dir first (mastering + encoding produce files), then `storage.write()` each file.

- [ ] `songs.py:430-438` `_delete_generation_files()` — Replace `path.unlink()` with `storage.delete(key)`. Remove `is_relative_to` guard (storage backend validates keys).

- [ ] `songs.py:493-495` `delete_album()` — Replace `shutil.rmtree` with `storage.delete_prefix(album_id + "/")`.

- [ ] `songs.py:547-564` `_move_file_and_update_path()` — Replace `shutil.move` with `storage.move(src_key, dst_key)`. For S3: copy + delete (no atomic move).

- [ ] `server.py:567-589` `get_audio()` — Check `storage.serve_url(key)`:
  - If URL returned: `RedirectResponse(url, status_code=302)`
  - If None (local): `FileResponse(storage.local_path(key))`

- [ ] `server.py:646-673` `get_shared_audio()` — Same pattern.

- [ ] `scoring/pipeline.py:157` — Use `storage.local_path(key)` to get a local file path for `librosa.load()`. For S3, this downloads the file first.

- [ ] `jobs.py:276-307` `run_scoring_job()` — The file existence check (`mp3_full.is_file()` at line ~285) needs to use `storage.exists(key)` instead.

### Phase 3: Audio serving

- [ ] Local: keep `FileResponse` (no change)
- [ ] S3: generate presigned URL (1 hour expiry), return 302 redirect
- [ ] Shared albums: presigned URLs with longer expiry or proxy through API
- [ ] Include ownership check BEFORE generating presigned URL (same as now)

### Phase 4: Docker / MinIO

- [ ] Add MinIO service to Docker Compose (S3-compatible, self-hosted)
- [ ] Create bucket on startup
- [ ] `STORAGE_URL=s3://songmaker?endpoint=http://minio:9000`
- [ ] Worker and API both use same S3 endpoint

## Design Decisions

### Presigned URLs vs proxy
Presigned URLs are faster (client downloads directly from S3/MinIO) but expose the storage endpoint. Proxy is simpler for auth but adds latency. **Decision: presigned URLs** for authenticated endpoints, proxy for shared albums (simpler, no exposed URLs).

### File paths in DB
Keep relative paths (`album/track_v1.mp3`) as storage keys. No DB migration needed. The storage backend interprets the key as a local path or S3 key.

### Scoring pipeline file access
`librosa.load()` requires a local file path. The `local_path()` method on `S3Storage` downloads to a temp directory with caching. This adds latency for S3 but preserves the entire scoring pipeline without changes. Alternative: refactor scoring to accept bytes — too invasive, not worth it.

### When to migrate
Only needed when API and worker are on different machines. For single-machine Docker Compose, a shared volume (`songmaker-audio:/app/_output`) is simpler and has zero code changes. **Start with shared volume, migrate to S3 when needed.**

## Testing

- Storage abstraction: unit tests with both `LocalStorage` and `S3Storage` (moto mock)
- Integration: Docker Compose with MinIO, generate → score → serve → delete cycle
- Existing tests: use `LocalStorage` (default), no changes needed
- Scoring test: verify `local_path()` returns valid path for `librosa.load()`
