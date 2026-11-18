"""The object store adapter against a real Garage."""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

import pytest

from songmaker_cli.object_store import (
    ObjectMissingError,
    ObjectRangeError,
    ObjectStore,
    object_store_of,
)
from songmaker_cli.settings import Settings

PAYLOAD = bytes(range(256)) * 40


@pytest.fixture
def prefix() -> str:
    return f"adapter-test/{uuid.uuid4().hex}/"


def test_a_file_put_to_the_store_reads_back_whole_and_by_range(
    object_store: ObjectStore, prefix: str, tmp_path: Path,
) -> None:
    source = tmp_path / "audio.mp3"
    source.write_bytes(PAYLOAD)
    object_store.put_file(f"{prefix}audio.mp3", source, content_type="audio/mpeg")

    whole = object_store.open(f"{prefix}audio.mp3")
    ranged = object_store.open(f"{prefix}audio.mp3", "bytes=10-19")

    assert (
        b"".join(whole.chunks()), whole.content_range,
        b"".join(ranged.chunks()), ranged.length, ranged.content_range,
    ) == (PAYLOAD, None, PAYLOAD[10:20], 10, f"bytes 10-19/{len(PAYLOAD)}")


def test_bytes_put_to_the_store_read_back(object_store: ObjectStore, prefix: str) -> None:
    object_store.put_bytes(f"{prefix}record.json", b'{"a": 1}', content_type="application/json")

    assert object_store.get_bytes(f"{prefix}record.json") == b'{"a": 1}'


def test_listing_a_prefix_names_its_objects_with_size_and_age_and_no_others(
    object_store: ObjectStore, prefix: str,
) -> None:
    object_store.put_bytes(f"{prefix}one", b"abc", content_type="text/plain")
    object_store.put_bytes(f"{prefix}nested/two", b"de", content_type="text/plain")
    object_store.put_bytes(f"{prefix}x/other", b"f", content_type="text/plain")

    listed = {entry.key: entry for entry in object_store.list(f"{prefix}nested/")}
    both = {entry.key: entry.size for entry in object_store.list(prefix) if "x/" not in entry.key}

    assert (
        sorted(listed), listed[f"{prefix}nested/two"].size,
        isinstance(listed[f"{prefix}nested/two"].last_modified, datetime),
        both,
    ) == ([f"{prefix}nested/two"], 2, True, {f"{prefix}one": 3, f"{prefix}nested/two": 2})


def test_deleted_objects_are_gone_and_a_missing_object_is_named_as_missing(
    object_store: ObjectStore, prefix: str,
) -> None:
    object_store.put_bytes(f"{prefix}a", b"1", content_type="text/plain")
    object_store.put_bytes(f"{prefix}b", b"2", content_type="text/plain")

    object_store.delete([f"{prefix}a", f"{prefix}b", f"{prefix}never-there"])

    assert [entry.key for entry in object_store.list(prefix)] == []
    with pytest.raises(ObjectMissingError):
        object_store.get_bytes(f"{prefix}a")


def test_a_range_beyond_the_object_is_refused(object_store: ObjectStore, prefix: str) -> None:
    object_store.put_bytes(f"{prefix}short", b"abc", content_type="text/plain")

    with pytest.raises(ObjectRangeError):
        object_store.open(f"{prefix}short", "bytes=100-200")


def test_a_web_process_without_a_bucket_name_refuses_to_start() -> None:
    settings = Settings(
        database_url="postgresql://x", redis_url="redis://x", session_secret="s",
        songmaker_internal_token="t",
    )

    with pytest.raises(ValueError, match="SONGMAKER_S3_BUCKET"):
        object_store_of(settings)
