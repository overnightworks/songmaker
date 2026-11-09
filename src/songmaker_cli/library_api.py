"""Personal library: search, Home's Listen and Write, and the library pool queue."""

from __future__ import annotations

from typing import Final

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from webauth.ports import AuthenticatedUser

from songmaker_cli.agent.mcp import ToolEffect, agent_tool
from songmaker_cli.api_helpers import (
    can_access_album,
    owner_filter,
    parse_required_search_query,
)
from songmaker_cli.api_models import (
    DEFAULT_LIBRARY_TAKE_POOL,
    LibraryListenResponse,
    LibraryPoolQueueResponse,
    LibrarySearchResponse,
    LibrarySort,
    LibraryTakePool,
    LibraryWriteResponse,
)
from songmaker_cli.app_context import AppContext, get_app_context, get_db_session
from songmaker_cli.auth_dependencies import get_current_user
from songmaker_cli.constants import (
    LIBRARY_CURSOR_INVALID,
    LIBRARY_CURSOR_MISMATCH,
    LIBRARY_SORT_NEWEST,
    PAGE_DEFAULT_LIMIT,
    PAGE_MAX_LIMIT,
)
from songmaker_cli.db.models import Album, Song
from songmaker_cli.db.queries.activity import list_place_listens, list_worked_songs
from songmaker_cli.db.queries.albums import (
    album_ids_with_playable_take,
    count_picked_songs_by_album,
    count_songs_by_album,
)
from songmaker_cli.db.queries.library import cursor_from_hit, search_library
from songmaker_cli.db.queries.songs import song_ids_with_pick
from songmaker_cli.library_cursor import (
    LibraryCursorInvalidError,
    LibraryCursorMismatchError,
    decode_library_cursor,
    encode_library_cursor,
)
from songmaker_cli.queue_streams import (
    check_queue_stream_rate_limit,
    resolve_library_pool_membership,
)

router = APIRouter()

LISTEN_DEFAULT_PLACES: Final[int] = 3
# Each Listen page re-reads every place before its window, so the offset is
# bounded far beyond any real library to keep one request's work finite.
LISTEN_MAX_OFFSET: Final[int] = 100_000
WRITE_SONGS: Final[int] = 3


_GET_LIBRARY_LISTEN_DESCRIPTION = (
    "Read the person's own library as places to listen to, paged with offset and limit."
)


@router.get(
    "/library/listen",
    description=_GET_LIBRARY_LISTEN_DESCRIPTION,
    openapi_extra=agent_tool(name="get_library_listen", effect=ToolEffect.READ_ONLY),
)
def api_library_listen(
    offset: int = Query(0, ge=0, le=LISTEN_MAX_OFFSET),
    limit: int = Query(LISTEN_DEFAULT_PLACES, ge=1, le=PAGE_MAX_LIMIT),
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> LibraryListenResponse:
    listens = list_place_listens(
        session, viewer_id=user.id, owner_id=owner_filter(user), limit=offset + limit,
    )
    return LibraryListenResponse.from_orm(
        listens[offset:], reaches=lambda album: can_access_album(album, user),
    )


_GET_LIBRARY_WRITE_DESCRIPTION = (
    "Read the songs the person worked on most recently, to pick up writing again."
)


@router.get(
    "/library/write",
    description=_GET_LIBRARY_WRITE_DESCRIPTION,
    openapi_extra=agent_tool(name="get_library_write", effect=ToolEffect.READ_ONLY),
)
def api_library_write(
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> LibraryWriteResponse:
    worked_songs = list_worked_songs(
        session, viewer_id=user.id, owner_id=owner_filter(user), limit=WRITE_SONGS,
    )
    return LibraryWriteResponse.from_orm(worked_songs)


_SEARCH_LIBRARY_DESCRIPTION = (
    "Search the person's own library by a text q and sort; page on with the returned cursor."
)


@router.get(
    "/library/search",
    description=_SEARCH_LIBRARY_DESCRIPTION,
    openapi_extra=agent_tool(name="search_library", effect=ToolEffect.READ_ONLY),
    responses={422: {"description": "Search cursor is invalid or does not match the query"}},
)
def api_library_search(
    q: str = Query(..., min_length=1),
    sort: LibrarySort = Query(LIBRARY_SORT_NEWEST),
    cursor: str | None = Query(None),
    limit: int = Query(PAGE_DEFAULT_LIMIT, ge=1, le=PAGE_MAX_LIMIT),
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> LibrarySearchResponse:
    query = parse_required_search_query(q)
    after = None
    if cursor is not None:
        try:
            after = decode_library_cursor(
                cursor, ctx.signing_key, q=query, sort=sort,
            )
        except LibraryCursorInvalidError:
            raise HTTPException(422, LIBRARY_CURSOR_INVALID)
        except LibraryCursorMismatchError:
            raise HTTPException(422, LIBRARY_CURSOR_MISMATCH)
    page = search_library(
        session,
        owner_id=owner_filter(user),
        q=query,
        sort=sort,
        limit=limit,
        after=after,
    )
    next_cursor = None
    if page.has_more:
        next_cursor = encode_library_cursor(
            cursor_from_hit(page.items[-1], q=query, sort=sort),
            ctx.signing_key,
        )
    album_ids = [item.id for item in page.items if isinstance(item, Album)]
    picked_counts = count_picked_songs_by_album(session, album_ids)
    song_counts = count_songs_by_album(session, album_ids)
    return LibrarySearchResponse.from_orm(
        page.items,
        has_more=page.has_more,
        next_cursor=next_cursor,
        picked_counts=picked_counts,
        playable_album_ids=album_ids_with_playable_take(session, album_ids),
        picked_song_ids=song_ids_with_pick(
            session, [item.id for item in page.items if isinstance(item, Song)],
        ),
        song_counts=song_counts,
    )


_GET_LIBRARY_POOL_QUEUE_DESCRIPTION = (
    "Read a queue of the person's takes from a pool, optionally shuffled or starting at one "
    "take. Changes nothing."
)


@router.get(
    "/library/pool-queue",
    description=_GET_LIBRARY_POOL_QUEUE_DESCRIPTION,
    openapi_extra=agent_tool(name="get_library_pool_queue", effect=ToolEffect.READ_ONLY),
)
def api_library_pool_queue(
    request: Request,
    pool: LibraryTakePool = Query(DEFAULT_LIBRARY_TAKE_POOL),
    shuffle: bool = Query(False),
    start_generation_id: str | None = Query(default=None, min_length=1, max_length=36),
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> LibraryPoolQueueResponse:
    check_queue_stream_rate_limit(request, user)
    membership = resolve_library_pool_membership(
        session,
        user,
        ctx,
        pool=pool,
        start_generation_id=start_generation_id,
        shuffle=shuffle,
    )
    return LibraryPoolQueueResponse.from_orm(
        pool=membership.pool,
        generations=[source.generation for source in membership.sources],
        skipped=membership.skipped,
        skipped_complete=membership.skipped_complete,
    )
