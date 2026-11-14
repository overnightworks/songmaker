"""API models for a refusal that carries a catalog key beside its sentence."""

from __future__ import annotations

from pydantic import BaseModel

from songmaker_cli.messages import Message


class RefusalResponse(BaseModel):
    """The body of a refusal: the English sentence for agents, and the message for the page."""

    detail: str
    message: Message
