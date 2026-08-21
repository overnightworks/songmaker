"""Signed library cursor encode/decode."""

from __future__ import annotations

import pytest
from conftest import TEST_SECRET

from songmaker_cli.constants import (
    LIBRARY_CURSOR_INVALID,
    LIBRARY_CURSOR_MISMATCH,
    LIBRARY_ITEM_ALBUM,
    LIBRARY_SORT_NEWEST,
    LIBRARY_SORT_TITLE,
)
from songmaker_cli.library_cursor import (
    LibraryCursor,
    LibraryCursorInvalidError,
    LibraryCursorMismatchError,
    decode_library_cursor,
    encode_library_cursor,
)


def test_cursor_roundtrip() -> None:
    cursor = LibraryCursor(
        q="nachtstrom",
        sort=LIBRARY_SORT_NEWEST,
        item_type=LIBRARY_ITEM_ALBUM,
        sort_value="2026-01-01T00:00:00+00:00",
        id="nachtstrom",
    )
    encoded = encode_library_cursor(cursor, TEST_SECRET)
    decoded = decode_library_cursor(
        encoded, TEST_SECRET, q="nachtstrom", sort=LIBRARY_SORT_NEWEST,
    )
    assert decoded == cursor


def test_cursor_rejects_query_mismatch() -> None:
    cursor = LibraryCursor(
        q="nachtstrom",
        sort=LIBRARY_SORT_NEWEST,
        item_type=LIBRARY_ITEM_ALBUM,
        sort_value="2026-01-01T00:00:00+00:00",
        id="nachtstrom",
    )
    encoded = encode_library_cursor(cursor, TEST_SECRET)
    with pytest.raises(LibraryCursorMismatchError, match=LIBRARY_CURSOR_MISMATCH):
        decode_library_cursor(encoded, TEST_SECRET, q="tide", sort=LIBRARY_SORT_NEWEST)


def test_cursor_rejects_sort_mismatch() -> None:
    cursor = LibraryCursor(
        q="nachtstrom",
        sort=LIBRARY_SORT_NEWEST,
        item_type=LIBRARY_ITEM_ALBUM,
        sort_value="2026-01-01T00:00:00+00:00",
        id="nachtstrom",
    )
    encoded = encode_library_cursor(cursor, TEST_SECRET)
    with pytest.raises(LibraryCursorMismatchError, match=LIBRARY_CURSOR_MISMATCH):
        decode_library_cursor(
            encoded, TEST_SECRET, q="nachtstrom", sort=LIBRARY_SORT_TITLE,
        )


def test_cursor_rejects_bad_signature() -> None:
    cursor = LibraryCursor(
        q="nachtstrom",
        sort=LIBRARY_SORT_NEWEST,
        item_type=LIBRARY_ITEM_ALBUM,
        sort_value="2026-01-01T00:00:00+00:00",
        id="nachtstrom",
    )
    encoded = encode_library_cursor(cursor, TEST_SECRET)
    with pytest.raises(LibraryCursorInvalidError, match=LIBRARY_CURSOR_INVALID):
        decode_library_cursor(
            encoded + "x", TEST_SECRET, q="nachtstrom", sort=LIBRARY_SORT_NEWEST,
        )


def test_cursor_rejects_other_secret() -> None:
    cursor = LibraryCursor(
        q="nachtstrom",
        sort=LIBRARY_SORT_NEWEST,
        item_type=LIBRARY_ITEM_ALBUM,
        sort_value="2026-01-01T00:00:00+00:00",
        id="nachtstrom",
    )
    encoded = encode_library_cursor(cursor, TEST_SECRET)
    with pytest.raises(LibraryCursorInvalidError, match=LIBRARY_CURSOR_INVALID):
        decode_library_cursor(
            encoded, b"b" * 64, q="nachtstrom", sort=LIBRARY_SORT_NEWEST,
        )
