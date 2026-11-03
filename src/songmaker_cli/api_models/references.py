"""Reference recording API models: the upload list and its storage usage."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

from songmaker_cli.api_models.songs import ReferenceResponse

if TYPE_CHECKING:
    from songmaker_cli.db.models import ReferenceRecording
    from songmaker_cli.db.queries.reference_recordings import ReferenceUsage
    from songmaker_cli.settings import Settings


class ReferenceRecordingResponse(BaseModel):
    id: str
    filename: str
    size_bytes: int
    duration_sec: float | None
    created_at: str
    in_use: bool

    @classmethod
    def from_orm(
        cls, recording: ReferenceRecording, *, in_use: bool,
    ) -> ReferenceRecordingResponse:
        link = ReferenceResponse.from_orm(recording)
        return cls(
            id=link.id,
            filename=link.filename,
            size_bytes=recording.size_bytes,
            duration_sec=recording.duration_sec,
            created_at=recording.created_at.isoformat(),
            in_use=in_use,
        )


class ReferenceUsageResponse(BaseModel):
    files: int
    bytes: int
    file_limit: int
    byte_limit: int

    @classmethod
    def from_orm(cls, usage: ReferenceUsage, settings: Settings) -> ReferenceUsageResponse:
        return cls(
            files=usage.files,
            bytes=usage.bytes,
            file_limit=settings.reference_audio_quota_files,
            byte_limit=settings.reference_audio_quota_bytes,
        )


class ReferenceListResponse(BaseModel):
    references: list[ReferenceRecordingResponse]
    usage: ReferenceUsageResponse
