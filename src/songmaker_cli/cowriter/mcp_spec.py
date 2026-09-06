"""Songmaker's own MCP server, as the provider layer needs to see it.

Everything below is a literal rather than an import from
``songmaker_cli.mcp_server``: that package's ``__init__`` eagerly imports the
``mcp`` extra, which the scoring-worker container does not install even though
it runs tool-free Claude calls through the same provider module. This module
therefore lives outside ``mcp_server/`` and imports nothing from it, which
``tests/test_packaging_boundary.py`` pins. The literal cannot go stale
silently: ``tests/test_claude_provider.py``'s drift test compares
:data:`MCP_TOOL_NAMES` against the server's real registration, and fails on a
missing tool as loudly as on an extra one.
"""

from __future__ import annotations

import sys
from typing import Final

from pydantic import SecretStr

from agent_providers.config import McpServerSpec

MCP_SERVER_NAME: Final = "songmaker"
MCP_CONFIG_FILE_PREFIX: Final = "songmaker-mcp-"
MCP_USER_ID_ENVIRONMENT_VARIABLE: Final = "SONGMAKER_MCP_USER_ID"

MCP_TOOL_NAMES: Final[frozenset[str]] = frozenset({
    "list_albums",
    "list_songs",
    "search_songs",
    "get_song",
    "get_version",
    "get_generation",
    "create_song",
    "update_song_lyrics",
    "update_song_prompt",
    "update_song_style",
    "rename_song",
    "suggest_album_cover",
})

# The subprocess constructs the full application Settings, so every required
# field must be present even though an MCP tool call reads only the database.
_UNUSED_IN_MCP_SUBPROCESS: Final = "unused-in-mcp-subprocess"


def songmaker_mcp_server(database_url: str) -> McpServerSpec:
    """Declare songmaker's stdio MCP server for the provider layer."""
    return McpServerSpec(
        name=MCP_SERVER_NAME,
        command=sys.executable,
        args=("-m", "songmaker_cli.mcp_server"),
        environment={
            "DATABASE_URL": SecretStr(database_url),
            "REDIS_URL": SecretStr(_UNUSED_IN_MCP_SUBPROCESS),
            "SESSION_SECRET": SecretStr(_UNUSED_IN_MCP_SUBPROCESS),
            "SONGMAKER_INTERNAL_TOKEN": SecretStr(_UNUSED_IN_MCP_SUBPROCESS),
        },
        user_id_environment_variable=MCP_USER_ID_ENVIRONMENT_VARIABLE,
        config_file_prefix=MCP_CONFIG_FILE_PREFIX,
        tool_names=MCP_TOOL_NAMES,
    )
