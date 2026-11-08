"""Signed library cursor encode/decode."""

from __future__ import annotations

import base64
import hmac
import json
from hashlib import sha256

import pytest
from support.web_app import TEST_SECRET

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
    LIBRARY_SORT_NEWEST,
    LIBRARY_SORT_TITLE,
)
from songmaker_cli.db.queries.library import LibraryCursor
from songmaker_cli.library_cursor import (
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


@pytest.mark.parametrize("suffix", ["x", "é"], ids=["ascii", "non-ascii"])
def test_cursor_rejects_bad_signature(suffix: str) -> None:
    """1301-F13-SIGNATURE: malformed signatures raise the cursor invalid error."""
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
            encoded + suffix, TEST_SECRET, q="nachtstrom", sort=LIBRARY_SORT_NEWEST,
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


def _signed(raw: bytes) -> str:
    packed = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return f"{packed}.{hmac.new(TEST_SECRET, raw, sha256).hexdigest()}"


def _signed_payload(**overrides: object) -> str:
    payload: dict[str, object] = {
        LIBRARY_CURSOR_KEY_VERSION: LIBRARY_CURSOR_VERSION,
        LIBRARY_CURSOR_KEY_Q: "nachtstrom",
        LIBRARY_CURSOR_KEY_SORT: LIBRARY_SORT_NEWEST,
        LIBRARY_CURSOR_KEY_TYPE: LIBRARY_ITEM_ALBUM,
        LIBRARY_CURSOR_KEY_SORT_VALUE: "2026-01-01T00:00:00+00:00",
        LIBRARY_CURSOR_KEY_ID: "nachtstrom",
    }
    payload.update(overrides)
    return _signed(json.dumps(payload).encode("utf-8"))


@pytest.mark.parametrize(
    "cursor",
    [
        pytest.param(".deadbeef", id="empty-encoded-part"),
        pytest.param("e30.", id="empty-signature"),
        pytest.param("a.deadbeef", id="prefix-is-not-base64"),
        pytest.param(_signed(b"\xff\xfe"), id="signed-bytes-are-not-utf8"),
        pytest.param(_signed(b"not json"), id="signed-text-is-not-json"),
        pytest.param(_signed(b"[]"), id="signed-json-is-no-object"),
        pytest.param(_signed(b"{}"), id="signed-object-lacks-the-keys"),
        pytest.param(_signed_payload(extra=1), id="signed-object-has-another-key"),
        pytest.param(_signed_payload(**{LIBRARY_CURSOR_KEY_VERSION: 0}), id="other-version"),
        pytest.param(_signed_payload(**{LIBRARY_CURSOR_KEY_Q: ""}), id="empty-query"),
        pytest.param(_signed_payload(**{LIBRARY_CURSOR_KEY_Q: 1}), id="query-is-no-string"),
        pytest.param(_signed_payload(**{LIBRARY_CURSOR_KEY_SORT: "random"}), id="unknown-sort"),
        pytest.param(_signed_payload(**{LIBRARY_CURSOR_KEY_SORT: 1}), id="sort-is-no-string"),
        pytest.param(_signed_payload(**{LIBRARY_CURSOR_KEY_TYPE: "playlist"}), id="unknown-type"),
        pytest.param(_signed_payload(**{LIBRARY_CURSOR_KEY_TYPE: 1}), id="type-is-no-string"),
        pytest.param(
            _signed_payload(**{LIBRARY_CURSOR_KEY_SORT_VALUE: 1}), id="sort-value-is-no-string",
        ),
        pytest.param(_signed_payload(**{LIBRARY_CURSOR_KEY_ID: ""}), id="empty-id"),
        pytest.param(_signed_payload(**{LIBRARY_CURSOR_KEY_ID: 1}), id="id-is-no-string"),
        pytest.param(
            _signed_payload(**{LIBRARY_CURSOR_KEY_SORT_VALUE: "yesterday"}),
            id="time-sort-value-is-no-timestamp",
        ),
    ],
)
def test_cursor_rejects_a_malformed_cursor_even_when_signed(cursor: str) -> None:
    with pytest.raises(LibraryCursorInvalidError, match=LIBRARY_CURSOR_INVALID):
        decode_library_cursor(cursor, TEST_SECRET, q="nachtstrom", sort=LIBRARY_SORT_NEWEST)


def test_cursor_of_a_title_sort_keeps_a_sort_value_that_is_no_timestamp() -> None:
    cursor = decode_library_cursor(
        _signed_payload(**{
            LIBRARY_CURSOR_KEY_SORT: LIBRARY_SORT_TITLE,
            LIBRARY_CURSOR_KEY_SORT_VALUE: "nachtstrom",
        }),
        TEST_SECRET,
        q="nachtstrom",
        sort=LIBRARY_SORT_TITLE,
    )
    assert cursor.sort_value == "nachtstrom"
