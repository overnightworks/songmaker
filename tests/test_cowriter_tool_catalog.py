"""Songmaker's tool catalog is the port the provider layer renders and validates.

The prompt text below is a wire contract with every subscription-CLI model:
it is pinned byte for byte against the file the pre-library rendering wrote,
so moving the protocol into ``agent_providers`` cannot silently reword what a
model is told about songmaker's tools.
"""

from __future__ import annotations

from pathlib import Path

from agent_providers.text_tool_protocol import render_tool_catalog

from songmaker_cli.cowriter.mcp_spec import MCP_TOOL_NAMES
from songmaker_cli.cowriter.tools import (
    COWRITER_TOOL_CATALOG,
    COWRITER_TOOLS,
    execute_cowriter_tool,
)

SHIPPED_PROMPT = (
    Path(__file__).with_name("fixtures") / "cowriter_tool_catalog_prompt.txt"
).read_text(encoding="utf-8")


def test_the_rendered_catalog_is_byte_for_byte_the_prompt_that_shipped():
    assert render_tool_catalog(COWRITER_TOOL_CATALOG) == SHIPPED_PROMPT


def test_rendering_the_same_catalog_twice_produces_the_same_prompt():
    assert render_tool_catalog(COWRITER_TOOL_CATALOG) == render_tool_catalog(
        COWRITER_TOOL_CATALOG,
    )


def test_the_catalog_declares_every_canonical_tool_in_its_canonical_order():
    assert [tool.name for tool in COWRITER_TOOL_CATALOG.tools] == [
        tool.name for tool in COWRITER_TOOLS
    ]
    assert [tool.parameters for tool in COWRITER_TOOL_CATALOG.tools] == [
        tool.parameters for tool in COWRITER_TOOLS
    ]


def test_the_catalog_wears_the_songmaker_markers():
    assert COWRITER_TOOL_CATALOG.markup.call_open_tag == "<songmaker_tool_call>"


def test_the_co_writer_tools_are_exactly_the_mcp_server_tools():
    assert {tool.name for tool in COWRITER_TOOLS} == MCP_TOOL_NAMES


def test_executing_an_unknown_tool_is_a_refused_outcome_not_a_crash():
    outcome = execute_cowriter_tool(None, None, "delete_everything", {})

    assert outcome.is_error is True
    assert outcome.content == "Unknown tool: delete_everything"
