# Coverage to 100% on Core Modules

## Problem

Overall coverage is 94%. CLAUDE.md targets 100% on core modules (excluding `main.py`). The gaps:

| File | Current | Missing |
|------|---------|---------|
| `cli_client.py` | 78% | HTTP session persistence, cookie handling, poll_job progress bar, resolve_song edge cases |
| `server.py` | 94% | CORS wildcard validation, SPA fallback, static file serving, HTTPS redirect |
| `acestep_engine/client.py` | 94% | Retry edge cases, audio download bounds |
| `audio_engine/audio_io.py` | 94% | Dtype normalization edge cases, stereo duplication |
| `audio_engine/mastering.py` | 97% | LUFS measurement fallback, filter edge cases |

## Scope

Small — ~15-20 new test cases across 5 files. No architecture changes.

## Priority

Low — existing coverage catches regressions. This is polish.
