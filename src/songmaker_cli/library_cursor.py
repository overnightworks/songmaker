"""Signed keyset cursors for the personal library index."""

from __future__ import annotations

import base64
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from songmaker_cli.constants import (
    LIBRARY_CURSOR_INVALID,
    LIBRARY_CURSOR_KEY_ID,
    LIBRARY_CURSOR_KEY_Q,
    LIBRARY_CURSOR_KEY_SORT,
    LIBRARY_CURSOR_KEY_SORT_VALUE,
    LIBRARY_CURSOR_KEY_TYPE,
    LIBRARY_CURSOR_KEY_VERSION,
    LIBRARY_CURSOR_MISMATCH,
    LIBRARY_CURSOR_VERSION,
    LIBRARY_ITEM_ALBUM,
    LIBRARY_ITEM_SONG,
    LIBRARY_SORT_NEWEST,
    LIBRARY_SORT_OLDEST,
    LIBRARY_SORT_TITLE,
    LIBRARY_SORTS,
)

_CURSOR_KEYS = frozenset({
    LIBRARY_CURSOR_KEY_VERSION,
    LIBRARY_CURSOR_KEY_Q,
    LIBRARY_CURSOR_KEY_SORT,
    LIBRARY_CURSOR_KEY_TYPE,
    LIBRARY_CURSOR_KEY_SORT_VALUE,
    LIBRARY_CURSOR_KEY_ID,
})
_ITEM_TYPES = frozenset({LIBRARY_ITEM_ALBUM, LIBRARY_ITEM_SONG})
_TIME_SORTS = frozenset({LIBRARY_SORT_NEWEST, LIBRARY_SORT_OLDEST})


class LibraryCursorInvalidError(ValueError):
    """Cursor is malformed or the signature does not match."""


class LibraryCursorMismatchError(ValueError):
    """Cursor was issued for a different query or sort."""


@dataclass(frozen=True)
class LibraryCursor:
    q: str
    sort: str
    item_type: str
    sort_value: str
    id: str


def encode_library_cursor(cursor: LibraryCursor, secret: bytes) -> str:
    payload = {
        LIBRARY_CURSOR_KEY_VERSION: LIBRARY_CURSOR_VERSION,
        LIBRARY_CURSOR_KEY_Q: cursor.q,
        LIBRARY_CURSOR_KEY_SORT: cursor.sort,
        LIBRARY_CURSOR_KEY_TYPE: cursor.item_type,
        LIBRARY_CURSOR_KEY_SORT_VALUE: cursor.sort_value,
        LIBRARY_CURSOR_KEY_ID: cursor.id,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    packed = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    signature = hmac.new(secret, raw, sha256).hexdigest()
    return f"{packed}.{signature}"


def decode_library_cursor(
    cursor: str, secret: bytes, *, q: str, sort: str,
) -> LibraryCursor:
    parsed = _parse_signed_cursor(cursor, secret)
    if parsed.q != q or parsed.sort != sort:
        raise LibraryCursorMismatchError(LIBRARY_CURSOR_MISMATCH)
    return parsed


def cursor_from_hit(hit: Any, *, q: str, sort: str) -> LibraryCursor:
    from songmaker_cli.db.models import Album

    item_type = LIBRARY_ITEM_ALBUM if isinstance(hit, Album) else LIBRARY_ITEM_SONG
    if sort == LIBRARY_SORT_TITLE:
        sort_value = hit.title.lower()
    else:
        created = hit.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        sort_value = created.isoformat()
    return LibraryCursor(
        q=q,
        sort=sort,
        item_type=item_type,
        sort_value=sort_value,
        id=hit.id,
    )


def _parse_signed_cursor(cursor: str, secret: bytes) -> LibraryCursor:
    if "." not in cursor:
        raise LibraryCursorInvalidError(LIBRARY_CURSOR_INVALID)
    packed, signature = cursor.rsplit(".", 1)
    if not packed or not signature:
        raise LibraryCursorInvalidError(LIBRARY_CURSOR_INVALID)
    try:
        raw = _b64url_decode(packed)
    except ValueError as exc:
        raise LibraryCursorInvalidError(LIBRARY_CURSOR_INVALID) from exc
    expected = hmac.new(secret, raw, sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise LibraryCursorInvalidError(LIBRARY_CURSOR_INVALID)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LibraryCursorInvalidError(LIBRARY_CURSOR_INVALID) from exc
    return _cursor_from_payload(payload)


def _cursor_from_payload(payload: object) -> LibraryCursor:
    if not isinstance(payload, dict) or set(payload) != _CURSOR_KEYS:
        raise LibraryCursorInvalidError(LIBRARY_CURSOR_INVALID)
    version = payload[LIBRARY_CURSOR_KEY_VERSION]
    q = payload[LIBRARY_CURSOR_KEY_Q]
    sort = payload[LIBRARY_CURSOR_KEY_SORT]
    item_type = payload[LIBRARY_CURSOR_KEY_TYPE]
    sort_value = payload[LIBRARY_CURSOR_KEY_SORT_VALUE]
    item_id = payload[LIBRARY_CURSOR_KEY_ID]
    if version != LIBRARY_CURSOR_VERSION:
        raise LibraryCursorInvalidError(LIBRARY_CURSOR_INVALID)
    if not isinstance(q, str) or not q:
        raise LibraryCursorInvalidError(LIBRARY_CURSOR_INVALID)
    if not isinstance(sort, str) or sort not in LIBRARY_SORTS:
        raise LibraryCursorInvalidError(LIBRARY_CURSOR_INVALID)
    if not isinstance(item_type, str) or item_type not in _ITEM_TYPES:
        raise LibraryCursorInvalidError(LIBRARY_CURSOR_INVALID)
    if not isinstance(sort_value, str):
        raise LibraryCursorInvalidError(LIBRARY_CURSOR_INVALID)
    if not isinstance(item_id, str) or not item_id:
        raise LibraryCursorInvalidError(LIBRARY_CURSOR_INVALID)
    if sort in _TIME_SORTS:
        _parse_cursor_datetime(sort_value)
    return LibraryCursor(
        q=q,
        sort=sort,
        item_type=item_type,
        sort_value=sort_value,
        id=item_id,
    )


def _parse_cursor_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise LibraryCursorInvalidError(LIBRARY_CURSOR_INVALID) from exc
    return parsed


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)
