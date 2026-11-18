"""A queue stream build that needs no ffmpeg and no real audio."""

from __future__ import annotations

from pathlib import Path

import pytest
from support.object_store import isolate_queue_stream_keys

from songmaker_cli import queue_streams


def stub_audio_build(monkeypatch: pytest.MonkeyPatch) -> None:
    isolate_queue_stream_keys(monkeypatch)
    monkeypatch.setattr(queue_streams, "probe_audio_duration", lambda _path: 10.0)

    def fake_concat(_concat_path: Path, output_path: Path) -> None:
        output_path.write_bytes(b"\xff\xfb\x90\x00" * 100)

    monkeypatch.setattr(queue_streams, "run_ffmpeg_concat", fake_concat)
