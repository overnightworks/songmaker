"""User LoRA API request and response models."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from songmaker_cli.db.models import Generation, UserLora, UserLoraSample


class UserLoraCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class UserLoraSampleCreateRequest(BaseModel):
    caption: str = Field(min_length=1)
    lyrics: str = Field(min_length=1)
    position: int | None = Field(default=None, ge=0)


class UserLoraSampleFromGenerationRequest(BaseModel):
    generation_id: str = Field(min_length=1)


class UserLoraSamplePatchRequest(BaseModel):
    caption: str | None = None
    lyrics: str | None = None
    position: int | None = Field(default=None, ge=0)


class UserLoraSampleResponse(BaseModel):
    id: str
    user_lora_id: str
    audio_path: str
    caption: str
    lyrics: str
    position: int
    created_at: str
    updated_at: str

    @classmethod
    def from_orm(cls, sample: UserLoraSample) -> UserLoraSampleResponse:
        return cls(
            id=sample.id,
            user_lora_id=sample.user_lora_id,
            audio_path=sample.audio_path,
            caption=sample.caption,
            lyrics=sample.lyrics,
            position=sample.position,
            created_at=sample.created_at.isoformat(),
            updated_at=sample.updated_at.isoformat(),
        )


class UserLoraResponse(BaseModel):
    id: str
    user_id: str
    name: str
    slug: str
    status: str
    storage_path: str | None = None
    tensor_path: str | None = None
    training_job_id: str | None = None
    error: str | None = None
    created_at: str
    completed_at: str | None = None
    deleted_at: str | None = None
    samples: list[UserLoraSampleResponse] = Field(default_factory=list)

    @classmethod
    def from_orm(cls, lora: UserLora) -> UserLoraResponse:
        samples = sorted(lora.samples or [], key=lambda s: s.position)
        return cls(
            id=lora.id,
            user_id=lora.user_id,
            name=lora.name,
            slug=lora.slug,
            status=lora.status,
            storage_path=lora.storage_path,
            tensor_path=lora.tensor_path,
            training_job_id=lora.training_job_id,
            error=lora.error,
            created_at=lora.created_at.isoformat(),
            completed_at=lora.completed_at.isoformat() if lora.completed_at else None,
            deleted_at=lora.deleted_at.isoformat() if lora.deleted_at else None,
            samples=[UserLoraSampleResponse.from_orm(s) for s in samples],
        )


class UserLoraListResponse(BaseModel):
    loras: list[UserLoraResponse]


class OwnPlayableTakeResponse(BaseModel):
    generation_id: str
    song_title: str
    generation_number: int
    audio_url: str
    caption: str
    lyrics: str

    @classmethod
    def from_orm(cls, generation: Generation) -> OwnPlayableTakeResponse:
        if generation.song is None or generation.version is None:
            raise ValueError("Playable take must include its song and version")
        return cls(
            generation_id=generation.id,
            song_title=generation.song.title,
            generation_number=generation.generation_number,
            audio_url=f"/audio/{generation.mp3_path}",
            caption=generation.version.prompt,
            lyrics=generation.version.lyrics,
        )


class OwnPlayableTakeListResponse(BaseModel):
    takes: list[OwnPlayableTakeResponse]
