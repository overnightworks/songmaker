"""Pydantic models for API requests and responses.

These define the exact contract between backend and frontend.
FastAPI auto-generates OpenAPI docs from these models.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ── Shared types ────────────────────────────────────────────────────


# generation_params and scores are dynamic dicts — not structured models.
# They contain varying keys depending on the ACE-Step model and scorer pipeline.
# Using dict[str, ...] | None keeps them flexible and matches the DB storage.


# ── Album ───────────────────────────────────────────────────────────


class AlbumResponse(BaseModel):
    id: str
    title: str
    artist: str
    subtitle: str = ""
    year: str = ""
    colors: dict[str, str] = Field(default_factory=dict)
    song_count: int = 0


# ── Generation ──────────────────────────────────────────────────────


class GenerationResponse(BaseModel):
    id: str
    song_id: str
    version_id: str | None
    version_number: int | None
    generation_number: int
    mp3_path: str
    seed: int | None
    status: str
    is_archived: bool
    is_picked: bool
    whisper_text: str | None
    scores: dict | None
    generation_params: dict | None
    created_at: str | None


# ── Version ─────────────────────────────────────────────────────────


class VersionResponse(BaseModel):
    id: str
    version_number: int
    lyrics: str
    prompt: str
    bpm: int
    duration: int
    key: str
    generation_params: dict | None
    created_at: str | None


# ── Song ────────────────────────────────────────────────────────────


class SongResponse(BaseModel):
    id: str
    title: str
    album_id: str
    album_title: str = ""
    artist: str = ""
    track_number: int
    language: str = ""
    lyrics: str = ""
    prompt: str = ""
    bpm: int = 0
    duration: int = 180
    key: str = ""
    generation_params: dict | None = None
    version_count: int = 0
    generation_count: int = 0
    best_scores: dict | None = None
    best_rating: float | None = None
    generations: list[GenerationResponse] = Field(default_factory=list)
    created_at: str | None = None


# ── Job ─────────────────────────────────────────────────────────────


class JobResponse(BaseModel):
    id: str
    type: str
    status: str
    progress: float = 0.0
    error: str | None = None
    started_at: str | None = None
    completed_at: str | None = None


# ── Requests ────────────────────────────────────────────────────────


class SongCreateRequest(BaseModel):
    title: str
    album_id: str
    lyrics: str = ""
    prompt: str = ""
    bpm: int = 0
    duration: int = 180
    key: str = ""
    language: str = ""
    generation_params: dict | None = None


class SongUpdateRequest(BaseModel):
    lyrics: str | None = None
    prompt: str | None = None
    bpm: int | None = None
    duration: int | None = None
    key: str | None = None
    generation_params: dict | None = None


class GenerateRequest(BaseModel):
    count: int = Field(1, ge=1, le=10)


class ScoreRequest(BaseModel):
    scorers: list[str] | None = None


class RateRequest(BaseModel):
    rating: float = Field(ge=0, le=100)
    notes: str = ""


class GenerationDefaultsRequest(BaseModel):
    turbo: dict | None = None
    sft: dict | None = None


class ChatRequest(BaseModel):
    message: str
    system: str = ""
    context: str = ""


# ── Simple responses ────────────────────────────────────────────────


class StatusResponse(BaseModel):
    status: str = "ok"


class RateResponse(BaseModel):
    status: str = "ok"
    generation_id: str | None = None
    generation: str | None = None
    rating: float


class CleanupResponse(BaseModel):
    status: str = "ok"
    deleted: int


class CapabilitiesResponse(BaseModel):
    claude_api: bool
    claude_cli: bool
    generation: bool
    scoring: bool


class ChatResponse(BaseModel):
    response: str
