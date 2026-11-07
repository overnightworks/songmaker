"""The ``agent`` settings section: the co-writer's gateway and the person's own agent client."""

from __future__ import annotations

from typing import Self

from agent_runtime_client.config import AgentConfig
from pydantic import Field, model_validator


class AgentSettings(AgentConfig):
    """The client's agent section plus what serves a person's own agent over MCP.

    ``mcp_client_id`` is the ``azp`` of the public client the person's agent signs in with and
    ``mcp_scope`` the one scope its token holds; both set turn the MCP endpoint on, neither set
    leaves it off, and one alone stops startup.
    """

    mcp_client_id: str | None = Field(None, min_length=1)
    mcp_scope: str | None = Field(None, min_length=1)

    @model_validator(mode="after")
    def _mcp_values_are_set_together(self) -> Self:
        if (self.mcp_client_id is None) != (self.mcp_scope is None):
            raise ValueError("mcp_client_id and mcp_scope are set together or not at all")
        return self
