"""Non-model constants for the songmaker CLI."""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from acestep_engine.constants import MODEL_CONFIG_PATHS as MODEL_CONFIG_PATHS

APP_NAME = "Hallucinai"

INTERNAL_TOKEN_HEADER = "X-Internal-Token"  # noqa: S105 - the name of an HTTP header and no secret

JOB_ERROR_AUDIO_DOWNLOAD_FAILED: Final[str] = "Failed to download generated audio"
JOB_ERROR_SERVER_UNREACHABLE: Final[str] = "ACE-Step server not reachable"
JOB_ERROR_GENERATION_TIMED_OUT: Final[str] = "Generation timed out"
JOB_ERROR_NO_WORKERS: Final[str] = "No ACE-Step workers available"
JOB_ERROR_GENERATION_UNAVAILABLE: Final[str] = "Generating isn't available right now."
JOB_ERROR_GPU_OUT_OF_MEMORY: Final[str] = (
    "Too long for the GPU right now — try a shorter duration."
)
JOB_ERROR_GENERATION_FAILED: Final[str] = "Generating failed — try again."
JOB_ERROR_WORKER_TRAINING_FAILED: Final[str] = "Worker training failed"
JOB_ERROR_WORKER_STREAM_SILENT: Final[str] = "Worker stream went silent"
JOB_ERROR_INTERNAL: Final[str] = "Internal error during processing"
JOB_ERROR_UNEXPECTED: Final[str] = "An unexpected error occurred"
JOB_ERROR_SONG_NOT_FOUND: Final[str] = "Song not found"
JOB_ERROR_VERSION_NOT_FOUND: Final[str] = "Version not found"
JOB_ERROR_REFERENCE_AUDIO_NOT_FOUND: Final[str] = "Reference audio not found"
JOB_ERROR_USER_LORA_UNAVAILABLE: Final[str] = "Selected voice is unavailable for this generation"
HTTP_NOT_FOUND: Final[str] = "Not Found"
AUDIO_FILE_NOT_FOUND: Final[str] = "Audio file not found"
JOB_ERROR_GENERATION_CANCELLED: Final[str] = (
    "Job cancelled: exceeded ARQ_JOB_TIMEOUT or worker shutdown"
)

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
LORA_TRAINING_MODEL_MODES: Final[frozenset[str]] = frozenset({"sft", "turbo"})

GENERATION_WAITING_FOR_LORA_QUEUE_REASON: Final[str] = "Waiting for LoRA training on this GPU."
GENERATION_ETA_MIN_PROGRESS: Final[float] = 0.05
# 0 asks ACE-Step to choose the song length.
AUTO_LENGTH_SECONDS: Final[int] = 0
LORA_WAITING_FOR_GENERATION_QUEUE_REASON: Final[str] = "Waiting for queued generations on this GPU."

DEFAULT_ARTIST = "Flex0r"

# Pagination defaults and limits
PAGE_DEFAULT_LIMIT = 50
PAGE_MAX_LIMIT = 200

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
LIBRARY_ITEM_PLAYLIST: Final[str] = "playlist"
LIBRARY_CURSOR_VERSION: Final[int] = 1
LIBRARY_CURSOR_KEY_VERSION: Final[str] = "v"
LIBRARY_CURSOR_KEY_Q: Final[str] = "q"
LIBRARY_CURSOR_KEY_SORT: Final[str] = "sort"
LIBRARY_CURSOR_KEY_TYPE: Final[str] = "type"
LIBRARY_CURSOR_KEY_SORT_VALUE: Final[str] = "sort_value"
LIBRARY_CURSOR_KEY_ID: Final[str] = "id"
LIKE_ESCAPE_CHAR: Final[str] = "\\"


class SongWorkKind(StrEnum):
    """The kind of a person's own work on a song.

    An edit recorded before kinds existed has none and reads as ``EDITED``.
    """

    CREATED = "created"
    LYRICS = "lyrics"
    STYLE = "style"
    RENAMED = "renamed"
    TAKE = "take"
    COWRITER = "cowriter"
    EDITED = "edited"


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

SETTING_REFERENCE_COUNTDOWN_VISIBLE_SINCE: Final = "reference_countdown_visible_since"
SETTING_COWRITER_TAIL_TOKEN_BUDGET = "cowriter_tail_token_budget"  # noqa: S105 - a setting key for an LLM token budget and no secret

MEMORY_SCOPE_USER = "user"
MEMORY_SCOPE_SONG = "song"
MEMORY_SCOPE_ALBUM = "album"
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

GET_SONG_ONLY_FOR_OTHER_SONGS = (
    "Call get_song only for other songs, or for the current song after you "
    "changed it yourself in this turn."
)
GET_SONG_TOOL_DESCRIPTION = (
    "Read the full state of a song: current draft lyrics/prompt/style, "
    f"version history, and generation ids. {GET_SONG_ONLY_FOR_OTHER_SONGS}"
)
CURRENT_SONG_FRESHNESS_NOTE = (
    "The current_song block below is this song's saved state as of this turn; "
    "fields it does not show are not set."
)

COWRITER_DEFAULT_TAIL_TOKEN_BUDGET = 24_000
COWRITER_MIN_TAIL_TOKEN_BUDGET = 2_000
COWRITER_MAX_TAIL_TOKEN_BUDGET = 100_000

COWRITER_SUMMARY_TAG = "conversation_summary"
COWRITER_MAX_SUMMARY_CHARS = 12_000

# Whisper hallucination detection
HALLUCINATION_MIN_LINES = 5
HALLUCINATION_MAX_UNIQUE = 2
HALLUCINATION_PHRASE_RATIO = 0.5

SHARING_RATE_LIMIT = 60
SHARING_RATE_WINDOW_SECONDS = 60
SHARING_STREAM_RATE_LIMIT = 6
SHARING_STREAM_RATE_WINDOW_SECONDS = 60
QUEUE_STREAM_AUTH_RATE_LIMIT = 12
QUEUE_STREAM_AUTH_RATE_WINDOW_SECONDS = 60

# Redis key prefixes
REDIS_KEY_PREFIX = "songmaker"
REDIS_METRICS_HTTP_KEY = f"{REDIS_KEY_PREFIX}:metrics:http"
REDIS_METRICS_DURATION_KEY = f"{REDIS_KEY_PREFIX}:metrics:http:duration"
REDIS_METRICS_TOTAL_KEY = f"{REDIS_KEY_PREFIX}:metrics:http:total"
REDIS_RL_IP_PREFIX = "rl:ip"
REDIS_RL_SHARED_PREFIX = "rl:shared"
REDIS_RL_SHARED_STREAM_PREFIX = "rl:shared-stream"
REDIS_RL_QUEUE_STREAM_PREFIX = "rl:queue-stream"
SESSION_CLEANUP_INTERVAL_SECONDS = 300
REDIS_SOCKET_TIMEOUT_SECONDS: Final[float] = 2.0
STORE_STARTUP_WAIT_SECONDS: Final[int] = 300
STORE_STARTUP_RETRY_DELAY_SECONDS: Final[int] = 1
STORE_STARTUP_CONNECT_TIMEOUT_SECONDS: Final[int] = 3

# Session lifetime: seven days without a request, thirty days from sign-in at most.
SESSION_IDLE_SECONDS_DEFAULT: Final = 7 * 24 * 60 * 60
SESSION_ABSOLUTE_MAX_AGE_SECONDS_DEFAULT: Final = 30 * 24 * 60 * 60

# Sign-in through the Keycloak realm. The groups name who may sign in and who
# administers; the paths are the browser-visible routes of the contract.
OIDC_LOGIN_GROUP: Final = "/apps/songmaker"
OIDC_ADMIN_GROUP: Final = "/apps/songmaker/admin"
# A person's own agent reaches the MCP endpoint only with membership here.
OIDC_MCP_GROUP: Final = "/apps/songmaker/mcp"
OIDC_LEEWAY_SECONDS: Final = 30
OIDC_START_PATH: Final = "/login/oidc"
OIDC_CALLBACK_PATH: Final = "/auth/callback"
LOGOUT_PATH: Final = "/auth/logout"
SIGNED_OUT_PATH: Final = "/login"
NO_ACCESS_PATH: Final = "/no-access"

# How far back a job rate limit counts an account's earlier jobs.
RATE_LIMIT_WINDOW_SECONDS: Final = 3600

# Global generation defaults
PRESET_GLOBAL_DEFAULTS_NAME = "__global_defaults__"
VALID_BUILTIN_CONFIGS: Final[frozenset[str]] = frozenset({"sft", "turbo"})

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
RECOVERY_LOCK_TTL_SECONDS = 30
ARQ_MUSIC_QUEUE_NAME = "arq:queue:music"
ARQ_SCORING_QUEUE_NAME = "arq:queue:scoring"
ARQ_MUSIC_HEALTH_KEY = f"{ARQ_MUSIC_QUEUE_NAME}:health-check"
ARQ_SCORING_HEALTH_KEY = f"{ARQ_SCORING_QUEUE_NAME}:health-check"
ARQ_HEALTH_CHECK_INTERVAL_SECONDS: Final[int] = 30
WORKER_LAST_ALIVE_TTL_SECONDS: Final[int] = 7 * 24 * 60 * 60
RECOVERY_LOCK_MUSIC_KEY = f"{REDIS_KEY_PREFIX}:recovery_lock:music"
RECOVERY_LOCK_SCORING_KEY = f"{REDIS_KEY_PREFIX}:recovery_lock:scoring"

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
# Background loop health
BACKGROUND_LOOP_FAILURE_THRESHOLD: Final[int] = 3

# Rate limit setting keys (stored in rate_limit_settings table)
SETTING_GENERATION_RATE_LIMIT = "generation_rate_limit"
SETTING_SCORING_RATE_LIMIT = "scoring_rate_limit"
SETTING_MAX_QUEUE_DEPTH = "max_queue_depth"
SETTING_MAX_USER_ACTIVE_JOBS = "max_user_active_jobs"

# Response compression
GZIP_MINIMUM_SIZE_BYTES: Final[int] = 1024
# zlib's own default (6) trades ~0.5pp less reduction than level 9 for
# roughly a third of the CPU time on a typical ~24 KB whisper_cues JSON
# payload (measured: level 6 -> 3855 bytes / 0.25ms avg; level 9 -> 3728
# bytes / 0.70ms avg). Not worth the extra CPU per request for that.
GZIP_COMPRESS_LEVEL: Final[int] = 6

# SSE streaming
SSE_HEARTBEAT_SECONDS: Final[int] = 15
SSE_HEARTBEAT_COMMENT: Final[str] = ": heartbeat\n\n"
COVER_PROMPT_SONG_FIELD_MAX_CHARS: Final[int] = 500
COVER_PROMPT_MAX_CHARS: Final[int] = 6000
RESOURCE_EVENT_STREAM_PATH: Final[str] = "/api/resource-events/stream"
RESOURCE_EVENT_STREAM_CONNECTION_SECONDS: Final[int] = 60
RESOURCE_EVENT_STREAM_OPEN_WINDOW_SECONDS: Final[int] = 60

# Audio file serving
AUDIO_MEDIA_TYPES: dict[str, str] = {
    ".mp3": "audio/mpeg", ".wav": "audio/wav",
    ".flac": "audio/flac", ".ogg": "audio/ogg",
}

# Reference audio upload
REFERENCE_AUDIO_DIR = "refs"
REFERENCE_AUDIO_EXTENSIONS = frozenset(AUDIO_MEDIA_TYPES)
REFERENCE_AUDIO_MAX_BYTES = 50 * 1024 * 1024
JSON_REQUEST_BODY_MAX_BYTES = 1_048_576
MULTIPART_ENVELOPE_MAX_BYTES = 1_048_576
AUDIO_UPLOAD_FILE_MAX_BYTES = REFERENCE_AUDIO_MAX_BYTES
AUDIO_UPLOAD_BODY_MAX_BYTES = AUDIO_UPLOAD_FILE_MAX_BYTES + MULTIPART_ENVELOPE_MAX_BYTES

ALBUM_COVER_SUGGESTIONS_DIRNAME: Final[str] = "cover-suggestions"
COVER_MAX_BYTES: Final[int] = 8 * 1024 * 1024
COVER_UPLOAD_BODY_MAX_BYTES: Final[int] = COVER_MAX_BYTES + MULTIPART_ENVELOPE_MAX_BYTES
COVER_VARIANT_CARD: Final[str] = "card"
COVER_VARIANT_DETAIL: Final[str] = "detail"
COVER_VERSION_QUERY: Final[str] = "v"
COVER_NOT_FOUND: Final[str] = "Cover not found"

# User LoRA training
USER_LORAS_DIRNAME: Final[str] = "user_loras"
USER_LORA_SAMPLES_DIRNAME: Final[str] = "samples"
USER_LORA_DATASET_DIRNAME: Final[str] = "dataset"
USER_LORA_TRAINING_TMP_DIRNAME: Final[str] = "training_tmp"
USER_LORA_OUTPUT_DIRNAME: Final[str] = "lora"
USER_LORA_SAMPLE_MAX_BYTES: Final[int] = 50 * 1024 * 1024
USER_LORA_MAX_SAMPLES: Final[int] = 20
USER_LORA_MIN_SAMPLES_FOR_TRAINING: Final[int] = 3
USER_LORA_AUDIO_EXTENSIONS: Final[frozenset[str]] = frozenset({".wav", ".mp3", ".flac"})


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
    COWRITER = "cowriter"
    RATE_LIMITS = "rate_limits"
    JOB = "job"
    SESSION = "session"
    LORA = "lora"
    REFERENCE = "reference"


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
    CANCEL = "cancel"
    SHARE = "share"
    UNSHARE = "unshare"
    MOVE = "move"
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
# package spawns (the scoring subprocess, in scoring/subprocess_runner.py). The
# acestep_worker package keeps an identical tuple of the same name in
# acestep_worker/constants.py (it cannot import this module, see the
# independent-packages contract in .importlinter); the parity test pins them equal.
#
# A login is scrubbed as a pair. The name half is no secret on its own, but
# handing a child process one half of a credential is pointless generosity —
# hence POSTGRES_USER beside its password. Every key here
# is a declared Settings field, so a process started from an exported .env
# really does carry it in os.environ.
SECRET_ENV_KEYS: Final[tuple[str, ...]] = (
    "ANTHROPIC_API_KEY",
    "XAI_API_KEY",
    "OPENAI_API_KEY",
    "SESSION_SECRET",
    "SONGMAKER_INTERNAL_TOKEN",
    "SONGMAKER_MONITORING_TOKEN",
    "DATABASE_URL",
    "REDIS_URL",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "HF_TOKEN",
)
