"""MCP server that exposes songmaker tools to the Claude Code CLI.

The server runs as a stdio subprocess spawned by the Claude CLI via
``--mcp-config``. Each chat turn spawns a fresh subprocess; the subprocess
dies when the CLI call completes. The acting user's id is passed via the
``SONGMAKER_MCP_USER_ID`` environment variable — every tool call loads
the user from the DB, wraps it in ``AuthenticatedUser``, and runs the
existing ``check_*_access()`` ownership helpers before touching data.

Phase 1 (this module) exposes read + non-destructive write tools:
list albums, list/search songs, read song/version/generation, create
song, update lyrics/prompt/style, rename song. Delete/move/sharing
tools and the backend streaming layer land in later phases.
"""
from songmaker_cli.mcp_server.server import build_server

__all__ = ["build_server"]
