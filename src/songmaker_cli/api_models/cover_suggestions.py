"""API models for album cover suggestions."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from songmaker_cli.api_models.jobs import JobResponse
from songmaker_cli.api_models.settings import AgentProblem


class CoverSuggestionSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suggestion_id: str = Field(min_length=1, max_length=36)


class CoverSuggestionRefusal(BaseModel):
    """Why Suggest was refused at the click, under the error body's ``detail``."""

    problem: AgentProblem


class CoverSuggestionUnavailableBody(BaseModel):
    """The 503 body of a Suggest the gateway or the realm cannot serve now."""

    detail: CoverSuggestionRefusal


class CoverSuggestionForbiddenBody(BaseModel):
    """The 403 body: why the person may not suggest, or a sentence for a caller without a login."""

    detail: CoverSuggestionRefusal | str


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

    @classmethod
    def from_orm(cls, *, job, suggestions) -> CoverSuggestionsResponse:
        return cls(
            job=JobResponse.from_orm(job) if job else None,
            suggestions=[CoverSuggestionResponse.from_orm(item) for item in suggestions],
        )
