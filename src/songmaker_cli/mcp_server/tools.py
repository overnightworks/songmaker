"""Songmaker MCP tool implementations.

Each function takes an open SQLAlchemy session + an ``AuthenticatedUser``
and returns a Pydantic model. Ownership is enforced through the
existing ``check_*_access()`` helpers; write tools delegate to the
existing domain queries so new versions, track numbering, and the
in-place update rule for un-generated versions all behave the same as
the HTTP endpoints.

The ``server.py`` layer wires these into FastMCP tools — opening
sessions, loading the user, committing writes. Keeping the logic in
pure functions makes everything directly unit-testable without
speaking the MCP protocol.
"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from songmaker_cli.api_helpers import (
    check_album_access,
    check_generation_access,
    check_song_access,
    owner_filter,
    unique_song_slug,
)
from songmaker_cli.cover_suggestions import (
    CoverSuggestionRequestError,
    request_cover_suggestions,
)
from songmaker_cli.db.models import Song
from songmaker_cli.db.queries.albums import get_album, list_albums
from songmaker_cli.db.queries.songs import (
    count_songs,
    list_songs,
)
from songmaker_cli.db.queries.songs import (
    create_song as db_create_song,
)
from songmaker_cli.db.queries.songs import (
    get_song as db_get_song,
)
from songmaker_cli.db.queries.songs import (
    rename_song as db_rename_song,
)
from songmaker_cli.db.queries.songs import (
    update_song as db_update_song,
)
from songmaker_cli.db.queries.versions import get_version
from songmaker_cli.mcp_server.schemas import (
    AlbumSummary,
    CoverSuggestionRequestResult,
    GenerationDetail,
    SongDetail,
    SongSummary,
    VersionSummary,
    WriteResult,
)
from songmaker_cli.middleware.auth import AuthenticatedUser

MAX_SEARCH_RESULTS = 50


class MCPToolError(RuntimeError):
    """Tool-level error, surfaced to Claude as the tool-call result."""


def _not_found(what: str) -> MCPToolError:
    return MCPToolError(f"{what} not found")


def _to_tool_error(exc: HTTPException) -> MCPToolError:
    return MCPToolError(str(exc.detail))


# ── Read tools ─────────────────────────────────────────────────────────


def tool_list_albums(session: Session, user: AuthenticatedUser) -> list[AlbumSummary]:
    albums = list_albums(session, user_id=owner_filter(user))
    return [
        AlbumSummary.from_orm_with_count(
            album, count_songs(session, album_id=album.id),
        )
        for album in albums
    ]


def tool_list_songs(
    session: Session, user: AuthenticatedUser, album_id: str | None = None,
) -> list[SongSummary]:
    if album_id is not None:
        album = get_album(session, album_id)
        try:
            check_album_access(album, user)
        except HTTPException as exc:
            raise _to_tool_error(exc) from exc
    songs = list_songs(
        session, album_id=album_id, user_id=owner_filter(user), light=True,
    )
    return [SongSummary.from_orm(s) for s in songs]


def tool_search_songs(
    session: Session, user: AuthenticatedUser, query: str, limit: int = 20,
) -> list[SongSummary]:
    if not query.strip():
        raise MCPToolError("search query cannot be empty")
    if limit < 1 or limit > MAX_SEARCH_RESULTS:
        raise MCPToolError(
            f"limit must be between 1 and {MAX_SEARCH_RESULTS}",
        )
    songs = list_songs(session, user_id=owner_filter(user), light=True)
    needle = query.strip().lower()
    matches = [s for s in songs if needle in s.title.lower()]
    return [SongSummary.from_orm(s) for s in matches[:limit]]


def tool_get_song(
    session: Session, user: AuthenticatedUser, song_id: str,
) -> SongDetail:
    try:
        song = check_song_access(session, song_id, user)
    except HTTPException as exc:
        raise _to_tool_error(exc) from exc
    return SongDetail.from_orm(song)


def tool_get_version(
    session: Session, user: AuthenticatedUser, song_id: str, version_id: str,
) -> VersionSummary:
    try:
        check_song_access(session, song_id, user)
    except HTTPException as exc:
        raise _to_tool_error(exc) from exc
    version = get_version(session, version_id, song_id)
    if version is None:
        raise _not_found(f"Version {version_id}")
    return VersionSummary.from_orm(version)


def tool_get_generation(
    session: Session, user: AuthenticatedUser, generation_id: str,
) -> GenerationDetail:
    try:
        gen = check_generation_access(session, generation_id, user)
    except HTTPException as exc:
        raise _to_tool_error(exc) from exc
    return GenerationDetail.from_orm(gen)


# ── Write tools ───────────────────────────────────────────────────────
#
# These delegate to existing DB queries. Co-writer content writes always use
# update_song()'s force_new_version path, while editor writes retain its draft
# editing behavior.


def tool_create_song(
    session: Session,
    user: AuthenticatedUser,
    album_id: str,
    title: str,
    lyrics: str = "",
    prompt: str = "",
) -> WriteResult:
    if not title.strip():
        raise MCPToolError("title cannot be empty")
    album = get_album(session, album_id)
    try:
        check_album_access(album, user)
    except HTTPException as exc:
        raise _to_tool_error(exc) from exc
    slug = unique_song_slug(session, album_id, title)
    song = db_create_song(
        session, title=title, album_id=album_id, lyrics=lyrics, prompt=prompt,
        slug=slug,
    )
    refreshed = _reload_song(session, song.id)
    return WriteResult(
        song_id=song.id,
        message=f"Created song '{title}' in album '{album.title}'",
        song=SongDetail.from_orm(refreshed),
    )


def tool_update_song_lyrics(
    session: Session, user: AuthenticatedUser, song_id: str, lyrics: str,
) -> WriteResult:
    try:
        check_song_access(session, song_id, user)
    except HTTPException as exc:
        raise _to_tool_error(exc) from exc
    version = db_update_song(
        session, song_id=song_id, lyrics=lyrics, force_new_version=True,
    )
    refreshed = _reload_song(session, song_id)
    return WriteResult(
        song_id=song_id,
        message=f"Updated lyrics in v{version.version_number}",
        song=SongDetail.from_orm(refreshed),
    )


def tool_update_song_prompt(
    session: Session, user: AuthenticatedUser, song_id: str, prompt: str,
) -> WriteResult:
    try:
        check_song_access(session, song_id, user)
    except HTTPException as exc:
        raise _to_tool_error(exc) from exc
    version = db_update_song(
        session, song_id=song_id, prompt=prompt, force_new_version=True,
    )
    refreshed = _reload_song(session, song_id)
    return WriteResult(
        song_id=song_id,
        message=f"Updated style prompt in v{version.version_number}",
        song=SongDetail.from_orm(refreshed),
    )


def tool_update_song_style(
    session: Session,
    user: AuthenticatedUser,
    song_id: str,
    bpm: int | None = None,
    key_scale: str | None = None,
    audio_duration: int | None = None,
) -> WriteResult:
    if bpm is None and key_scale is None and audio_duration is None:
        raise MCPToolError(
            "provide at least one of: bpm, key_scale, audio_duration",
        )
    try:
        check_song_access(session, song_id, user)
    except HTTPException as exc:
        raise _to_tool_error(exc) from exc
    version = db_update_song(
        session, song_id=song_id, bpm=bpm, key_scale=key_scale,
        audio_duration=audio_duration, force_new_version=True,
    )
    refreshed = _reload_song(session, song_id)
    parts = []
    if bpm is not None:
        parts.append(f"bpm={bpm}")
    if key_scale is not None:
        parts.append(f"key={key_scale}")
    if audio_duration is not None:
        parts.append(f"duration={audio_duration}s")
    return WriteResult(
        song_id=song_id,
        message=f"Updated style ({', '.join(parts)}) in v{version.version_number}",
        song=SongDetail.from_orm(refreshed),
    )


def tool_rename_song(
    session: Session, user: AuthenticatedUser, song_id: str, title: str,
) -> WriteResult:
    if not title.strip():
        raise MCPToolError("title cannot be empty")
    try:
        song = check_song_access(session, song_id, user)
    except HTTPException as exc:
        raise _to_tool_error(exc) from exc
    slug = unique_song_slug(session, song.album_id, title, exclude_song_id=song_id)
    db_rename_song(
        session, song_id=song_id, title=title, slug=slug, force_new_version=True,
    )
    refreshed = _reload_song(session, song_id)
    return WriteResult(
        song_id=song_id,
        message=(
            f"Renamed song to '{title}' in v{refreshed.latest_version.version_number}"
        ),
        song=SongDetail.from_orm(refreshed),
    )


def tool_suggest_album_cover(
    session: Session, user: AuthenticatedUser, album_id: str,
) -> CoverSuggestionRequestResult:
    """Queue three cover suggestions through the album admission owner."""
    try:
        request = request_cover_suggestions(session, album_id, user)
    except CoverSuggestionRequestError as exc:
        raise MCPToolError(str(exc)) from exc
    return CoverSuggestionRequestResult(
        job_id=request.job.id,
        status=request.job.status,
        message="Cover suggestions queued.",
    )


def _reload_song(session: Session, song_id: str) -> Song:
    session.flush()
    song = db_get_song(session, song_id)
    assert song is not None
    return song
