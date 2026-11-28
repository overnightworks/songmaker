"""The object store adapter against a real Garage."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch

import boto3
import pytest
from botocore.exceptions import ClientError, NoCredentialsError
from logline import unit_trace
from logline.testing import configured
from pydantic import ValidationError
from support.object_store import (
    a_store_that_drops_the_connection_mid_body,
    an_unreachable_object_store,
)

from songmaker_cli import object_store as object_store_module
from songmaker_cli import server
from songmaker_cli.object_store import (
    ObjectMissingError,
    ObjectRangeError,
    ObjectStore,
    ObjectStoreUnavailableError,
    object_store_of,
)
from songmaker_cli.settings import Settings

PAYLOAD = bytes(range(256)) * 40


@contextmanager
def _recorded_header_names() -> Iterator[list[str]]:
    """The header names every `http.client` connection writes, lowercased, in order.

    Entered inside `configured`, after logline's hooks: patched earlier, logline would wrap the
    recorder and the undo would remove logline's own header hook from the class for the process.
    """
    names: list[str] = []
    original = HTTPConnection.putheader

    def record(self: HTTPConnection, header: str | bytes, *values: str) -> None:
        names.append((header.decode() if isinstance(header, bytes) else header).lower())
        original(self, header, *values)

    with patch.object(HTTPConnection, "putheader", record):
        yield names


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


def test_every_store_call_inside_a_trace_is_accepted_and_carries_the_trace(
    object_store: ObjectStore, prefix: str, tmp_path: Path,
) -> None:
    key = f"{prefix}record.json"
    source = tmp_path / "audio.mp3"
    source.write_bytes(PAYLOAD)

    with configured("songmaker-web"), unit_trace(None), _recorded_header_names() as names:
        object_store.put_bytes(key, PAYLOAD, content_type="application/octet-stream")
        object_store.put_file(f"{prefix}audio.mp3", source, content_type="audio/mpeg")
        whole = object_store.get_bytes(key)
        ranged = b"".join(object_store.open(key, "bytes=10-19").chunks())
        listed = [entry.key for entry in object_store.list(prefix)]
        object_store.delete([key, f"{prefix}audio.mp3"])

    assert (whole, ranged, sorted(listed)) == (PAYLOAD, PAYLOAD[10:20], [f"{prefix}audio.mp3", key])
    assert names.count("traceparent") == names.count("authorization") > 0


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


@pytest.mark.parametrize("credentials_file", [None, "absent", "."])
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


def test_settings_reject_platform_store_variables_that_an_env_file_supplies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    for variable in ("AWS_ENDPOINT_URL_S3", "AWS_DEFAULT_REGION", "AWS_SHARED_CREDENTIALS_FILE"):
        monkeypatch.delenv(variable, raising=False)
    credentials = tmp_path / "credentials"
    credentials.write_text("[default]\n", encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text(
        "AWS_ENDPOINT_URL_S3=http://store.invalid\nAWS_DEFAULT_REGION=garage\n"
        f"AWS_SHARED_CREDENTIALS_FILE={credentials}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="extra_forbidden"):
        Settings(
            _env_file=env_file, database_url="postgresql://x", redis_url="redis://x",
            session_secret="s", songmaker_internal_token="t", songmaker_s3_bucket="b",
        )


def test_a_store_error_that_is_not_a_missing_key_or_range_reaches_the_caller_unchanged(
    prefix: str,
) -> None:
    store = ObjectStore(f"no-such-bucket-{uuid.uuid4().hex}")
    key = f"{prefix}a"

    with pytest.raises(ClientError) as raised:
        store.get_bytes(key)

    assert raised.value.response["Error"]["Code"] == "NoSuchBucket"


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(lambda store: store.get_bytes("k"), id="read"),
        pytest.param(lambda store: store.put_bytes("k", b"x", content_type="text/plain"), id="put"),
        pytest.param(lambda store: store.delete(["k"]), id="delete"),
        pytest.param(lambda store: list(store.list("")), id="list"),
    ],
)
def test_a_store_that_cannot_be_reached_is_named_unavailable(
    call, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = an_unreachable_object_store(monkeypatch)

    with pytest.raises(ObjectStoreUnavailableError):
        call(store)


def test_a_connection_that_drops_while_the_body_is_read_is_named_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with a_store_that_drops_the_connection_mid_body(monkeypatch) as store:
        body = store.open("k")

        with pytest.raises(ObjectStoreUnavailableError):
            body.read()


def test_missing_credentials_reach_the_caller_unchanged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    an_unreachable_object_store(monkeypatch)
    for variable in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.delenv(variable)
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "none"))
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "none"))
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.setattr(boto3, "DEFAULT_SESSION", None)

    store = ObjectStore("b")

    with pytest.raises(NoCredentialsError):
        store.get_bytes("k")


def test_deleting_more_keys_than_one_call_takes_removes_them_all(
    object_store: ObjectStore, prefix: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(object_store_module, "DELETE_OBJECTS_PER_CALL", 2)
    keys = [f"{prefix}{number}" for number in range(5)]
    for key in keys:
        object_store.put_bytes(key, b"x", content_type="text/plain")

    object_store.delete(keys)

    assert [entry.key for entry in object_store.list(prefix)] == []
