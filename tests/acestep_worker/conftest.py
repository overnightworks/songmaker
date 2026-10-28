from __future__ import annotations

import socket
from collections.abc import Callable
from pathlib import Path

import pytest
from fake_uv_child import FakeUvChild


@pytest.fixture
def free_port() -> Callable[[], int]:
    """A port that was free a moment ago; the fake child binds its own socket, so the
    probe is closed before it is handed out and the kernel may reuse it under xdist."""

    def pick() -> int:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            return probe.getsockname()[1]

    return pick


@pytest.fixture
def fake_uv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, free_port: Callable[[], int]
) -> FakeUvChild:
    return FakeUvChild(tmp_path, monkeypatch, free_port)
