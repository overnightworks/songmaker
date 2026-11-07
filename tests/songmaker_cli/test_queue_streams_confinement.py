"""A queue snapshot's audio path is served only from below the snapshot folder."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException
from support.web_app import make_test_app

from songmaker_cli.queue_streams import QUEUE_STREAM_DIRNAME, queue_stream_audio_path

SNAPSHOT_ID = "0123456789abcdef0123456789abcdef"


def _app_context(tmp_path: Path):
    client, _ = make_test_app(tmp_path)
    return client.app.state.ctx


def test_a_snapshot_below_the_stream_folder_resolves(tmp_path: Path) -> None:
    ctx = _app_context(tmp_path)
    stream_dir = ctx.data_dir / QUEUE_STREAM_DIRNAME
    stream_dir.mkdir(parents=True)
    snapshot = stream_dir / f"{SNAPSHOT_ID}.mp3"
    snapshot.write_bytes(b"fake")

    assert queue_stream_audio_path(ctx, SNAPSHOT_ID) == snapshot.resolve()


def test_a_planted_link_to_outside_the_stream_folder_answers_403(tmp_path: Path) -> None:
    ctx = _app_context(tmp_path)
    stream_dir = ctx.data_dir / QUEUE_STREAM_DIRNAME
    stream_dir.mkdir(parents=True)
    outside = tmp_path / "outside.mp3"
    outside.write_bytes(b"fake")
    (stream_dir / f"{SNAPSHOT_ID}.mp3").symlink_to(outside)

    with pytest.raises(HTTPException) as refused:
        queue_stream_audio_path(ctx, SNAPSHOT_ID)

    assert refused.value.status_code == 403
