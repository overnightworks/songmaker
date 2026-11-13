"""API models for a refusal that carries a catalog key beside its sentence."""

from __future__ import annotations

from pydantic import BaseModel


class RefusalMessage(BaseModel):
    """The catalog key of a refusal and the values of its gaps, for a page that words it itself."""

    key: str
    values: dict[str, str]


class RefusalResponse(BaseModel):
    """The body of a refusal: the English sentence for agents, and the message for the page."""

    detail: str
    message: RefusalMessage
