"""The ``agent`` settings section: the co-writer's gateway."""

from __future__ import annotations

from agents.config import ChatGateway
from pydantic import BaseModel, ConfigDict


class AgentSettings(BaseModel):
    """The gateway the co-writer talks to; its group is the realm's ``REALM_AI_GROUP``.

    An unknown key stops startup.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    gateway: ChatGateway
