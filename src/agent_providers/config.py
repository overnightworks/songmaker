"""The runtime configuration a host application injects into the provider layer.

The provider layer runs Claude, Grok and Codex on someone else's machine: its
binaries, credential mirrors, mounted resource directories, chat model and API
keys are deployment facts the host owns, not values this package may guess. It
therefore reads them from one frozen value the host installs once per process
via :func:`configure`, instead of reaching into an application settings module.

Nothing is installed by default. :func:`current_config` raises
:class:`ProviderRuntimeNotConfiguredError` until the host has configured the
process, so a forgotten call fails loudly at the first provider turn rather
than silently running against a guessed path. :func:`reset_config` drops the
installation again — the test-suite counterpart of clearing a settings cache.

Self-contained by design: pydantic only, no application import, so the package
can be released on its own (issue #825).
"""

from __future__ import annotations

import threading
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class ProviderRuntimeConfig(BaseModel):
    """Every deployment fact the provider layer needs, as one immutable value."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claude_chat_model: str
    anthropic_api_key: SecretStr | None = None
    xai_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None

    claude_cli_binary: str
    grok_cli_binary: str
    codex_cli_binary: str
    claude_cli_binary_search_globs: tuple[str, ...] = ()

    grok_cli_auth_file: Path
    grok_cli_session_root: Path
    codex_cli_auth_file: Path
    codex_code_mode_host_binary: Path
    codex_resources_directory: Path

    codex_max_concurrent_processes: int = Field(ge=1)
    codex_max_concurrent_cover_runs: int = Field(ge=1)

    secret_env_keys: tuple[str, ...]


class ProviderRuntimeNotConfiguredError(RuntimeError):
    """A provider ran before its host installed a runtime configuration."""


_NOT_CONFIGURED_DETAIL = (
    "The agent-provider runtime is unconfigured. Call "
    "agent_providers.config.configure() during application startup."
)

_configured: ProviderRuntimeConfig | None = None
_configuration_lock = threading.Lock()


def configure(config: ProviderRuntimeConfig) -> None:
    """Install the host's configuration as this process's provider runtime."""
    global _configured
    with _configuration_lock:
        _configured = config


def current_config() -> ProviderRuntimeConfig:
    """Return the installed configuration, or refuse to run without one."""
    with _configuration_lock:
        config = _configured
    if config is None:
        raise ProviderRuntimeNotConfiguredError(_NOT_CONFIGURED_DETAIL)
    return config


def reset_config() -> None:
    """Drop the installed configuration so the next caller must configure again."""
    global _configured
    with _configuration_lock:
        _configured = None
