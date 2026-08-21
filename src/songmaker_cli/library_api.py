"""Personal library index search."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from songmaker_cli.api_helpers import parse_required_search_query
from songmaker_cli.api_models import LibrarySearchResponse, LibrarySort
from songmaker_cli.app_context import AppContext, get_app_context, get_db_session
from songmaker_cli.constants import (
    LIBRARY_CURSOR_INVALID,
    LIBRARY_CURSOR_MISMATCH,
    LIBRARY_SORT_NEWEST,
    PAGE_DEFAULT_LIMIT,
    PAGE_MAX_LIMIT,
)
from songmaker_cli.db.queries import search_library
from songmaker_cli.library_cursor import (
    LibraryCursorInvalidError,
    LibraryCursorMismatchError,
    cursor_from_hit,
    decode_library_cursor,
    encode_library_cursor,
)
from songmaker_cli.middleware import AuthenticatedUser, get_current_user

router = APIRouter()


@router.get("/library/search")
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
                cursor, ctx.session_secret, q=query, sort=sort,
            )
        except LibraryCursorInvalidError:
            raise HTTPException(422, LIBRARY_CURSOR_INVALID)
        except LibraryCursorMismatchError:
            raise HTTPException(422, LIBRARY_CURSOR_MISMATCH)
    page = search_library(
        session,
        user_id=user.id,
        q=query,
        sort=sort,
        limit=limit,
        after=after,
    )
    next_cursor = None
    if page.has_more:
        if not page.items:
            raise HTTPException(422, LIBRARY_CURSOR_INVALID)
        next_cursor = encode_library_cursor(
            cursor_from_hit(page.items[-1], q=query, sort=sort),
            ctx.session_secret,
        )
    return LibrarySearchResponse.from_orm(
        page.items, has_more=page.has_more, next_cursor=next_cursor,
    )
