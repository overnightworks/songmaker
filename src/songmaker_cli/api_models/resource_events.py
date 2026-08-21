"""Wire models for the authenticated resource-event stream."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from songmaker_cli.constants import ResourceEventKind, ResourceType

if TYPE_CHECKING:
    from songmaker_cli.db.models import ResourceEvent

_DECIMAL_PATTERN = r"^(0|[1-9][0-9]*)$"


class ResourceHelloEvent(BaseModel):
    high_water_mark: str = Field(pattern=_DECIMAL_PATTERN)

    @classmethod
    def from_high_water_mark(cls, value: int) -> ResourceHelloEvent:
        return cls(high_water_mark=str(value))


class ResourceResyncEvent(BaseModel):
    high_water_mark: str = Field(pattern=_DECIMAL_PATTERN)

    @classmethod
    def from_high_water_mark(cls, value: int) -> ResourceResyncEvent:
        return cls(high_water_mark=str(value))


class GenerationCreatedResourceEvent(BaseModel):
    kind: Literal["generation.created"] = ResourceEventKind.GENERATION_CREATED
    sequence: str = Field(pattern=_DECIMAL_PATTERN)
    resource_type: Literal["song"] = ResourceType.SONG
    resource_id: str
    generation_id: str
    created_at: str

    @classmethod
    def from_event(cls, event: ResourceEvent) -> GenerationCreatedResourceEvent:
        return cls(
            sequence=str(event.sequence),
            resource_id=event.resource_id,
            generation_id=event.generation_id,
            created_at=event.created_at.isoformat(),
        )
