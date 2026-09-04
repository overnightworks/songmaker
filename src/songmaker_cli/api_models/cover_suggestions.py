"""API models for album cover suggestions."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from songmaker_cli.api_models.jobs import JobResponse


class CoverSuggestionSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suggestion_id: str = Field(min_length=1, max_length=36)


class CoverSuggestionResponse(BaseModel):
    id: str
    url: str

    @classmethod
    def from_orm(cls, suggestion) -> CoverSuggestionResponse:
        return cls(
            id=suggestion.id,
            url=(
                f"/api/albums/{suggestion.album_id}/cover-suggestions/"
                f"{suggestion.id}"
            ),
        )


class CoverSuggestionsResponse(BaseModel):
    job: JobResponse | None = None
    suggestions: list[CoverSuggestionResponse]
    used_today: int
    daily_limit: int

    @classmethod
    def from_orm(
        cls,
        *,
        job,
        suggestions,
        used_today: int,
        daily_limit: int,
    ) -> CoverSuggestionsResponse:
        return cls(
            job=JobResponse.from_orm(job) if job else None,
            suggestions=[CoverSuggestionResponse.from_orm(item) for item in suggestions],
            used_today=used_today,
            daily_limit=daily_limit,
        )
