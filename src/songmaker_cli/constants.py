"""Non-model constants for the songmaker CLI."""

from __future__ import annotations

DATA_ROOT = "data"
AUDIO_ROOT = "data/audio"
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
ACESTEP_DEFAULT_VRAM_GB = "18"

# Whisper hallucination detection
HALLUCINATION_MIN_LINES = 5
HALLUCINATION_MAX_UNIQUE = 2
HALLUCINATION_PHRASE_RATIO = 0.5

# Sharing
SHARED_RATE_LIMIT = 60
SHARED_RATE_WINDOW_SECONDS = 60

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

# Session
MAX_USER_AGENT_LENGTH = 500

# Global generation defaults
GLOBAL_DEFAULTS_PRESET_NAME = "__global_defaults__"

# ACE-Step server
ACESTEP_PORT = 8001
ACESTEP_HEALTH_URL_TEMPLATE = "http://localhost:{port}/health"
ACESTEP_STARTUP_TIMEOUT_SECONDS = 120

# arq worker
ARQ_QUEUE_KEY = "arq:queue"
ACTIVE_MODEL_REDIS_KEY = "songmaker:active_model"
ARQ_HEALTH_KEY_PATTERN = "arq:worker:*"

# Audio file serving
AUDIO_MEDIA_TYPES: dict[str, str] = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
}
