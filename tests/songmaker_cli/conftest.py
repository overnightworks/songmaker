"""Fixtures shared by the tests of `songmaker_cli`."""

import gc
from collections.abc import Iterator

import pytest


@pytest.fixture
def no_task_left_pending(caplog: pytest.LogCaptureFixture) -> Iterator[None]:
    """Fails a test whose event loop's task is destroyed while still pending.

    asyncio logs that only when the garbage collector reaches the task, so teardown collects."""
    yield
    gc.collect()
    assert [record.getMessage() for record in caplog.records if record.name == "asyncio"] == []
