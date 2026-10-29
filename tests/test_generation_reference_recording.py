"""A take records the reference audio its job actually ran with."""

from __future__ import annotations

import wave
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from support.generation_job_world import (
    make_generation_dto,
    patch_generation_dispatch,
    run_async,
)

from songmaker_cli.api_models import CoverTaskParams, RepaintTaskParams
from songmaker_cli.db.models import Generation, ReferenceRecording, User, Version
from songmaker_cli.db.queries.jobs import get_job
from songmaker_cli.db.queries.songs import update_song
from songmaker_cli.jobs import run_generation_job

REFERENCE_A = "u1/refs/aaaaaaaa-0000-0000-0000-000000000001.wav"
REFERENCE_B = "u1/refs/bbbbbbbb-0000-0000-0000-000000000002.wav"


def _write_reference(tmp_path: Path, relative: str) -> None:
    path = tmp_path / "audio" / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"RIFF" + b"\x00" * 40)


def _run_job(
    seeded_db,
    tmp_path: Path,
    *,
    count: int = 1,
    on_dispatch=None,
    **task,
) -> None:
    """Run the job; ``on_dispatch`` replaces the worker dispatch with a callable."""
    dispatch, post_process, defaults = patch_generation_dispatch(
        on_dispatch or make_generation_dto(seed=42)
    )
    with dispatch, post_process, defaults:
        run_async(
            run_generation_job(
                "j1",
                "s1",
                "v1",
                count,
                "u1",
                db_factory=seeded_db,
                audio_dir=tmp_path / "audio",
                data_dir=tmp_path / "data",
                redis=MagicMock(),
                target_model="sft",
                **task,
            )
        )


def _recorded_references(seeded_db) -> list[str | None]:
    with seeded_db() as session:
        takes = (
            session.query(Generation)
            .filter(Generation.song_id == "s1", Generation.id != "g0")
            .all()
        )
        return [take.generation_params.get("reference_audio_path") for take in takes]


def _record_reference(seeded_db, relative: str, user_id: str = "u1") -> str:
    with seeded_db() as session:
        if session.get(User, user_id) is None:
            session.add(User(id=user_id, username=user_id))
            session.flush()
        recording = ReferenceRecording(
            user_id=user_id, storage_path=relative, original_filename="ref.wav", size_bytes=44,
        )
        session.add(recording)
        session.commit()
        return recording.id


def _link_version_reference(seeded_db, reference_id: str) -> None:
    with seeded_db() as session:
        session.query(Version).filter_by(id="v1").one().reference_recording_id = reference_id
        session.commit()


def _name_version_reference_of(seeded_db, relative: str, user_id: str) -> None:
    _link_version_reference(seeded_db, _record_reference(seeded_db, relative, user_id))


def _name_version_reference(seeded_db, relative: str) -> None:
    _name_version_reference_of(seeded_db, relative, "u1")


@pytest.mark.parametrize(("linked", "expected"), [(True, REFERENCE_A), (False, "")])
def test_take_records_the_reference_the_job_resolved(
    seeded_db, tmp_path: Path, linked: bool, expected: str
) -> None:
    _write_reference(tmp_path, REFERENCE_A)
    if linked:
        _name_version_reference(seeded_db, REFERENCE_A)

    _run_job(seeded_db, tmp_path)

    assert _recorded_references(seeded_db) == [expected]


def test_take_keeps_its_reference_after_the_version_is_edited_in_place(
    seeded_db, tmp_path: Path
) -> None:
    _write_reference(tmp_path, REFERENCE_A)
    _write_reference(tmp_path, REFERENCE_B)
    _name_version_reference(seeded_db, REFERENCE_A)
    replacement = _record_reference(seeded_db, REFERENCE_B)
    _run_job(seeded_db, tmp_path)

    with seeded_db() as session:
        update_song(session, "s1", reference_recording_id=replacement)
        session.commit()

    with seeded_db() as session:
        assert session.query(Version).filter_by(id="v1").one().reference_recording_id == replacement
    assert _recorded_references(seeded_db) == [REFERENCE_A]


def test_every_take_of_a_batch_records_the_reference(seeded_db, tmp_path: Path) -> None:
    _write_reference(tmp_path, REFERENCE_A)
    _name_version_reference(seeded_db, REFERENCE_A)

    _run_job(seeded_db, tmp_path, count=2)

    assert _recorded_references(seeded_db) == [REFERENCE_A, REFERENCE_A]


@pytest.mark.parametrize("task", ["repaint", "cover"])
def test_repaint_and_cover_takes_record_the_reference(seeded_db, tmp_path: Path, task: str) -> None:
    _write_reference(tmp_path, REFERENCE_A)
    with seeded_db() as session:
        session.add(
            Generation(id="g0", song_id="s1", mp3_path="u1/g0.mp3", model_mode="sft", seed=1)
        )
        session.commit()
    _name_version_reference(seeded_db, REFERENCE_A)
    source_wav = tmp_path / "source.wav"
    with wave.open(str(source_wav), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(8000)
        writer.writeframes(b"\x00\x00" * 8000)
    if task == "repaint":
        options = {
            "repaint_params": RepaintTaskParams(
                src_wav_path=str(source_wav),
                src_generation_id="g0",
                repainting_start=0.2,
                repainting_end=0.8,
                lyrics="la",
                prompt="rock",
            )
        }
    else:
        options = {
            "cover_params": CoverTaskParams(
                src_wav_path=str(source_wav),
                src_generation_id="g0",
                audio_cover_strength=0.6,
                lyrics="la",
                prompt="rock",
            )
        }

    _run_job(seeded_db, tmp_path, **options)

    assert _recorded_references(seeded_db) == [REFERENCE_A]


def _run_recording_dispatch(seeded_db, tmp_path: Path) -> list[str]:
    """Run the job and return the reference path of each config the worker was sent."""
    received: list[str] = []

    def dispatch(**kwargs):
        received.append(kwargs["ace_config"].reference_audio_path)
        return make_generation_dto(seed=42)

    _run_job(seeded_db, tmp_path, on_dispatch=dispatch)
    return received


def test_the_worker_receives_the_file_of_the_linked_row(seeded_db, tmp_path: Path) -> None:
    _write_reference(tmp_path, REFERENCE_A)
    _name_version_reference(seeded_db, REFERENCE_A)

    assert _run_recording_dispatch(seeded_db, tmp_path) == [str(tmp_path / "audio" / REFERENCE_A)]


def test_a_job_whose_version_links_another_users_row_fails_before_dispatch(
    seeded_db, tmp_path: Path,
) -> None:
    foreign = "u2/refs/dddddddd-0000-0000-0000-000000000004.wav"
    _write_reference(tmp_path, foreign)
    _name_version_reference_of(seeded_db, foreign, "u2")

    assert _run_recording_dispatch(seeded_db, tmp_path) == []

    with seeded_db() as session:
        job = get_job(session, "j1")
        assert (job.status, job.error_type, job.error) == (
            "failed", "setup_error", "Reference audio not found",
        )
    assert _recorded_references(seeded_db) == []
