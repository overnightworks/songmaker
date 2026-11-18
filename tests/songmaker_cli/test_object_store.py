"""The object store adapter against a real Garage."""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

from songmaker_cli import object_store as object_store_module
from songmaker_cli import server
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


def test_a_web_process_without_a_bucket_name_refuses_to_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    settings = Settings(
        database_url="postgresql://x", redis_url="redis://x", session_secret="s",
        songmaker_internal_token="t",
    )
    monkeypatch.setattr(server, "get_settings", lambda: settings)

    with pytest.raises(ValueError, match="SONGMAKER_S3_BUCKET"):
        server._create_default_context(tmp_path, tmp_path)


@pytest.mark.parametrize("missing", ["AWS_ENDPOINT_URL_S3", "AWS_DEFAULT_REGION"])
def test_a_web_process_without_a_platform_store_variable_refuses_to_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, missing: str,
) -> None:
    credentials = tmp_path / "credentials"
    credentials.write_text("[default]\n", encoding="utf-8")
    monkeypatch.setenv("AWS_ENDPOINT_URL_S3", "http://store.invalid")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "garage")
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(credentials))
    monkeypatch.delenv(missing)

    with pytest.raises(ValueError, match=missing):
        object_store_of(Settings(
            database_url="postgresql://x", redis_url="redis://x", session_secret="s",
            songmaker_internal_token="t", songmaker_s3_bucket="b",
        ))


@pytest.mark.parametrize("credentials_file", [None, "absent"])
def test_a_web_process_without_a_readable_credentials_file_refuses_to_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, credentials_file: str | None,
) -> None:
    monkeypatch.setenv("AWS_ENDPOINT_URL_S3", "http://store.invalid")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "garage")
    if credentials_file is None:
        monkeypatch.delenv("AWS_SHARED_CREDENTIALS_FILE", raising=False)
    else:
        monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / credentials_file))

    with pytest.raises(ValueError, match="AWS_SHARED_CREDENTIALS_FILE"):
        object_store_of(Settings(
            database_url="postgresql://x", redis_url="redis://x", session_secret="s",
            songmaker_internal_token="t", songmaker_s3_bucket="b",
        ))


def test_a_store_error_that_is_not_a_missing_key_or_range_reaches_the_caller_unchanged(
    prefix: str,
) -> None:
    with pytest.raises(ClientError) as raised:
        ObjectStore(f"no-such-bucket-{uuid.uuid4().hex}").get_bytes(f"{prefix}a")

    assert raised.value.response["Error"]["Code"] == "NoSuchBucket"


def test_deleting_more_keys_than_one_call_takes_removes_them_all(
    object_store: ObjectStore, prefix: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(object_store_module, "DELETE_OBJECTS_PER_CALL", 2)
    keys = [f"{prefix}{number}" for number in range(5)]
    for key in keys:
        object_store.put_bytes(key, b"x", content_type="text/plain")

    object_store.delete(keys)

    assert [entry.key for entry in object_store.list(prefix)] == []
