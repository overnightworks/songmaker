"""FastMCP server wiring — session/user plumbing around the tool functions.

Each FastMCP tool is a thin wrapper: open a DB session via the shared
session factory, resolve the acting user from env, delegate to the
corresponding ``tool_*`` function in ``tools.py``, commit writes, and
return the Pydantic result. All DB access and ownership checks live
in the underlying tool functions.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import TYPE_CHECKING

from mcp.server.fastmcp import FastMCP
from sqlalchemy.orm import sessionmaker

from songmaker_cli.mcp_server import auth, tools
from songmaker_cli.mcp_server.schemas import (
    AlbumSummary,
    GenerationDetail,
    SongDetail,
    SongSummary,
    VersionSummary,
    WriteResult,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

SERVER_NAME = "songmaker"
SERVER_INSTRUCTIONS = (
    "Songmaker tools for reading and editing the authenticated user's songs "
    "and albums. Read tools return full DB state; write tools commit "
    "immediately and return the resulting song state. Before each write, "
    "verbalize what you're about to change so the user can revert if needed."
)


def _default_factory() -> sessionmaker:
    from songmaker_cli.db.engine import init_db, resolve_database_url
    return init_db(resolve_database_url())


def build_server(
    session_factory: sessionmaker | None = None,
) -> FastMCP:
    """Construct the MCP server. Accepts an explicit session factory for tests."""
    resolved_factory: sessionmaker | None = session_factory

    def _get_factory() -> sessionmaker:
        nonlocal resolved_factory
        if resolved_factory is None:
            resolved_factory = _default_factory()
        return resolved_factory

    @contextmanager
    def session_scope(write: bool):
        session = _get_factory()()
        try:
            yield session
            if write:
                session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def resolved_user(session: Session):
        return auth.load_user(session, auth.require_user_id())

    mcp = FastMCP(
        name=SERVER_NAME,
        instructions=SERVER_INSTRUCTIONS,
    )

    # ── Read tools ────────────────────────────────────────────────────

    @mcp.tool(description="List all albums owned by the current user.")
    def list_albums() -> list[AlbumSummary]:
        with session_scope(write=False) as session:
            user = resolved_user(session)
            return tools.tool_list_albums(session, user)

    @mcp.tool(
        description=(
            "List songs. Without album_id, returns every song owned by "
            "the user; with album_id, only songs in that album."
        ),
    )
    def list_songs(album_id: str | None = None) -> list[SongSummary]:
        with session_scope(write=False) as session:
            user = resolved_user(session)
            return tools.tool_list_songs(session, user, album_id=album_id)

    @mcp.tool(
        description=(
            "Search songs by title substring (case-insensitive). "
            "Limit defaults to 20, max 50."
        ),
    )
    def search_songs(query: str, limit: int = 20) -> list[SongSummary]:
        with session_scope(write=False) as session:
            user = resolved_user(session)
            return tools.tool_search_songs(
                session, user, query=query, limit=limit,
            )

    @mcp.tool(
        description=(
            "Read the full state of a song: current draft lyrics/prompt/"
            "style, version history, and generation ids."
        ),
    )
    def get_song(song_id: str) -> SongDetail:
        with session_scope(write=False) as session:
            user = resolved_user(session)
            return tools.tool_get_song(session, user, song_id=song_id)

    @mcp.tool(description="Read a specific version snapshot of a song.")
    def get_version(song_id: str, version_id: str) -> VersionSummary:
        with session_scope(write=False) as session:
            user = resolved_user(session)
            return tools.tool_get_version(
                session, user, song_id=song_id, version_id=version_id,
            )

    @mcp.tool(
        description=(
            "Read a generation's metadata, scores, whisper transcript, "
            "and rating."
        ),
    )
    def get_generation(generation_id: str) -> GenerationDetail:
        with session_scope(write=False) as session:
            user = resolved_user(session)
            return tools.tool_get_generation(
                session, user, generation_id=generation_id,
            )

    # ── Write tools ───────────────────────────────────────────────────

    @mcp.tool(
        description=(
            "Create a new song in an album. Returns the new song's id "
            "and full state so Claude can switch focus to it."
        ),
    )
    def create_song(
        album_id: str, title: str, lyrics: str = "", prompt: str = "",
    ) -> WriteResult:
        with session_scope(write=True) as session:
            user = resolved_user(session)
            return tools.tool_create_song(
                session, user, album_id=album_id, title=title,
                lyrics=lyrics, prompt=prompt,
            )

    @mcp.tool(
        description=(
            "Replace the song's current lyrics. If the latest version "
            "has no generations yet, updates in place; otherwise creates "
            "a new version so audio stays traceable to its lyrics."
        ),
    )
    def update_song_lyrics(song_id: str, lyrics: str) -> WriteResult:
        with session_scope(write=True) as session:
            user = resolved_user(session)
            return tools.tool_update_song_lyrics(
                session, user, song_id=song_id, lyrics=lyrics,
            )

    @mcp.tool(description="Replace the song's current style prompt.")
    def update_song_prompt(song_id: str, prompt: str) -> WriteResult:
        with session_scope(write=True) as session:
            user = resolved_user(session)
            return tools.tool_update_song_prompt(
                session, user, song_id=song_id, prompt=prompt,
            )

    @mcp.tool(
        description=(
            "Update one or more musical style params: bpm, key_scale, "
            "audio_duration. Any omitted param keeps its current value."
        ),
    )
    def update_song_style(
        song_id: str,
        bpm: int | None = None,
        key_scale: str | None = None,
        audio_duration: int | None = None,
    ) -> WriteResult:
        with session_scope(write=True) as session:
            user = resolved_user(session)
            return tools.tool_update_song_style(
                session, user, song_id=song_id, bpm=bpm,
                key_scale=key_scale, audio_duration=audio_duration,
            )

    @mcp.tool(description="Rename a song's title.")
    def rename_song(song_id: str, title: str) -> WriteResult:
        with session_scope(write=True) as session:
            user = resolved_user(session)
            return tools.tool_rename_song(
                session, user, song_id=song_id, title=title,
            )

    return mcp


def main() -> None:
    """Stdio entrypoint — spawned by the Claude CLI via --mcp-config."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log.info("songmaker MCP server starting (stdio)")
    build_server().run(transport="stdio")
