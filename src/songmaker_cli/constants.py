"""Non-model constants for the songmaker CLI."""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from acestep_engine.constants import MODEL_CONFIG_PATHS as MODEL_CONFIG_PATHS

APP_NAME = "Hallucinai"

# The two PWA icon files SvelteKit's static build emits. Shared by
# server.py (SPA-fallback 404 exclusion, see `_pwa_exact_paths`) and
# rate_limit.py (per-IP budget exemption) so the two never drift.
PWA_ICON_PATHS: Final[frozenset[str]] = frozenset({
    "/icon-192.png",
    "/icon-512.png",
})

MODEL_AVAILABLE_MODES: Final[frozenset[str]] = frozenset({
    "turbo",
    "sft",
    "xl-turbo",
    "xl-sft",
    "xl-base",
})
MODEL_DEFAULT_MODE: Final[str] = "sft"

DEFAULT_ARTIST = "Flex0r"

# Pagination defaults and limits
PAGE_DEFAULT_LIMIT = 50
PAGE_MAX_LIMIT = 200
PAGE_ADMIN_DEFAULT_LIMIT = 100
PAGE_ADMIN_MAX_LIMIT = 500

LIBRARY_SORT_NEWEST: Final[str] = "newest"
LIBRARY_SORT_OLDEST: Final[str] = "oldest"
LIBRARY_SORT_TITLE: Final[str] = "title"
LIBRARY_SORTS: Final[frozenset[str]] = frozenset({
    LIBRARY_SORT_NEWEST,
    LIBRARY_SORT_OLDEST,
    LIBRARY_SORT_TITLE,
})
LIBRARY_ITEM_ALBUM: Final[str] = "album"
LIBRARY_ITEM_SONG: Final[str] = "song"
LIBRARY_ITEM_GENERATION: Final[str] = "generation"
LIBRARY_ITEM_PLAYLIST: Final[str] = "playlist"
SHARE_INVENTORY_TYPES: Final[frozenset[str]] = frozenset({
    LIBRARY_ITEM_ALBUM,
    LIBRARY_ITEM_SONG,
    LIBRARY_ITEM_GENERATION,
    LIBRARY_ITEM_PLAYLIST,
})
SHARE_PUBLIC_PATH_ALBUM: Final[str] = "/share/{slug}"
SHARE_PUBLIC_PATH_SONG: Final[str] = "/share/song/{slug}"
SHARE_PUBLIC_PATH_GENERATION: Final[str] = "/share/gen/{slug}"
SHARE_PUBLIC_PATH_PLAYLIST: Final[str] = "/share/playlist/{slug}"
LIBRARY_CURSOR_VERSION: Final[int] = 1
LIBRARY_CURSOR_KEY_VERSION: Final[str] = "v"
LIBRARY_CURSOR_KEY_Q: Final[str] = "q"
LIBRARY_CURSOR_KEY_SORT: Final[str] = "sort"
LIBRARY_CURSOR_KEY_TYPE: Final[str] = "type"
LIBRARY_CURSOR_KEY_SORT_VALUE: Final[str] = "sort_value"
LIBRARY_CURSOR_KEY_ID: Final[str] = "id"
LIBRARY_QUERY_REQUIRED: Final[str] = "Search query is required"
LIBRARY_CURSOR_INVALID: Final[str] = "Invalid library cursor"
LIBRARY_CURSOR_MISMATCH: Final[str] = "Library cursor does not match query and sort"
LIKE_ESCAPE_CHAR: Final[str] = "\\"

# Scoring pipeline
SILENCE_TOP_DB = 40
SILENCE_MIN_GAP_SECONDS = 2.0
SILENCE_TRIM_SECONDS = 2.0
SCORING_SAMPLE_RATE = 22050
SCORING_NUM_SECTIONS = 6
DYNAMICS_PITCH_WEIGHT = 0.4
DYNAMICS_RMS_WEIGHT = 0.3
DYNAMICS_ONSET_WEIGHT = 0.3
# Calibrated against real song data (v32, v108, v109, v112):
# pitch_cv range: 0.03–0.49, rms_contrast: 1.47–1.93, onset_cv: 0.10–0.28
DYNAMICS_PITCH_CV_CEILING = 0.5
DYNAMICS_RMS_CONTRAST_CEILING = 3.0
DYNAMICS_ONSET_CV_CEILING = 0.5

# Spectral quality scorer
SPECTRAL_WINDOW_SECONDS = 5.0
SPECTRAL_ARTIFACT_MULTIPLIER = 2.0
SPECTRAL_ABSOLUTE_THRESHOLD = 0.1

# Whisper transcription (faster-whisper / CTranslate2)
WHISPER_COMPUTE_TYPE = "int8_float16"
WHISPER_BEAM_SIZE = 5
WHISPER_TEMPERATURE = 0.0

SETTING_CLAUDE_CHAT_MODEL = "claude_chat_model"
SETTING_CLAUDE_SCORING_MODEL = "claude_scoring_model"
# Default for Settings.claude_scoring_model, which the DB setting overrides
# (get_claude_scoring_model). Since #315 the coherence judge itself reads
# judge_provider/judge_model instead; get_judge_model() falls back to this
# chain only while the judge provider stays on its default, Claude, so a
# musician who already customized claude_scoring_model keeps that value.
CLAUDE_SCORING_MODEL_DEFAULT = "claude-opus-4-6"
SETTING_COWRITER_PROVIDER = "cowriter_provider"
SETTING_COWRITER_MODEL = "cowriter_model"
SETTING_COWRITER_TAIL_TOKEN_BUDGET = "cowriter_tail_token_budget"  # nosec B105
SETTING_JUDGE_PROVIDER = "judge_provider"
SETTING_JUDGE_MODEL = "judge_model"
# The judge is its own task with its own provider choice (not coupled to the
# co-writer's), but its default must not move the goalposts on day one: the
# default provider stays Claude, and get_judge_model() falls back to the
# pre-existing claude_scoring_model default when unset (#315).
JUDGE_DEFAULT_PROVIDER = "claude"

MEMORY_SCOPE_USER = "user"
MEMORY_SCOPE_SONG = "song"
MEMORY_SCOPE_ALBUM = "album"
MEMORY_SCOPES: Final[frozenset[str]] = frozenset({
    MEMORY_SCOPE_USER,
    MEMORY_SCOPE_SONG,
    MEMORY_SCOPE_ALBUM,
})
MEMORY_MAX_LENGTH = 20_000

TURN_BLOCK_CURRENT_SONG = "current_song"
TURN_BLOCK_USER_MEMORY = "user_memory"
TURN_BLOCK_SONG_MEMORY = "song_memory"
TURN_BLOCK_ALBUM_NOTES = "album_notes"
TURN_BLOCK_MENTIONED_SONGS = "mentioned_songs"
TURN_BLOCK_MENTIONED_VERSIONS = "mentioned_versions"
TURN_BLOCK_MENTIONED_ALBUM = "mentioned_album"
TURN_BLOCK_CURRENT_TAKE = "current_take"
TURN_BLOCK_NO_TAKE = "no_take"

COWRITER_PROVIDERS: Final[frozenset[str]] = frozenset({"claude", "grok", "codex"})
COWRITER_DEFAULT_PROVIDER = "claude"
COWRITER_DEFAULT_TAIL_TOKEN_BUDGET = 24_000
COWRITER_MIN_TAIL_TOKEN_BUDGET = 2_000
COWRITER_MAX_TAIL_TOKEN_BUDGET = 100_000
COWRITER_CLI_TIMEOUT_SECONDS = 600
COWRITER_MAX_TOOL_ROUNDS = 8
COWRITER_MODELS_TIMEOUT_SECONDS = 15
CLI_LOGIN_STATUS_CACHE_SECONDS = 30
# Agent CLI login probes return only a few hundred bytes. These bounds keep a
# broken mounted binary from holding a request or its memory indefinitely.
CLI_OUTPUT_READ_LIMIT_BYTES = 64 * 1024
CLI_TERMINATION_GRACE_SECONDS = 1
# The real init event measured 0.34s (see docs/security.md); these budgets
# keep a wide margin over that without letting a stuck probe block a request
# for anywhere near as long as the old 30s did.
CLAUDE_CLI_TOOL_SURFACE_TIMEOUT_SECONDS = 10
CLAUDE_CLI_NO_TOOL_SURFACE_TIMEOUT_SECONDS = 5
CLAUDE_CLI_COMPLETION_TIMEOUT_SECONDS = 120
# A judge timeout has one stable reason across its provider's own bound and
# the outer watchdog, so callers need not infer it from incidental prose.
JUDGE_FAILURE_TIMEOUT: Final[str] = "judge_timeout"
# Short on purpose: long enough to shield a struggling probe from being
# re-run by every concurrent caller, short enough that a real repair (binary
# reinstalled, DB reachable again) is picked up on the next request rather
# than staying failed for the lifetime of the success cache.
CLAUDE_CLI_TOOL_SURFACE_FAILURE_CACHE_SECONDS = 10
# How long a probe waits for SIGTERM to take effect before escalating to
# SIGKILL. Named rather than a literal so the reap budget below is legible
# as spelled-out arithmetic, not a mystery "+1".
CLAUDE_CLI_SIGTERM_GRACE_SECONDS = 1
# After SIGKILL a process cannot ignore the signal, so this bounds only the
# pathological case (an uninterruptible kernel sleep, a stuck watcher) —
# not a normal exit, which is immediate. Chosen well above that normal case
# so it never fires in practice, and well below any caller's own timeout so
# a stuck reap cannot block whoever is waiting on its outcome past it.
CLAUDE_CLI_ZOMBIE_REAP_TIMEOUT_SECONDS = 5
# A process that outlives SIGKILL is not a transient hiccup — ten more
# seconds will not make it healthy, and probing again on that schedule only
# spawns another zombie. Cached failures of that specific kind get this much
# longer TTL instead of CLAUDE_CLI_TOOL_SURFACE_FAILURE_CACHE_SECONDS.
CLAUDE_CLI_ZOMBIE_FAILURE_CACHE_SECONDS = 300
# A hard ceiling on background reapers tracked at once (across every key and
# every process the tool-surface probe has ever spawned) — small on purpose:
# beyond it, a new zombie is logged and left for the OS/asyncio's own child
# reaping rather than growing an unbounded pool of waiting tasks/threads.
CLAUDE_CLI_MAX_CONCURRENT_ZOMBIE_REAPERS = 8
COWRITER_GROK_CHAT_URL = "https://api.x.ai/v1/chat/completions"
COWRITER_GROK_MODELS_URL = "https://api.x.ai/v1/models"
COWRITER_OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
COWRITER_OPENAI_MODELS_URL = "https://api.openai.com/v1/models"
COWRITER_ANTHROPIC_MODELS_URL = "https://api.anthropic.com/v1/models"
ANTHROPIC_API_VERSION = "2023-06-01"
COWRITER_GROK_MODEL_PREFIX = "grok-"
COWRITER_GROK_NON_CHAT_MARKERS: Final[tuple[str, ...]] = (
    "imagine", "image", "video", "voice", "tts", "whisper",
)
COWRITER_OPENAI_CHAT_PREFIXES: Final[tuple[str, ...]] = (
    "gpt-", "o1", "o3", "o4", "codex",
)
COWRITER_OPENAI_NON_CHAT_MARKERS: Final[tuple[str, ...]] = (
    "whisper", "tts", "embedding", "dall-e", "dalle", "transcribe", "realtime",
    "audio", "image", "search", "moderation",
)
COWRITER_CLAUDE_MODEL_PREFIX = "claude-"
COWRITER_CLAUDE_CLI_MODEL_LIST_MARKER = "Available: "

CLAUDE_CLI_BINARY: Final[str] = "claude"
CLAUDE_CLI_STATUS_ARGS: Final[tuple[str, ...]] = ("auth", "status")
CLAUDE_CLI_LOGGED_IN_FIELD: Final[str] = "loggedIn"
CLAUDE_CLI_AUTH_METHOD_FIELD: Final[str] = "authMethod"
GROK_CLI_BINARY: Final[str] = "grok"
GROK_CLI_STATUS_ARGS: Final[tuple[str, ...]] = ("models",)
GROK_CLI_LOGGED_IN_MARKER: Final[str] = "You are logged in with "
GROK_CLI_LOGGED_OUT_MARKER: Final[str] = "You are not authenticated."
GROK_CLI_MODEL_LIST_MARKER: Final[str] = "Available models:"
GROK_CLI_MODEL_BULLETS: Final[tuple[str, ...]] = ("* ", "- ")
CODEX_CLI_BINARY: Final[str] = "codex"
CODEX_CLI_STATUS_ARGS: Final[tuple[str, ...]] = ("login", "status")
CODEX_CLI_LOGGED_IN_MARKER: Final[str] = "Logged in using "
CODEX_CLI_LOGGED_OUT_MARKER: Final[str] = "Not logged in"
COWRITER_SUMMARY_TAG = "conversation_summary"
COWRITER_MAX_SUMMARY_CHARS = 12_000

# Owned solely by the legacy `/settings/claude-models` endpoint and the dead
# chat_api.py co-writer (chat_model). scoring_model is not orphaned: it is
# the Claude judge's fallback until a judge_provider/judge_model pair is
# configured (#315, get_judge_model()) — once that pair exists it takes over
# and scoring_model has no further effect. The co-writer reads its live
# catalog instead (cowriter/catalog.py). Retire this list with chat_api.py's
# cleanup.
MODEL_ALLOWED_CLAUDE = frozenset({
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
})

# Whisper hallucination detection
HALLUCINATION_MIN_LINES = 5
HALLUCINATION_MAX_UNIQUE = 2
HALLUCINATION_PHRASE_RATIO = 0.5

# Sharing
SHARING_RATE_LIMIT = 60
SHARING_RATE_WINDOW_SECONDS = 60
SHARING_STREAM_RATE_LIMIT = 6
SHARING_STREAM_RATE_WINDOW_SECONDS = 60
QUEUE_STREAM_AUTH_RATE_LIMIT = 12
QUEUE_STREAM_AUTH_RATE_WINDOW_SECONDS = 60
QUEUE_STREAM_EMPTY_POOL_DETAIL = "No playable takes in pool"
QUEUE_STREAM_UNPLAYABLE_START_DETAIL = "Requested take is not playable"

# Redis key prefixes
REDIS_KEY_PREFIX = "songmaker"
REDIS_METRICS_HTTP_KEY = f"{REDIS_KEY_PREFIX}:metrics:http"
REDIS_METRICS_DURATION_KEY = f"{REDIS_KEY_PREFIX}:metrics:http:duration"
REDIS_METRICS_TOTAL_KEY = f"{REDIS_KEY_PREFIX}:metrics:http:total"
REDIS_RL_IP_PREFIX = "rl:ip"
REDIS_RL_IP_MEDIA_PREFIX = "rl:ip-media"
REDIS_RL_IP_STREAM_PREFIX = "rl:ip-stream"
REDIS_RL_SHARED_PREFIX = "rl:shared"
REDIS_RL_SHARED_STREAM_PREFIX = "rl:shared-stream"
REDIS_RL_QUEUE_STREAM_PREFIX = "rl:queue-stream"
REDIS_RL_RESOURCE_STREAM_PREFIX = "rl:resource-stream"
REDIS_SESSION_PREFIX = f"{REDIS_KEY_PREFIX}:session"
REDIS_USER_SESSIONS_PREFIX = f"{REDIS_KEY_PREFIX}:user_sessions"
REDIS_RESOURCE_STREAM_LEASE_USER_PREFIX = f"{REDIS_KEY_PREFIX}:resource-stream:user"
REDIS_RESOURCE_STREAM_LEASE_GLOBAL_KEY = f"{REDIS_KEY_PREFIX}:resource-stream:global"
REDIS_JOB_STREAM_LEASE_USER_PREFIX = f"{REDIS_KEY_PREFIX}:job-stream:user"
REDIS_JOB_STREAM_LEASE_GLOBAL_KEY = f"{REDIS_KEY_PREFIX}:job-stream:global"
REDIS_SESSION_SYNC_INTERVAL_SECONDS = 300
REDIS_DEGRADED_THRESHOLD = 3
REDIS_SOCKET_TIMEOUT_SECONDS: Final[float] = 2.0

# Session
HTTP_MAX_USER_AGENT_LENGTH = 500

# Global generation defaults
PRESET_GLOBAL_DEFAULTS_NAME = "__global_defaults__"

# Shared tmp dir for repaint/cover source audio — must be on the audio
# volume so the acestep-worker container can read what the music-worker
# wrote (each container has its own /tmp).
WORKER_SHARED_TMP_DIRNAME = ".tmp"

# Scoring subprocess. Each scorer runs under its own budget; text_accuracy
# gets a larger one because a cold Whisper model load counts against it.
# The pipeline watchdog must outlive the slowest single scorer plus the
# dependent scorers that run after it, otherwise the per-scorer budget is
# unreachable and the whole run is killed instead of one scorer.
SCORING_PIPELINE_TIMEOUT_SECONDS = 240
SCORING_PIPELINE_TIMEOUT_HEADROOM_SECONDS = 120
SCORER_TIMEOUT_SECONDS = 120
TEXT_ACCURACY_TIMEOUT_SECONDS = 300

# arq worker
RECOVERY_LOCK_KEY = f"{REDIS_KEY_PREFIX}:recovery_lock"
RECOVERY_LOCK_TTL_SECONDS = 30
ARQ_MUSIC_QUEUE_NAME = "arq:queue:music"
ARQ_SCORING_QUEUE_NAME = "arq:queue:scoring"
ARQ_MUSIC_HEALTH_KEY = f"{ARQ_MUSIC_QUEUE_NAME}:health-check"
ARQ_SCORING_HEALTH_KEY = f"{ARQ_SCORING_QUEUE_NAME}:health-check"
RECOVERY_LOCK_MUSIC_KEY = f"{REDIS_KEY_PREFIX}:recovery_lock:music"
RECOVERY_LOCK_SCORING_KEY = f"{REDIS_KEY_PREFIX}:recovery_lock:scoring"
SESSION_SYNC_LOCK_KEY = f"{REDIS_KEY_PREFIX}:session_sync_lock"
SESSION_SYNC_LOCK_TTL_SECONDS = 60

# Score backfill (issue #222): catches up generations that predate
# auto-scoring, or that an auto-score attempt could not reach (worker down,
# enqueue failure). Small batch on a short interval so a large backlog is
# worked off gradually rather than as one big-bang burst against the CPU-only
# scoring worker.
SCORE_BACKFILL_INTERVAL_SECONDS = 120
SCORE_BACKFILL_BATCH_SIZE = 5
SCORE_BACKFILL_LOCK_KEY = f"{REDIS_KEY_PREFIX}:score_backfill_lock"
SCORE_BACKFILL_LOCK_TTL_SECONDS = 60
# A chronically-unscorable generation (corrupt file, scorer bug) must not
# starve the rest of the backlog by winning the same oldest-first batch every
# tick forever. Redis tracks a per-generation attempt count (no schema
# change); once a generation hits SCORE_BACKFILL_MAX_ATTEMPTS it is skipped
# until its counter's TTL lapses, letting it try again later (e.g. after a
# scorer fix). The candidate pool is read wider than one batch so exhausted
# generations at the front of the oldest-first list don't crowd out eligible
# ones behind them.
SCORE_BACKFILL_MAX_ATTEMPTS = 3
SCORE_BACKFILL_ATTEMPT_TTL_SECONDS = 7 * 24 * 60 * 60
SCORE_BACKFILL_CANDIDATE_POOL_SIZE = SCORE_BACKFILL_BATCH_SIZE * 4
SCORE_BACKFILL_ATTEMPTS_KEY_PREFIX = f"{REDIS_KEY_PREFIX}:score_backfill:attempts"
SCORE_BACKFILL_TRACKED_SET_KEY = f"{REDIS_KEY_PREFIX}:score_backfill:tracked"

# Startup error messages
REDIS_STARTUP_ERROR = (
    "Cannot connect to Redis at {url}. "
    "Redis is required — set REDIS_URL in .env or start Redis."
)
# Prometheus metric names
PROM_HTTP_REQUESTS_TOTAL = "songmaker_http_requests_total"
PROM_HTTP_REQUEST_DURATION_MS = "songmaker_http_request_duration_milliseconds_total"
PROM_ACTIVE_SESSIONS = "songmaker_active_sessions"
PROM_JOBS_TOTAL = "songmaker_jobs_total"
# When the newest job failure finished, as Unix time (issue #333). A
# timestamp rather than a failure counter, because every counter-shaped
# answer needs history the alarm may not have: a per-type
# songmaker_jobs_total{status="failed"} series only comes into existence
# WITH the first failure of that type, and even an always-exported total
# reads 1 on Prometheus' FIRST sample if the failure happened between the
# web container becoming healthy and that first scrape. increase() finds
# no rise across a series' first sample either way, so exactly the first
# failure of a fresh stack went unalerted. "How long ago was the last
# one" needs no history: one sample carries the whole answer.
PROM_LAST_JOB_FAILURE_TIMESTAMP = "songmaker_last_job_failure_timestamp_seconds"
# What that metric reads while nothing has ever failed: the Unix epoch,
# which puts `time() - <metric>` decades outside every alert window
# without the series ever having to be absent.
PROM_NEVER_FAILED_TIMESTAMP = 0.0
PROM_JOB_DURATION_SECONDS = "songmaker_job_duration_seconds"
# Labeled by queue ("music"/"scoring") — the arq queue names the workers
# actually run on. Renders as songmaker_queue_depth{queue="music"} etc.
# (issue #333, #330 Finding 3): the previous single unlabeled value read
# the arq client library's own default queue key, which nothing in this
# codebase ever enqueues to, so it was always 0.
PROM_QUEUE_DEPTH = "songmaker_queue_depth"
PROM_ACESTEP_WORKERS_TOTAL = "songmaker_acestep_workers_total"
PROM_ACESTEP_WORKER_LOADED_MODELS = "songmaker_acestep_worker_loaded_models"
PROM_ACESTEP_WORKER_QUEUE_DEPTH = "songmaker_acestep_worker_queue_depth"
# Per-worker VRAM from the acestep-worker's own heartbeat (issue #333,
# #330 Finding 4) — replaces songmaker_gpu_vram_megabytes, which could
# never be produced from the songmaker-web container itself (no GPU
# runtime, no NVML there) and always read empty.
PROM_ACESTEP_WORKER_VRAM_USED_GB = "songmaker_acestep_worker_vram_used_gigabytes"
PROM_ACESTEP_WORKER_VRAM_TOTAL_GB = "songmaker_acestep_worker_vram_total_gigabytes"
PROM_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"

# Background loop health (issue #396)
BACKGROUND_LOOP_FAILURE_THRESHOLD: Final[int] = 3
PROM_BACKGROUND_LOOP_CONSECUTIVE_FAILURES = "songmaker_background_loop_consecutive_failures"
PROM_BACKGROUND_LOOP_ALIVE = "songmaker_background_loop_alive"

# Rate limit setting keys (stored in rate_limit_settings table)
SETTING_GENERATION_RATE_LIMIT = "generation_rate_limit"
SETTING_SCORING_RATE_LIMIT = "scoring_rate_limit"
SETTING_CHAT_RATE_LIMIT = "chat_rate_limit"
SETTING_MAX_QUEUE_DEPTH = "max_queue_depth"
SETTING_MAX_USER_ACTIVE_JOBS = "max_user_active_jobs"

RATE_LIMIT_SETTING_KEYS = frozenset({
    SETTING_GENERATION_RATE_LIMIT,
    SETTING_SCORING_RATE_LIMIT,
    SETTING_CHAT_RATE_LIMIT,
    SETTING_MAX_QUEUE_DEPTH,
    SETTING_MAX_USER_ACTIVE_JOBS,
})

# Response compression
GZIP_MINIMUM_SIZE_BYTES: Final[int] = 1024
# zlib's own default (6) trades ~0.5pp less reduction than level 9 for
# roughly a third of the CPU time on a typical ~24 KB whisper_cues JSON
# payload (measured: level 6 -> 3855 bytes / 0.25ms avg; level 9 -> 3728
# bytes / 0.70ms avg). Not worth the extra CPU per request for that.
GZIP_COMPRESS_LEVEL: Final[int] = 6

# SSE streaming
SSE_POLL_INTERVAL_SECONDS = 1
SSE_HEARTBEAT_SECONDS: Final[int] = 15
SSE_HEARTBEAT_COMMENT: Final[str] = ": heartbeat\n\n"
QUEUED_JOB_STALE_THRESHOLD_SECONDS: Final[int] = 900
JOB_HEARTBEAT_STALE_THRESHOLD_SECONDS: Final[int] = 180
JOB_HEARTBEAT_INTERVAL_SECONDS: Final[int] = 15
RESOURCE_EVENT_STREAM_PATH: Final[str] = "/api/resource-events/stream"
RESOURCE_EVENT_STREAM_CONNECTION_SECONDS: Final[int] = 60
RESOURCE_EVENT_STREAM_POLL_SECONDS: Final[float] = 1.0
RESOURCE_EVENT_STREAM_PAGE_SIZE: Final[int] = 100
RESOURCE_EVENT_STREAM_OPEN_WINDOW_SECONDS: Final[int] = 60
RESOURCE_EVENT_STREAM_MAX_PER_USER: Final[int] = 6
RESOURCE_EVENT_STREAM_MAX_GLOBAL: Final[int] = 12
RESOURCE_EVENT_STREAM_LEASE_SECONDS: Final[int] = 65
RESOURCE_EVENT_STREAM_LIMIT_DETAIL: Final[str] = "Too many resource streams"
RESOURCE_EVENT_STREAM_LIMITER_UNAVAILABLE: Final[str] = "Resource stream limiter unavailable"
RESOURCE_EVENT_STREAM_CAPACITY_UNAVAILABLE: Final[str] = (
    "Resource stream unavailable: no spare database capacity"
)
LAST_EVENT_ID_INVALID: Final[str] = "Last-Event-ID must be a non-negative decimal"
POSTGRES_BIGINT_MAX: Final[int] = (1 << 63) - 1
# Job SSE stream (#331 Finding 2). Forces the same kind of periodic
# reconnect as the resource-event stream, for the same reason: bound the
# worst case a single stream can stay open rather than let a queued/running
# job hold it (and, before the to_thread fix, the event loop) indefinitely.
# The frontend (jobs.ts) already reconnects an EventSource with backoff on
# any drop and resets its attempt counter on the next message, so a forced
# close here is a cheap, already-handled event, not a new failure mode.
JOB_STREAM_CONNECTION_SECONDS: Final[int] = RESOURCE_EVENT_STREAM_CONNECTION_SECONDS
JOB_STREAM_LEASE_SECONDS: Final[int] = JOB_STREAM_CONNECTION_SECONDS + 5
JOB_STREAM_LIMIT_DETAIL: Final[str] = "Too many job streams"
JOB_STREAM_LIMITER_UNAVAILABLE: Final[str] = "Job stream limiter unavailable"

# Audio file serving
AUDIO_MEDIA_TYPES: dict[str, str] = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
}

# Reference audio upload
REFERENCE_AUDIO_DIR = "refs"
REFERENCE_AUDIO_EXTENSIONS = frozenset({".mp3", ".wav", ".flac", ".ogg"})
REFERENCE_AUDIO_MAX_BYTES = 50 * 1024 * 1024
JSON_REQUEST_BODY_MAX_BYTES = 1_048_576
MULTIPART_ENVELOPE_MAX_BYTES = 1_048_576
AUDIO_UPLOAD_FILE_MAX_BYTES = REFERENCE_AUDIO_MAX_BYTES
AUDIO_UPLOAD_BODY_MAX_BYTES = AUDIO_UPLOAD_FILE_MAX_BYTES + MULTIPART_ENVELOPE_MAX_BYTES
REIMPORT_BODY_MAX_BYTES = (2 * AUDIO_UPLOAD_FILE_MAX_BYTES) + MULTIPART_ENVELOPE_MAX_BYTES

COVER_DIRNAME: Final[str] = "covers"
SONG_COVER_DIRNAME: Final[str] = "song-covers"
COVER_MAX_BYTES: Final[int] = 8 * 1024 * 1024
COVER_MAX_PIXELS: Final[int] = 20_000_000
COVER_CARD_MAX_EDGE: Final[int] = 512
COVER_DETAIL_MAX_EDGE: Final[int] = 1024
COVER_JPEG_QUALITY: Final[int] = 85
COVER_UPLOAD_BODY_MAX_BYTES: Final[int] = COVER_MAX_BYTES + MULTIPART_ENVELOPE_MAX_BYTES
COVER_VARIANT_ORIGINAL: Final[str] = "original"
COVER_VARIANT_CARD: Final[str] = "card"
COVER_VARIANT_DETAIL: Final[str] = "detail"
COVER_VARIANTS: Final[frozenset[str]] = frozenset({
    COVER_VARIANT_ORIGINAL,
    COVER_VARIANT_CARD,
    COVER_VARIANT_DETAIL,
})
COVER_KEY_JPEG: Final[str] = "jpg"
COVER_KEY_PNG: Final[str] = "png"
COVER_KEYS: Final[frozenset[str]] = frozenset({COVER_KEY_JPEG, COVER_KEY_PNG})
COVER_JPEG_EXTENSION: Final[str] = ".jpg"
COVER_PNG_EXTENSION: Final[str] = ".png"
COVER_JPEG_MAGIC: Final[bytes] = b"\xff\xd8\xff"
COVER_PNG_MAGIC: Final[bytes] = b"\x89PNG\r\n\x1a\n"
COVER_FORMAT_JPEG: Final[str] = "jpeg"
COVER_FORMAT_PNG: Final[str] = "png"
COVER_MEDIA_TYPE_JPEG: Final[str] = "image/jpeg"
COVER_MEDIA_TYPE_PNG: Final[str] = "image/png"
COVER_VERSION_QUERY: Final[str] = "v"
COVER_CACHE_CONTROL: Final[str] = "no-store"
COVER_UNSUPPORTED_TYPE: Final[str] = "Cover must be a JPEG or PNG image"
COVER_TOO_LARGE: Final[str] = "Cover file is too large"
COVER_TOO_MANY_PIXELS: Final[str] = "Cover image is too large"
COVER_UNREADABLE: Final[str] = "Cover image could not be read"
COVER_NOT_FOUND: Final[str] = "Cover not found"
COVER_VARIANT_UNKNOWN: Final[str] = "Unknown cover variant"
COVER_INVALID_ALBUM_ID: Final[str] = "Invalid album id for cover storage"
COVER_INVALID_SONG_ID: Final[str] = "Invalid song id for cover storage"
COVER_OLD_DIRNAME_SUFFIX: Final[str] = ".old"
COVER_STAGING_DIRNAME_SUFFIX: Final[str] = ".staging"

# User LoRA training
USER_LORAS_DIRNAME: Final[str] = "user_loras"
USER_LORA_SAMPLES_DIRNAME: Final[str] = "samples"
USER_LORA_DATASET_DIRNAME: Final[str] = "dataset"
USER_LORA_OUTPUT_DIRNAME: Final[str] = "lora"
USER_LORA_SAMPLE_MAX_BYTES: Final[int] = 50 * 1024 * 1024
USER_LORA_MAX_SAMPLES: Final[int] = 20
USER_LORA_MIN_SAMPLES_FOR_TRAINING: Final[int] = 3
USER_LORA_AUDIO_EXTENSIONS: Final[frozenset[str]] = frozenset({".wav", ".mp3", ".flac"})


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"
    CANCELLED = "cancelled"


JOB_ACTIVE_STATUSES = frozenset({JobStatus.QUEUED, JobStatus.RUNNING})
JOB_TERMINAL_STATUSES = frozenset({
    JobStatus.COMPLETED,
    JobStatus.FAILED,
    JobStatus.PARTIAL,
    JobStatus.CANCELLED,
})


class JobType(StrEnum):
    GENERATE = "generate"
    SCORE = "score"
    CHAT = "chat"
    LORA_TRAINING = "lora_training"


class JobFunction(StrEnum):
    GENERATE = "generate"
    SCORE = "score"
    LOAD_MODEL_ON_WORKER = "load_model_on_worker"
    DOWNLOAD_MODEL_ON_WORKER = "download_model_on_worker"
    LORA_TRAINING = "lora_training"


class ResourceType(StrEnum):
    SONG = "song"
    ALBUM = "album"
    GENERATION = "generation"
    VERSION = "version"
    PLAYLIST = "playlist"
    USER = "user"
    PRESET = "preset"
    MODEL = "model"
    DEFAULT_CONFIG = "default_config"
    CLAUDE_MODELS = "claude_models"
    COWRITER = "cowriter"
    JUDGE = "judge"
    RATE_LIMITS = "rate_limits"
    JOB = "job"
    SESSION = "session"
    LORA = "lora"


class ResourceEventKind(StrEnum):
    GENERATION_CREATED = "generation.created"


RESOURCE_EVENT_RETENTION_DAYS: Final = 30
RESOURCE_EVENT_CLEANUP_INTERVAL_SECONDS: Final = 60 * 60


class AuditAction(StrEnum):
    GENERATE = "generate"
    REPAINT = "repaint"
    COVER = "cover"
    SCORE = "score"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    RESTORE = "restore"
    ARCHIVE = "archive"
    UNARCHIVE = "unarchive"
    HARD_DELETE = "hard_delete"
    DEACTIVATE = "deactivate"
    CANCEL = "cancel"
    SHARE = "share"
    UNSHARE = "unshare"
    REMASTER = "remaster"
    MOVE = "move"
    CLEANUP = "cleanup"
    SESSION_IP_CHANGE = "session_ip_change"
    SESSION_UA_CHANGE = "session_ua_change"
    TRAIN_LORA = "train_lora"


class LoraStatus(StrEnum):
    DRAFT = "draft"
    QUEUED = "queued"
    PREPROCESSING = "preprocessing"
    TRAINING = "training"
    EXPORTING = "exporting"
    READY = "ready"
    FAILED = "failed"


LORA_ACTIVE_STATUSES: Final[frozenset[LoraStatus]] = frozenset({
    LoraStatus.QUEUED,
    LoraStatus.PREPROCESSING,
    LoraStatus.TRAINING,
    LoraStatus.EXPORTING,
})


class LimiterFailurePolicy(StrEnum):
    """Named fallback for when a rate/lease limiter's Redis backend errors.

    FAIL_OPEN lets the request through — used for public, unauthenticated
    endpoints (album/song/playlist share pages) where blocking real traffic
    on a transient Redis outage outweighs the abuse risk. FAIL_CLOSED
    rejects the request with 503 — used where an unenforced limit could let
    resource exhaustion through unbounded (queue-stream creation, the
    resource-event SSE stream's connection lease).
    """

    FAIL_OPEN = "fail_open"
    FAIL_CLOSED = "fail_closed"


# Env var names stripped from the environment of every child process this
# package spawns (currently the Claude CLI, in claude/provider.py). The
# acestep_worker package keeps an identical tuple of the same name in
# acestep_worker/constants.py — it cannot import this module (see
# CLAUDE.md "Engine packages are independent") — and
# tests/test_secret_scrub_parity.py pins the two as equal sets.
#
# ADMIN_USERNAME / ADMIN_PASSWORD: compose sets the bootstrap admin
# credentials on the long-running web container, not just for a one-shot
# setup step — lifecycle.auto_setup_admin re-reads them on every startup so
# a restored-from-empty database gets its admin back. They therefore sit in
# the parent environment for the container's whole life, and this scrub is
# the only thing keeping them out of every child process it spawns.
#
# A login is scrubbed as a pair. The name half is no secret on its own, but
# handing a child process one half of a credential is pointless generosity —
# hence POSTGRES_USER and GRAFANA_USER beside their passwords. Every key here
# is a declared Settings field, so a process started from an exported .env
# really does carry it in os.environ.
SECRET_ENV_KEYS: Final[tuple[str, ...]] = (
    "ANTHROPIC_API_KEY",
    "XAI_API_KEY",
    "OPENAI_API_KEY",
    "SESSION_SECRET",
    "SONGMAKER_INTERNAL_TOKEN",
    "DATABASE_URL",
    "REDIS_URL",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "HF_TOKEN",
    "ADMIN_USERNAME",
    "ADMIN_PASSWORD",
    "GRAFANA_USER",
    "GRAFANA_PASSWORD",
)
