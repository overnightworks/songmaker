"""The provider layer's own mechanics: values that are the same everywhere.

A constant lives here when it describes how the agent CLIs and HTTP APIs
behave — how long a probe may take, how much of a CLI's output is read, which
words a login probe looks for, which endpoint a catalog is fetched from. Those
are facts about Claude, Codex and Grok, not about the host that runs them, so
every deployment holds the same value and none of them belongs in
:class:`~agent_providers.config.ProviderRuntimeConfig`.

Everything that *does* differ per deployment — binaries, credential mirrors,
mounted directories, models, keys, process caps — arrives through that
configuration instead, and product vocabulary (a host's defaults, its cover and
history rules, its user-facing texts) stays with the host. ``docs/architecture.md``
in songmaker carries the ruled Go/Stay table for that split (issue #856).
"""

from __future__ import annotations

from typing import Final

CLI_LOGIN_STATUS_CACHE_SECONDS = 30
# Agent CLI login probes return only a few hundred bytes. These bounds keep a
# broken mounted binary from holding a request or its memory indefinitely.
CLI_OUTPUT_READ_LIMIT_BYTES = 64 * 1024
CLI_TERMINATION_GRACE_SECONDS = 1

COWRITER_CLI_TIMEOUT_SECONDS = 600
COWRITER_MODELS_TIMEOUT_SECONDS = 15
COWRITER_CLAUDE_API_MAX_TOKENS = 4_096
COWRITER_GROK_CLI_LINE_CHANNEL_CAPACITY = 64

# The real init event measured 0.34s (see docs/security.md); these budgets
# keep a wide margin over that without letting a stuck probe block a request
# for anywhere near as long as the old 30s did.
CLAUDE_CLI_TOOL_SURFACE_TIMEOUT_SECONDS = 10
CLAUDE_CLI_NO_TOOL_SURFACE_TIMEOUT_SECONDS = 5
CLAUDE_CLI_COMPLETION_TIMEOUT_SECONDS = 120
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
# A hard ceiling on all Claude CLI processes: live turns, probes, and processes
# that are still waiting for a background reaper. A zombie storm deliberately
# degrades to refusing new work (fail-closed), rather than growing without bound.
CLAUDE_CLI_MAX_CONCURRENT_PROCESSES = 8

# A judge timeout has one stable reason across its provider's own bound and
# the outer watchdog, so callers need not infer it from incidental prose.
JUDGE_FAILURE_TIMEOUT: Final[str] = "judge_timeout"

COWRITER_PROVIDERS: Final[frozenset[str]] = frozenset({"claude", "grok", "codex"})

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

CLAUDE_CLI_STATUS_ARGS: Final[tuple[str, ...]] = ("auth", "status")
CLAUDE_CLI_LOGGED_IN_FIELD: Final[str] = "loggedIn"
CLAUDE_CLI_AUTH_METHOD_FIELD: Final[str] = "authMethod"
GROK_CLI_STREAMING_OUTPUT_FORMAT: Final[str] = "streaming-json"
GROK_CLI_STATUS_ARGS: Final[tuple[str, ...]] = ("models",)
GROK_CLI_LOGGED_IN_MARKER: Final[str] = "You are logged in with "
GROK_CLI_LOGGED_OUT_MARKER: Final[str] = "You are not authenticated."
GROK_CLI_MODEL_LIST_MARKER: Final[str] = "Available models:"
GROK_CLI_MODEL_BULLETS: Final[tuple[str, ...]] = ("* ", "- ")
CODEX_CLI_STATUS_ARGS: Final[tuple[str, ...]] = ("login", "status")
CODEX_CLI_MODELS_ARGS: Final[tuple[str, ...]] = ("debug", "models")
CODEX_CLI_LOGGED_IN_MARKER: Final[str] = "Logged in using "
CODEX_CLI_LOGGED_OUT_MARKER: Final[str] = "Not logged in"
