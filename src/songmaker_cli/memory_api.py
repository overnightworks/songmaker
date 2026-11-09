"""Durable user, song and album notes of the co-writer.

- ``GET /memory`` — the user's notes, plus the song's and its album's when ``song_id`` is given.
- ``PUT /memory/user`` / ``/memory/songs/{id}`` / ``/memory/albums/{id}`` — replace one note.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from webauth.ports import AuthenticatedUser

from songmaker_cli.api_helpers import check_album_access, check_song_access
from songmaker_cli.api_models import (
    MemoryBundleResponse,
    MemoryScopeResponse,
    MemoryUpdateRequest,
)
from songmaker_cli.app_context import get_db_session
from songmaker_cli.auth_dependencies import get_current_user
from songmaker_cli.constants import MEMORY_SCOPE_ALBUM, MEMORY_SCOPE_SONG, MEMORY_SCOPE_USER
from songmaker_cli.db.models import CowriterAlbumMemory, CowriterSongMemory, CowriterUserMemory
from songmaker_cli.db.queries.albums import get_album
from songmaker_cli.db.queries.memory import (
    get_album_memory,
    get_song_memory,
    get_user_memory,
    upsert_album_memory,
    upsert_song_memory,
    upsert_user_memory,
)

router = APIRouter()

MemoryRow = CowriterUserMemory | CowriterSongMemory | CowriterAlbumMemory


def _store_note(
    session: Session,
    scope: str,
    scope_id: str,
    upsert: Callable[[Session, str, str], MemoryRow],
    body: str,
) -> MemoryScopeResponse:
    row = upsert(session, scope_id, body)
    session.commit()
    return MemoryScopeResponse.from_orm(scope, scope_id, row)


@router.get("/memory")
def api_get_memory(
    song_id: str | None = None,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> MemoryBundleResponse:
    user_row = get_user_memory(session, user.id)
    bundle = MemoryBundleResponse(
        user=MemoryScopeResponse.from_orm(MEMORY_SCOPE_USER, user.id, user_row),
    )
    if song_id is None:
        return bundle
    song = check_song_access(session, song_id, user)
    song_row = get_song_memory(session, song.id)
    album_row = get_album_memory(session, song.album_id)
    return MemoryBundleResponse(
        user=bundle.user,
        song=MemoryScopeResponse.from_orm(MEMORY_SCOPE_SONG, song.id, song_row),
        album=MemoryScopeResponse.from_orm(
            MEMORY_SCOPE_ALBUM,
            song.album_id,
            album_row,
        ),
    )


@router.put("/memory/user")
def api_put_user_memory(
    req: MemoryUpdateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> MemoryScopeResponse:
    return _store_note(session, MEMORY_SCOPE_USER, user.id, upsert_user_memory, req.body)


@router.put("/memory/songs/{song_id}")
def api_put_song_memory(
    song_id: str,
    req: MemoryUpdateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> MemoryScopeResponse:
    check_song_access(session, song_id, user)
    return _store_note(session, MEMORY_SCOPE_SONG, song_id, upsert_song_memory, req.body)


@router.put("/memory/albums/{album_id}")
def api_put_album_memory(
    album_id: str,
    req: MemoryUpdateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> MemoryScopeResponse:
    check_album_access(get_album(session, album_id), user)
    return _store_note(session, MEMORY_SCOPE_ALBUM, album_id, upsert_album_memory, req.body)
