"""Non-model constants for the songmaker CLI."""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from acestep_engine.constants import MODEL_CONFIG_PATHS as MODEL_CONFIG_PATHS

APP_NAME = "Hallucinai"

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

# Redis key prefixes
REDIS_KEY_PREFIX = "songmaker"
REDIS_METRICS_HTTP_KEY = f"{REDIS_KEY_PREFIX}:metrics:http"
REDIS_METRICS_DURATION_KEY = f"{REDIS_KEY_PREFIX}:metrics:http:duration"
REDIS_METRICS_TOTAL_KEY = f"{REDIS_KEY_PREFIX}:metrics:http:total"
REDIS_RL_IP_PREFIX = "rl:ip"
REDIS_RL_SHARED_PREFIX = "rl:shared"
REDIS_SESSION_PREFIX = f"{REDIS_KEY_PREFIX}:session"
REDIS_USER_SESSIONS_PREFIX = f"{REDIS_KEY_PREFIX}:user_sessions"
REDIS_SESSION_SYNC_INTERVAL_SECONDS = 300
REDIS_DEGRADED_THRESHOLD = 3

# Session
HTTP_MAX_USER_AGENT_LENGTH = 500

# Global generation defaults
PRESET_GLOBAL_DEFAULTS_NAME = "__global_defaults__"

# Shared tmp dir for repaint/cover source audio — must be on the audio
# volume so the acestep-worker container can read what the music-worker
# wrote (each container has its own /tmp).
WORKER_SHARED_TMP_DIRNAME = ".tmp"

# Scoring subprocess
SCORING_PIPELINE_TIMEOUT_SECONDS = 240

# arq worker
ARQ_QUEUE_KEY = "arq:queue"
ARQ_HEALTH_KEY = f"{ARQ_QUEUE_KEY}:health-check"
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
PROM_JOB_DURATION_SECONDS = "songmaker_job_duration_seconds"
PROM_QUEUE_DEPTH = "songmaker_queue_depth"
PROM_GPU_VRAM_MB = "songmaker_gpu_vram_megabytes"
PROM_ACESTEP_WORKERS_TOTAL = "songmaker_acestep_workers_total"
PROM_ACESTEP_WORKER_LOADED_MODELS = "songmaker_acestep_worker_loaded_models"
PROM_ACESTEP_WORKER_QUEUE_DEPTH = "songmaker_acestep_worker_queue_depth"
PROM_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"

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

# SSE streaming
SSE_POLL_INTERVAL_SECONDS = 1

# Audio file serving
AUDIO_MEDIA_TYPES: dict[str, str] = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
}

# Reference audio upload
REFERENCE_AUDIO_DIR = "refs"
REFERENCE_AUDIO_EXTENSIONS = frozenset({".mp3", ".wav", ".flac", ".ogg"})
REFERENCE_AUDIO_MAX_BYTES = 50 * 1024 * 1024


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
    RATE_LIMITS = "rate_limits"
    JOB = "job"
    SESSION = "session"


class AuditAction(StrEnum):
    GENERATE = "generate"
    REPAINT = "repaint"
    COVER = "cover"
    SCORE = "score"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    RESTORE = "restore"
    HARD_DELETE = "hard_delete"
    DEACTIVATE = "deactivate"
    CANCEL = "cancel"
    SHARE = "share"
    UNSHARE = "unshare"
    MOVE = "move"
    CLEANUP = "cleanup"
    SESSION_IP_CHANGE = "session_ip_change"
    SESSION_UA_CHANGE = "session_ua_change"
