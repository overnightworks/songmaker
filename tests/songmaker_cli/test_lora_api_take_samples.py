"""Failures of the route that copies a take into a voice's samples."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from support.lora_api_world import make_lora, make_take, post_sample_from_take

from songmaker_cli.app_context import AppContext
from songmaker_cli.db.models import Generation, UserLoraSample


@pytest.mark.parametrize("leftover", ["nothing", "a directory"])
def test_a_take_whose_audio_is_no_longer_a_file_adds_no_sample(
    client_and_ctx: tuple[TestClient, AppContext], leftover: str,
) -> None:
    client, ctx = client_and_ctx
    lora_id = make_lora(ctx)
    take_id = make_take(ctx)
    with ctx.db() as session:
        audio_path = ctx.audio_dir / session.get(Generation, take_id).mp3_path
    audio_path.unlink()
    if leftover == "a directory":
        audio_path.mkdir()

    response = post_sample_from_take(client, lora_id, take_id)

    assert response.status_code == 404
    with ctx.db() as session:
        assert session.query(UserLoraSample).count() == 0


def test_a_failed_copy_of_a_take_leaves_no_sample_row_and_no_file(
    client_and_ctx: tuple[TestClient, AppContext],
) -> None:
    client, ctx = client_and_ctx
    lora_id = make_lora(ctx)
    take_id = make_take(ctx)
    audio_before = {path for path in ctx.audio_dir.rglob("*") if path.is_file()}

    def write_half_then_fail(_source, destination) -> None:
        Path(destination).write_bytes(b"half")
        raise OSError("disk full")

    with (
        patch("shutil.copyfile", side_effect=write_half_then_fail),
        pytest.raises(OSError, match="disk full"),
    ):
        post_sample_from_take(client, lora_id, take_id)

    with ctx.db() as session:
        assert session.query(UserLoraSample).count() == 0
    assert {path for path in ctx.audio_dir.rglob("*") if path.is_file()} == audio_before
