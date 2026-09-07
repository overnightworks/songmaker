"""The co-writer MCP tool literal stays honest against the real server.

``cowriter/mcp_spec.py`` names songmaker's twelve MCP tools as a literal rather
than importing them from ``mcp_server.server`` (that would pull in the ``mcp``
package, which the scoring-worker container does not install — see CLAUDE.md).
This is the drift check that keeps the literal honest against the server's own
registration. It imports ``songmaker_cli`` and so belongs with songmaker, not
with the ``agent_providers`` library tests (issue #825).
"""

from __future__ import annotations

import asyncio

from songmaker_cli.cowriter.mcp_spec import MCP_TOOL_NAMES


def test_mcp_spec_tool_names_match_the_registered_mcp_server() -> None:
    """Set equality, so a tool that disappears fails as loudly as one that appears."""
    from songmaker_cli.mcp_server.server import build_server

    server = build_server(session_factory=lambda: None)
    registered = asyncio.run(server.list_tools())
    registered_names = {tool.name for tool in registered}

    assert len(registered_names) == 12
    assert registered_names == MCP_TOOL_NAMES, (
        "the spec promises tools the server does not register, or the server "
        "registers tools the co-writer gate would refuse"
    )
