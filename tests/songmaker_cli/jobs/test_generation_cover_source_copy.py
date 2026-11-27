"""A cover take's working copy of its source take is gone once its job ended."""

from __future__ import annotations

from pathlib import Path

import pytest
from support.generation_job_world import (
    make_generation_dto,
    patch_generation_dispatch,
    run_async,
)
from support.job_owner import an_owner
from support.score_jobs import ScoringRedis

from songmaker_cli.db.models import Generation
from songmaker_cli.generation_params import CoverTaskParams
from songmaker_cli.jobs import run_generation_job


@pytest.mark.parametrize("job_fails", [False, True], ids=["completed", "failed"])
def test_a_cover_job_leaves_no_source_copy_in_the_tmp_directory(
    seeded_db, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, job_fails: bool,
) -> None:
    monkeypatch.chdir(tmp_path)
    audio_dir = Path("data/audio")
    tmp_dir = audio_dir / ".tmp"
    tmp_dir.mkdir(parents=True)
    unrelated = tmp_dir / "unrelated.wav"
    unrelated.write_bytes(b"other")
    stored_take = audio_dir / "take.wav"
    stored_take.write_bytes(b"stored")
    with seeded_db() as session:
        session.add(
            Generation(id="g0", song_id="s1", mp3_path="u1/g0.mp3", model_mode="sft", seed=1)
        )
        session.commit()
    source = tmp_path / "source.wav"
    source.write_bytes(b"RIFF" + b"\x00" * 40)

    def dispatch_outcome(**_kwargs):
        if job_fails:
            raise RuntimeError("worker failed")
        return make_generation_dto()

    dispatch, post_process, defaults = patch_generation_dispatch(dispatch_outcome)
    with dispatch, post_process, defaults:
        run_async(
            run_generation_job(
                "j1", "s1", "v1", 1, "u1",
                db_factory=seeded_db,
                audio_dir=audio_dir,
                data_dir=Path("data"),
                redis=ScoringRedis(worker_running=False),
                target_model="sft",
                owner=an_owner("o1"),
                task_params=CoverTaskParams(
                    src_wav_path=str(source), src_generation_id="g0",
                    audio_cover_strength=0.7, lyrics="la", prompt="p",
                ),
            )
        )

    assert sorted(path.name for path in tmp_dir.iterdir()) == ["unrelated.wav"]
    assert stored_take.read_bytes() == b"stored"
