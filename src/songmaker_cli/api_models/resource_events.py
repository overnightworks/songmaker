"""SSE payloads for the per-user resource event stream."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

from songmaker_cli.constants import (
    RESOURCE_EVENT_KIND_GENERATION_CREATED,
    RESOURCE_EVENT_TYPE_HEARTBEAT,
    RESOURCE_EVENT_TYPE_HELLO,
    RESOURCE_EVENT_TYPE_RESYNC,
    ResourceType,
)

if TYPE_CHECKING:
    from songmaker_cli.db.models import UserResourceEvent


class ResourceHelloEvent(BaseModel):
    type: Literal["hello"] = RESOURCE_EVENT_TYPE_HELLO
    high_water_mark: int


class ResourceResyncEvent(BaseModel):
    type: Literal["resync"] = RESOURCE_EVENT_TYPE_RESYNC
    high_water_mark: int


class ResourceHeartbeatEvent(BaseModel):
    type: Literal["heartbeat"] = RESOURCE_EVENT_TYPE_HEARTBEAT


class GenerationCreatedEvent(BaseModel):
    type: Literal["generation.created"] = RESOURCE_EVENT_KIND_GENERATION_CREATED
    kind: Literal["generation.created"] = RESOURCE_EVENT_KIND_GENERATION_CREATED
    sequence: int
    user_id: str
    resource_type: Literal["song"] = ResourceType.SONG
    resource_id: str
    song_id: str
    generation_id: str
    created_at: str

    @classmethod
    def from_orm(cls, event: UserResourceEvent) -> GenerationCreatedEvent:
        return cls(
            sequence=event.sequence,
            user_id=event.user_id,
            resource_id=event.song_id,
            song_id=event.song_id,
            generation_id=event.generation_id,
            created_at=event.created_at.isoformat(),
        )
