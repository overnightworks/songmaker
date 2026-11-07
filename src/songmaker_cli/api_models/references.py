"""Reference recording API models: the upload list, its storage usage and where a file is used."""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING

from pydantic import BaseModel

from songmaker_cli.api_models.songs import ReferenceResponse

if TYPE_CHECKING:
    from songmaker_cli.db.models import ReferenceRecording
    from songmaker_cli.db.queries.reference_recordings import (
        ReferenceLinkCounts,
        ReferenceUsage,
        ReferenceUses,
    )
    from songmaker_cli.settings import Settings


class ReferenceRecordingResponse(BaseModel):
    id: str
    filename: str
    size_bytes: int
    duration_sec: float | None
    created_at: str
    in_use: bool
    is_kept: bool
    used_by_versions: int
    used_by_takes: int

    @classmethod
    def from_orm(
        cls, recording: ReferenceRecording, counts: ReferenceLinkCounts,
    ) -> ReferenceRecordingResponse:
        link = ReferenceResponse.from_orm(recording)
        return cls(
            id=link.id,
            filename=link.filename,
            size_bytes=recording.size_bytes,
            duration_sec=recording.duration_sec,
            created_at=recording.created_at.isoformat(),
            in_use=not counts.is_unlinked,
            is_kept=recording.is_kept,
            used_by_versions=counts.versions,
            used_by_takes=counts.takes,
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


class ReferenceVersionUseResponse(BaseModel):
    song_id: str
    song_title: str
    song_slug: str
    album_id: str
    version_number: int
    is_trashed: bool


class ReferenceTakeUseResponse(BaseModel):
    song_id: str
    song_title: str
    song_slug: str
    album_id: str
    generation_number: int
    version_number: int | None
    is_archived: bool
    is_trashed: bool
    audio_duration_sec: float | None


class ReferenceUsesResponse(BaseModel):
    versions: list[ReferenceVersionUseResponse]
    takes: list[ReferenceTakeUseResponse]

    @classmethod
    def from_orm(cls, uses: ReferenceUses) -> ReferenceUsesResponse:
        return cls(
            versions=[ReferenceVersionUseResponse(**asdict(use)) for use in uses.versions],
            takes=[ReferenceTakeUseResponse(**asdict(use)) for use in uses.takes],
        )


class ReferenceListResponse(BaseModel):
    references: list[ReferenceRecordingResponse]
    usage: ReferenceUsageResponse
