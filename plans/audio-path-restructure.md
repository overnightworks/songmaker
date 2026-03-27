# Audio Path Restructure + MP3/WAV Reimport

> **Status: IMPLEMENTED**

## Problem

Audio files live under `_output/{album_name}/{song_title}_v{N}.mp3` — a structure derived from mutable album/song names with no user isolation. Two users creating an album with the same name would collide. Renaming albums would break file paths. The `_output` name is unclear and conflates audio storage with DB/session-secret storage.

## Goal

Professional ID-based paths with per-user filesystem isolation. Plus a reimport command to bring select MP3/WAV files from the old structure into the new one.

## New Structure

```
data/                          # DATA_ROOT — app data
├── audio/                     # AUDIO_ROOT — all audio files
│   ├── {user_id}/
│   │   ├── {generation_id}.mp3
│   │   └── {generation_id}.wav
│   └── {user_id_2}/
│       └── ...
├── songmaker.db               # SQLite fallback (when no DATABASE_URL)
└── .session_secret            # HMAC signing key
```

- Paths in DB: `{user_id}/{generation_id}.mp3` (relative to audio root)
- Filenames are UUIDs — immutable, globally unique, no versioning needed
- Album/song metadata stays in DB, not filesystem
- Renaming albums/songs = zero filesystem changes
- User deletion = `rm -rf data/audio/{user_id}/`

## Phase 1: Constants and AppContext

### `constants.py`
- Replace `OUTPUT_ROOT = "_output"` with `DATA_ROOT = "data"` and `AUDIO_ROOT = "data/audio"`
- Keep `OUTPUT_ROOT` temporarily as deprecated alias (used by `main.py` escape hatches)

### `app_context.py`
- Rename `output_dir: Path` → `audio_dir: Path`
- Add `data_dir: Path` for DB/session-secret location

### `config.py`
- Remove `OutputPaths` class, `resolve_output_paths()`, `next_version()`
- Add simple helper:
  ```python
  def audio_file_path(audio_dir: Path, user_id: str, generation_id: str, suffix: str) -> Path:
      path = audio_dir / user_id / f"{generation_id}{suffix}"
      path.parent.mkdir(parents=True, exist_ok=True)
      return path
  ```
- `load_generation_defaults` / `_migrate_file_defaults`: change `output_dir` param → `data_dir` (these look for `generation_defaults.json` in the data root, not audio root)

## Phase 2: Generation Pipeline

### `generate.py`
- `generate_single` signature: replace `output_root: Path` with `audio_dir: Path`, `user_id: str`, `generation_id: str`
- Remove `resolve_output_paths` call — compute paths directly via `audio_file_path`
- `GenerationResult`: remove `output_paths: OutputPaths` field, keep `mp3_path`, `wav_path`, `seed`, `duration`
- `_write_output`: takes mp3/wav `Path` directly instead of `OutputPaths`

### `jobs.py`
- `GenerationContext`: rename `output_root` → `audio_dir`, add `user_id: str`
- `_build_generation_context`: get `user_id` from `song.album.created_by`; pass to context
- `run_generation_job`:
  - Generate UUID for each generation upfront
  - Pass `audio_dir`, `user_id`, `generation_id` to `generate_single`
  - Store relative path as `f"{user_id}/{generation_id}.mp3"` (not album-based)
- `run_scoring_job`: rename `output_dir` → `audio_dir` (path resolution unchanged — `audio_dir / mp3_path_rel` still works)
- `load_generation_defaults` call: pass `data_dir` instead of `output_dir`

### `worker.py`
- `_output_dir()` → split into `_audio_dir()` (env `AUDIO_DIR`, default `data/audio`) and `_data_dir()` (env `DATA_DIR`, default `data`)
- Pass `audio_dir` to generation/scoring jobs, `data_dir` for DB URL resolution

## Phase 3: Audio Serving

### `server.py`
- **`create_app` params**: `output_dir` → `audio_dir`; add `data_dir` for DB/secret
- **`run_server`**: compute `audio_dir = project_root / AUDIO_ROOT`, `data_dir = project_root / DATA_ROOT`
- **Audio endpoint**: `GET /audio/{album}/{filename}` → `GET /audio/{owner_id}/{filename}`
  - Ownership: `owner_id == user.id or user.role == "admin"` (no DB query needed)
  - Path traversal check stays
- **Shared audio endpoint**: unchanged — resolves `audio_dir / gen.mp3_path` where `gen.mp3_path` is now `{user_id}/{gen_id}.mp3`
- **DB/secret init**: `resolve_database_url(data_dir)`, `ensure_session_secret(data_dir)`

### `settings_api.py`
- `load_generation_defaults(ctx.db, ctx.output_dir)` → `load_generation_defaults(ctx.db, ctx.data_dir)`

## Phase 4: Database Queries

### `db/queries/songs.py`
- `delete_generation_files`: rename `output_dir` → `audio_dir` (logic unchanged)
- `delete_album`: remove `shutil.rmtree` of album directory (files are under `user_id/`, not `album_id/`). Individual generation file deletion stays.
- `move_song`: remove `_move_generation_files` call entirely — file paths don't contain album info, so moving a song between albums is a pure DB update
- Remove `_move_generation_files` and `_move_file_and_update_path` — dead code after restructure

### `generation_api.py`
- `ctx.output_dir` → `ctx.audio_dir`
- Remove `api_rate_by_path` endpoint — encodes old album-based path structure. Rating by generation ID (`POST /api/generations/{gen_id}/rate`) is the primary path. The frontend uses it. The CLI uses it.
- Remove `get_generation_by_path` import (only used by `api_rate_by_path`)

### `album_api.py`, `song_api.py`
- `ctx.output_dir` → `ctx.audio_dir`

## Phase 5: Reimport

### `reimport.py` (new file)
Core logic:
1. Read ID3 tags from MP3 (or basic metadata from WAV header) using `mutagen`
2. Accept `user_id`, `album_id`, `song_id` (caller provides context)
3. Generate a new generation UUID
4. Copy MP3 to `data/audio/{user_id}/{generation_id}.mp3`
5. If WAV provided alongside MP3 (or WAV-only), copy that too
6. Create `Generation` record in DB with the new path
7. Extract seed from ID3 comment field (`seed=N`) if present

Supports:
- MP3 file → copies as-is
- WAV file → copies as-is (no transcoding)
- Both MP3 + WAV for the same generation

### `reimport_api.py` (new file)
- `POST /api/songs/{song_id}/reimport` — multipart file upload
- Accepts one or two files (MP3 and/or WAV)
- Requires authentication + song ownership check
- Body size exemption: override `MAX_REQUEST_BODY_BYTES` for this endpoint (MP3s ~3-10 MB)
- Returns `GenerationResponse`

### `main.py`
- Add CLI command: `songmaker reimport <file> --song <song_id> [--wav <wav_file>]`
- Uses the API endpoint (consistent with "one code path" rule)

### `api.py`
- Include reimport router

## Phase 6: CLI Escape Hatches

### `main.py`
- `reset-password` and `list-users` use `OUTPUT_ROOT` to find SQLite DB → change to `DATA_ROOT`
- Update `--output` flag help text

## Phase 7: Tests

### Update existing tests
- All test fixtures creating files under `output_dir / album_name /` → create under `audio_dir / user_id /`
- `test_server.py`: update audio endpoint URLs from `/audio/{album}/{file}` to `/audio/{user_id}/{file}`
- `test_api.py`: update `_seed_db` path format, remove `test_rate_by_path` tests
- `test_sharing.py`: update mp3_path format in seed data
- All `AppContext(output_dir=...)` → `AppContext(audio_dir=..., data_dir=...)`

### New tests
- `test_reimport.py`: reimport MP3 with ID3 tags, reimport WAV, reimport both, missing file, song ownership check
- `test_config.py`: test `audio_file_path` helper (if not already covered)

## Phase 8: Documentation

- `docs/architecture.md`: update file structure diagram, path description
- `docs/security.md`: update path traversal section for new endpoint structure
- `CLAUDE.md`: update "Where Things Go" table if needed

## Files Changed (summary)

| File | Change |
|------|--------|
| `constants.py` | `DATA_ROOT`, `AUDIO_ROOT` replace `OUTPUT_ROOT` |
| `app_context.py` | `output_dir` → `audio_dir` + `data_dir` |
| `config.py` | Remove `OutputPaths`/`resolve_output_paths`/`next_version`; add `audio_file_path` |
| `generate.py` | New signature (`audio_dir`, `user_id`, `generation_id`) |
| `jobs.py` | `output_root` → `audio_dir`; UUID-based paths; pass `user_id` |
| `worker.py` | Split `_output_dir()` into `_audio_dir()` + `_data_dir()` |
| `server.py` | New audio endpoint; `output_dir` → `audio_dir`; separate `data_dir` |
| `generation_api.py` | `ctx.output_dir` → `ctx.audio_dir`; remove `rate_by_path` |
| `song_api.py` | `ctx.output_dir` → `ctx.audio_dir` |
| `album_api.py` | `ctx.output_dir` → `ctx.audio_dir` |
| `settings_api.py` | Use `ctx.data_dir` for defaults |
| `db/queries/songs.py` | `output_dir` → `audio_dir`; remove `move_song` file ops; remove album dir cleanup |
| `main.py` | Add `reimport` command; `OUTPUT_ROOT` → `DATA_ROOT` for DB paths |
| `reimport.py` | **New**: reimport logic |
| `reimport_api.py` | **New**: reimport API endpoint |
| `api.py` | Include reimport router |
| `auth.py` | `ensure_session_secret` param name (cosmetic) |
| `db/engine.py` | `resolve_database_url` param name (cosmetic) |
| Tests (8+ files) | Path fixtures, endpoint URLs, AppContext fields |
| Docs (3 files) | Architecture, security, CLAUDE.md |

## Not Included

- **Data migration script** — user will cherry-pick MP3s via reimport
- **Auto-scoring on reimport** — user will score manually
- **Transcoding** — reimport copies files as-is
