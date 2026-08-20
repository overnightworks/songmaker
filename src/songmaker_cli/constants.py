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
SETTING_COWRITER_PROVIDER = "cowriter_provider"
SETTING_COWRITER_MODEL = "cowriter_model"
SETTING_COWRITER_TAIL_TOKEN_BUDGET = "cowriter_tail_token_budget"

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
COWRITER_SUMMARY_TAG = "conversation_summary"
COWRITER_MAX_SUMMARY_CHARS = 12_000

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

# Redis key prefixes
REDIS_KEY_PREFIX = "songmaker"
REDIS_METRICS_HTTP_KEY = f"{REDIS_KEY_PREFIX}:metrics:http"
REDIS_METRICS_DURATION_KEY = f"{REDIS_KEY_PREFIX}:metrics:http:duration"
REDIS_METRICS_TOTAL_KEY = f"{REDIS_KEY_PREFIX}:metrics:http:total"
REDIS_RL_IP_PREFIX = "rl:ip"
REDIS_RL_SHARED_PREFIX = "rl:shared"
REDIS_RL_SHARED_STREAM_PREFIX = "rl:shared-stream"
REDIS_RL_QUEUE_STREAM_PREFIX = "rl:queue-stream"
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
    RATE_LIMITS = "rate_limits"
    JOB = "job"
    SESSION = "session"
    LORA = "lora"


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
