"""The object store of a test run: the bucket `TEST_S3_BUCKET` names, on a real Garage.

CI starts it with platform's garage action, `scripts/test_postgresql.sh` starts one locally; both
export `AWS_ENDPOINT_URL_S3`, `AWS_DEFAULT_REGION` and `AWS_SHARED_CREDENTIALS_FILE`, which the
client reads. Every worker and case shares the bucket, so a case that sweeps or fills the
queue-stream cache names a key prefix of its own first.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from dataclasses import replace
from datetime import timedelta

import pytest

from songmaker_cli import queue_streams
from songmaker_cli.object_store import ObjectStore, StoredObject

BUCKET_VARIABLE = "TEST_S3_BUCKET"
UNCONFIGURED_BUCKET = "unconfigured"
"""A client builds without a store; a call to it fails, naming the missing endpoint."""


def configured_bucket() -> str:
    return os.environ.get(BUCKET_VARIABLE, UNCONFIGURED_BUCKET)


def an_object_store() -> ObjectStore:
    return ObjectStore(configured_bucket())


class AgedObjectStore(ObjectStore):
    """The real store, whose listing shows chosen objects as older than they are.

    A write stamps an object with the time it is made, which a case cannot set; the sweep and
    the quota read that time from the listing.
    """

    def __init__(self, bucket: str) -> None:
        super().__init__(bucket)
        self._extra_age: dict[str, timedelta] = {}

    def age(self, key: str, by: timedelta) -> None:
        self._extra_age[key] = by

    def list(self, prefix: str) -> Iterator[StoredObject]:
        for entry in super().list(prefix):
            older = self._extra_age.get(entry.key, timedelta())
            yield replace(entry, last_modified=entry.last_modified - older)


def an_aged_object_store() -> AgedObjectStore:
    return AgedObjectStore(configured_bucket())


def isolate_queue_stream_keys(monkeypatch: pytest.MonkeyPatch) -> str:
    """Give this case its own queue-stream key prefix in the shared bucket."""
    prefix = f"case-{uuid.uuid4().hex}/{queue_streams.QUEUE_STREAM_KEY_PREFIX}"
    monkeypatch.setattr(queue_streams, "QUEUE_STREAM_KEY_PREFIX", prefix)
    return prefix


@pytest.fixture
def object_store(monkeypatch: pytest.MonkeyPatch) -> ObjectStore:
    """The run's store, with this case's queue-stream keys apart from every other case's."""
    if BUCKET_VARIABLE not in os.environ:
        pytest.fail(
            f"{BUCKET_VARIABLE} is not set: run object store tests through "
            "scripts/test_postgresql.sh, which starts a disposable Garage.",
            pytrace=False,
        )
    isolate_queue_stream_keys(monkeypatch)
    return an_object_store()
