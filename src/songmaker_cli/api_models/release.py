"""The release a running image was built for."""

from __future__ import annotations

from pydantic import BaseModel

from songmaker_cli.settings import Settings


class ReleaseInfo(BaseModel):
    tag: str
    commit: str

    @classmethod
    def from_settings(cls, settings: Settings) -> ReleaseInfo:
        return cls(tag=settings.songmaker_release, commit=settings.songmaker_commit)
