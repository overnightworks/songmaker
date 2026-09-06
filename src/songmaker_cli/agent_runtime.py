"""Songmaker's one owner of the agent-provider runtime configuration.

``agent_providers`` refuses to run until a host installs its deployment facts
(see ``agent_providers.config``). This module is where songmaker states them:
the container's credential mirrors and mounted Codex resources, the Claude
chat model, the API keys, the Codex process caps, and the MCP server a
co-writer turn attaches. Every process that can reach a provider calls
:func:`configure_agent_providers` at startup — the web application in
``server.create_app`` and both arq workers in
``worker_base.WorkerBase.on_startup``, since neither worker runs a lifespan.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Final

from agent_providers.config import ProviderRuntimeConfig, configure
from songmaker_cli.constants import (
    CLAUDE_CLI_BINARY,
    CLI_PROMPT_FILE_PREFIX,
    CODEX_CLI_AUTH_FILE,
    CODEX_CLI_BINARY,
    CODEX_CODE_MODE_HOST_BINARY,
    CODEX_RESOURCES_DIRECTORY,
    GROK_CLI_AUTH_FILE,
    GROK_CLI_BINARY,
    GROK_CLI_PROMPT_FILE_PLACEHOLDER,
    SECRET_ENV_KEYS,
)
from songmaker_cli.cowriter.mcp_spec import songmaker_mcp_server
from songmaker_cli.settings import Settings

GROK_CLI_SESSION_ROOT: Final = Path.home() / ".grok" / "sessions"

# A developer machine often has no `claude` on PATH but does have the VS Code
# extension's bundled binary; the container has the binary on PATH and no
# extensions directory at all.
CLAUDE_CLI_VSCODE_BINARY_GLOB: Final = str(
    Path.home()
    / ".vscode"
    / "extensions"
    / "anthropic.claude-code-*"
    / "resources"
    / "native-binary"
    / CLAUDE_CLI_BINARY,
)


def configure_agent_providers(settings: Settings) -> None:
    """Install songmaker's deployment facts as the provider runtime."""
    configure(
        ProviderRuntimeConfig(
            claude_chat_model=settings.claude_chat_model,
            anthropic_api_key=settings.anthropic_api_key,
            xai_api_key=settings.xai_api_key,
            openai_api_key=settings.openai_api_key,
            claude_cli_binary=CLAUDE_CLI_BINARY,
            grok_cli_binary=GROK_CLI_BINARY,
            codex_cli_binary=CODEX_CLI_BINARY,
            claude_cli_binary_search_globs=(CLAUDE_CLI_VSCODE_BINARY_GLOB,),
            grok_cli_auth_file=Path(GROK_CLI_AUTH_FILE),
            grok_cli_session_root=GROK_CLI_SESSION_ROOT,
            codex_cli_auth_file=Path(CODEX_CLI_AUTH_FILE),
            codex_code_mode_host_binary=Path(CODEX_CODE_MODE_HOST_BINARY),
            codex_resources_directory=Path(CODEX_RESOURCES_DIRECTORY),
            codex_max_concurrent_processes=settings.codex_cli_max_concurrent_processes,
            codex_max_concurrent_image_runs=settings.cover_max_concurrent_runs,
            cli_working_directory_root=Path(tempfile.gettempdir()),
            cli_prompt_file_prefix=CLI_PROMPT_FILE_PREFIX,
            cli_prompt_file_placeholder=GROK_CLI_PROMPT_FILE_PLACEHOLDER,
            secret_env_keys=SECRET_ENV_KEYS,
            mcp_server=songmaker_mcp_server(settings.database_url),
        ),
    )
