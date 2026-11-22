"""The ``agent`` settings section: the co-writer's gateway."""

from __future__ import annotations

from agents.config import AgentConfig

# The client's agent section as songmaker reads it; this leaf is the one settings module that
# imports the agents library.
AgentSettings = AgentConfig
