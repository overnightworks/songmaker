"""The S3 object store: the one module that owns boto3.

The platform hands every web process the store's address, region and credentials file through
the environment (`AWS_ENDPOINT_URL_S3`, `AWS_DEFAULT_REGION`, `AWS_SHARED_CREDENTIALS_FILE`),
which botocore reads itself, so the client takes no endpoint, region or key. Calls block; an
async caller runs them in a worker thread.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from itertools import batched
from pathlib import Path
from typing import TYPE_CHECKING, Final

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from botocore.response import StreamingBody

if TYPE_CHECKING:
    from songmaker_cli.settings import Settings

DELETE_OBJECTS_PER_CALL: Final = 1000
STREAM_CHUNK_BYTES: Final = 64 * 1024
_MISSING_KEY_CODES: Final = frozenset({"NoSuchKey", "404"})
_UNSATISFIABLE_RANGE_CODE: Final = "InvalidRange"


class ObjectMissingError(Exception):
    """The key names no object."""


class ObjectRangeError(Exception):
    """The requested byte range lies outside the object."""


@dataclass(frozen=True)
class StoredObject:
    key: str
    size: int
    last_modified: datetime


class ObjectBody:
    """An object read from the store, all of it or the byte range asked for."""

    def __init__(self, body: StreamingBody, length: int, content_range: str | None) -> None:
        self._body = body
        self.length = length
        self.content_range = content_range
        """`bytes first-last/total` when a range was asked for, else None."""

    def chunks(self) -> Iterator[bytes]:
        try:
            yield from self._body.iter_chunks(STREAM_CHUNK_BYTES)
        finally:
            self._body.close()

    def read(self) -> bytes:
        try:
            return self._body.read()
        finally:
            self._body.close()


class ObjectStore:
    """One bucket, reached through one client for the process."""

    def __init__(self, bucket: str) -> None:
        self._bucket = bucket
        self._client = boto3.client("s3", config=Config(s3={"addressing_style": "path"}))

    def put_file(self, key: str, path: Path, *, content_type: str) -> None:
        self._client.upload_file(
            str(path), self._bucket, key, ExtraArgs={"ContentType": content_type},
        )

    def put_bytes(self, key: str, body: bytes, *, content_type: str) -> None:
        self._client.put_object(Bucket=self._bucket, Key=key, Body=body, ContentType=content_type)

    def get_bytes(self, key: str) -> bytes:
        return self.open(key).read()

    def open(self, key: str, byte_range: str | None = None) -> ObjectBody:
        """Stream the object; `byte_range` is an HTTP `Range` header value."""
        try:
            answer = self._client.get_object(
                Bucket=self._bucket, Key=key, **({"Range": byte_range} if byte_range else {}),
            )
        except ClientError as exc:
            raise _store_error(exc) from exc
        return ObjectBody(answer["Body"], answer["ContentLength"], answer.get("ContentRange"))

    def delete(self, keys: list[str]) -> None:
        for batch in batched(keys, DELETE_OBJECTS_PER_CALL):
            self._client.delete_objects(
                Bucket=self._bucket,
                Delete={"Objects": [{"Key": key} for key in batch], "Quiet": True},
            )

    def list(self, prefix: str) -> Iterator[StoredObject]:
        pages = self._client.get_paginator("list_objects_v2").paginate(
            Bucket=self._bucket, Prefix=prefix,
        )
        for page in pages:
            for entry in page.get("Contents", []):
                yield StoredObject(entry["Key"], entry["Size"], entry["LastModified"])


def _store_error(exc: ClientError) -> Exception:
    code = exc.response.get("Error", {}).get("Code")
    if code in _MISSING_KEY_CODES:
        return ObjectMissingError()
    if code == _UNSATISFIABLE_RANGE_CODE:
        return ObjectRangeError()
    return exc


def object_store_of(settings: Settings) -> ObjectStore:
    """The store a web process uses; refuses to start without its bucket."""
    if not settings.songmaker_s3_bucket:
        raise ValueError("SONGMAKER_S3_BUCKET names the object store's bucket and is required")
    return ObjectStore(settings.songmaker_s3_bucket)
