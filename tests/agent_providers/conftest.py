"""Autouse fixtures for the ``agent_providers`` library tests.

The root ``tests/conftest.py`` installs *songmaker's* provider runtime and its
probe patches for every test. This package overrides those with library-only
facts so the tests here prove the provider layer against values the package
owns, never the application's — which is what lets them travel to the extracted
``agent_providers`` repository (issue #825, S1) with no ``songmaker_cli`` on the
path.

``_configure_agent_provider_runtime`` is overridden *by name*: pytest uses the
nearest fixture of a given name, so this one runs and the root fixture does
not. That matters because ``agent_providers.config.configure()`` refuses a
second, differing installation — if both ran, the first to win would make the
other raise, and every test here would error.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from provider_test_support import MCP_TOOL_NAMES, SECRET_ENV_KEYS, close_fake_cli_pipes

from agent_providers.config import (
    McpServerSpec,
    ProviderRuntimeConfig,
    configure,
    reset_config,
)

_SAMPLE_ROOT = Path("/tmp/agent-providers-tests")

_SAMPLE_MCP_SERVER = McpServerSpec(
    name="songmaker",
    command="/usr/bin/python3",
    args=("-m", "songmaker_mcp_server"),
    user_id_environment_variable="SONGMAKER_MCP_USER_ID",
    config_file_prefix="songmaker-mcp-",
    tool_names=MCP_TOOL_NAMES,
)

_SAMPLE_RUNTIME = ProviderRuntimeConfig(
    claude_chat_model="claude-test-model",
    claude_cli_binary="claude",
    grok_cli_binary="grok",
    codex_cli_binary="codex",
    grok_cli_auth_file=_SAMPLE_ROOT / "grok" / "auth.json",
    grok_cli_session_root=_SAMPLE_ROOT / "grok" / "sessions",
    codex_cli_auth_file=_SAMPLE_ROOT / "codex" / "auth.json",
    codex_code_mode_host_binary=_SAMPLE_ROOT / "codex" / "code-mode-host",
    codex_resources_directory=_SAMPLE_ROOT / "codex" / "resources",
    codex_max_concurrent_processes=4,
    codex_max_concurrent_image_runs=2,
    cli_working_directory_root=Path(tempfile.gettempdir()),
    cli_prompt_file_prefix="agent-cli-prompt-",
    cli_prompt_file_placeholder="__PROMPT_FILE__",
    secret_env_keys=SECRET_ENV_KEYS,
    mcp_server=_SAMPLE_MCP_SERVER,
)


@pytest.fixture(autouse=True)
def _configure_agent_provider_runtime():
    """Install the library's own sample runtime for every test, then drop it."""
    configure(_SAMPLE_RUNTIME)
    yield
    reset_config()


@pytest.fixture(autouse=True)
def _isolate_codex_process_pool():
    """Keep each test independent of Codex CLI process reservations."""
    import agent_providers.codex.pool as pool_mod

    pool_mod._process_pool = None
    yield
    pool_mod._process_pool = None


@pytest.fixture(autouse=True)
def _no_claude_cli_tool_surface_probe():
    """Never let a test spawn the real Claude CLI to read its tool surface."""
    with (
        patch(
            "agent_providers.claude.provider.verify_cli_tool_surface", AsyncMock(),
        ),
        patch(
            "agent_providers.claude.provider.averify_no_builtin_cli_tools", AsyncMock(),
        ),
        patch(
            "agent_providers.claude.provider.verify_no_builtin_cli_tools", MagicMock(),
        ),
    ):
        yield


@pytest.fixture(scope="module", autouse=True)
def _close_fake_cli_pipes():
    """Close the pipe-backed fake Claude CLI streams after each test module."""
    yield
    close_fake_cli_pipes()
