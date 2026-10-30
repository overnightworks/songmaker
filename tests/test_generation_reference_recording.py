"""A take links the reference recording its job actually ran with."""

from __future__ import annotations

import wave
from functools import partial
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError
from support.generation_job_world import (
    make_generation_dto,
    patch_generation_dispatch,
    persist_via_post_process,
    post_process_with_stubbed_audio,
    run_async,
)

from songmaker_cli.api_models import (
    CoverTaskParams,
    GenerationResponse,
    RepaintTaskParams,
    SharedGenerationResponse,
)
from songmaker_cli.api_models.songs import ReferenceResponse
from songmaker_cli.constants import JOB_ERROR_GPU_OUT_OF_MEMORY, JOB_ERROR_UNEXPECTED
from songmaker_cli.db.models import (
    Generation,
    ReferenceRecording,
    ResourceEvent,
    User,
    Version,
)
from songmaker_cli.db.queries.jobs import JobStatusUpdate, get_job, update_job_status
from songmaker_cli.db.queries.songs import update_song
from songmaker_cli.jobs import run_generation_job
from songmaker_cli.jobs._runtime import ReferenceDeletedDuringTake
from songmaker_cli.scheduler import WorkerGpuOutOfMemory, WorkerTaskFailed

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
    post_process=persist_via_post_process,
    **task,
) -> None:
    """Run the job; ``on_dispatch`` replaces the worker dispatch with a callable."""
    dispatch, post_process, defaults = patch_generation_dispatch(
        on_dispatch or make_generation_dto(seed=42), post_process,
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
    """The linked row id of each take the job saved; no take carries a path."""
    with seeded_db() as session:
        takes = (
            session.query(Generation)
            .filter(Generation.song_id == "s1", Generation.id != "g0")
            .all()
        )
        assert all("reference_audio_path" not in (take.generation_params or {}) for take in takes)
        return [take.reference_recording_id for take in takes]


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


def _name_version_reference_of(seeded_db, relative: str, user_id: str) -> str:
    reference_id = _record_reference(seeded_db, relative, user_id)
    _link_version_reference(seeded_db, reference_id)
    return reference_id


def _name_version_reference(seeded_db, relative: str) -> str:
    return _name_version_reference_of(seeded_db, relative, "u1")


@pytest.mark.parametrize("linked", [True, False])
def test_take_links_the_reference_the_job_resolved(
    seeded_db, tmp_path: Path, linked: bool
) -> None:
    _write_reference(tmp_path, REFERENCE_A)
    reference_id = _name_version_reference(seeded_db, REFERENCE_A) if linked else None

    _run_job(seeded_db, tmp_path)

    assert _recorded_references(seeded_db) == [reference_id]


def test_take_keeps_the_reference_the_job_captured_when_the_version_changes_mid_take(
    seeded_db, tmp_path: Path
) -> None:
    _write_reference(tmp_path, REFERENCE_A)
    _write_reference(tmp_path, REFERENCE_B)
    captured = _name_version_reference(seeded_db, REFERENCE_A)
    replacement = _record_reference(seeded_db, REFERENCE_B)

    def edit_version_in_place() -> None:
        with seeded_db() as session:
            update_song(session, "s1", reference_recording_id=replacement)
            session.commit()

    _, dispatch = _dispatching(tmp_path, [edit_version_in_place])
    _run_job(seeded_db, tmp_path, on_dispatch=dispatch)

    with seeded_db() as session:
        assert session.query(Version).filter_by(id="v1").one().reference_recording_id == replacement
    assert _recorded_references(seeded_db) == [captured]


def test_every_take_of_a_batch_links_the_reference(seeded_db, tmp_path: Path) -> None:
    _write_reference(tmp_path, REFERENCE_A)
    reference_id = _name_version_reference(seeded_db, REFERENCE_A)

    _run_job(seeded_db, tmp_path, count=2)

    assert _recorded_references(seeded_db) == [reference_id, reference_id]


@pytest.mark.parametrize("task", ["repaint", "cover"])
def test_repaint_and_cover_takes_link_the_reference(seeded_db, tmp_path: Path, task: str) -> None:
    _write_reference(tmp_path, REFERENCE_A)
    with seeded_db() as session:
        session.add(
            Generation(id="g0", song_id="s1", mp3_path="u1/g0.mp3", model_mode="sft", seed=1)
        )
        session.commit()
    reference_id = _name_version_reference(seeded_db, REFERENCE_A)
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

    assert _recorded_references(seeded_db) == [reference_id]


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


# ── a reference deleted while a take generates ─────────────────────

DELETED_DURING_TAKE = "The reference track was deleted while this take was generating."


def _delete_reference(seeded_db, reference_id: str, *, takes: tuple[str, ...] = ()) -> None:
    """Remove the row the way a delete would: the links first, then the row."""
    with seeded_db() as session:
        session.query(Version).filter_by(id="v1").one().reference_recording_id = None
        for take_id in takes:
            session.query(ResourceEvent).filter_by(generation_id=take_id).delete()
            session.query(Generation).filter_by(id=take_id).delete()
        session.flush()
        session.query(ReferenceRecording).filter_by(id=reference_id).delete()
        session.commit()


def _saved_takes(seeded_db) -> list[str]:
    with seeded_db() as session:
        return [take.id for take in session.query(Generation).filter_by(song_id="s1")]


def _job_outcome(seeded_db) -> tuple[str, str | None, str | None]:
    with seeded_db() as session:
        job = get_job(session, "j1")
        return job.status, job.error, job.error_type


def _dispatching(tmp_path: Path, steps) -> tuple[list[int], object]:
    """A dispatch that writes each take's worker audio, then runs that take's step."""
    calls: list[int] = []

    def dispatch(**_kwargs):
        calls.append(len(calls))
        step = steps[calls[-1]]
        worker_audio = tmp_path / f"worker-{calls[-1]}.wav"
        worker_audio.write_bytes(b"RIFF")
        if isinstance(step, Exception):
            raise step
        step()
        return make_generation_dto(seed=42, audio_path=str(worker_audio))

    return calls, dispatch


def test_a_reference_gone_at_persistence_fails_the_job_and_saves_nothing(
    seeded_db, tmp_path: Path,
) -> None:
    _write_reference(tmp_path, REFERENCE_A)
    reference_id = _name_version_reference(seeded_db, REFERENCE_A)
    files: list[Path] = []
    existed: list[bool] = []

    def record_files(written: list[Path]) -> None:
        files.extend(written)
        existed.extend(path.exists() for path in written)

    _, dispatch = _dispatching(tmp_path, [lambda: _delete_reference(seeded_db, reference_id)])

    _run_job(
        seeded_db, tmp_path, on_dispatch=dispatch,
        post_process=partial(post_process_with_stubbed_audio, on_outputs_written=record_files),
    )

    assert existed == [True] * 4
    assert files[-1] == tmp_path / "worker-0.wav"
    assert not any(path.exists() for path in files)
    assert _job_outcome(seeded_db) == ("failed", DELETED_DURING_TAKE, "generation_error")
    assert _saved_takes(seeded_db) == []


def test_a_reference_gone_on_the_first_of_three_takes_submits_no_further_take(
    seeded_db, tmp_path: Path,
) -> None:
    _write_reference(tmp_path, REFERENCE_A)
    reference_id = _name_version_reference(seeded_db, REFERENCE_A)
    calls, dispatch = _dispatching(tmp_path, [lambda: _delete_reference(seeded_db, reference_id)])

    _run_job(seeded_db, tmp_path, count=3, on_dispatch=dispatch)

    assert calls == [0]
    assert _job_outcome(seeded_db) == ("failed", DELETED_DURING_TAKE, "generation_error")


def test_a_reference_gone_after_a_gpu_memory_failure_ends_with_the_deletion_line(
    seeded_db, tmp_path: Path,
) -> None:
    _write_reference(tmp_path, REFERENCE_A)
    reference_id = _name_version_reference(seeded_db, REFERENCE_A)
    _, dispatch = _dispatching(
        tmp_path, [WorkerGpuOutOfMemory("need 18.5 GB"),
                   lambda: _delete_reference(seeded_db, reference_id)],
    )

    _run_job(seeded_db, tmp_path, count=2, on_dispatch=dispatch)

    assert _job_outcome(seeded_db) == ("failed", DELETED_DURING_TAKE, "generation_error")


def test_a_gpu_memory_failure_still_wins_over_a_later_take_failure(
    seeded_db, tmp_path: Path,
) -> None:
    _write_reference(tmp_path, REFERENCE_A)
    _name_version_reference(seeded_db, REFERENCE_A)
    _, dispatch = _dispatching(
        tmp_path, [WorkerGpuOutOfMemory("need 18.5 GB"), WorkerTaskFailed("boom")],
    )

    _run_job(seeded_db, tmp_path, count=2, on_dispatch=dispatch)

    status, error, error_type = _job_outcome(seeded_db)
    assert (status, error_type) == ("failed", "gpu_out_of_memory")
    assert error == JOB_ERROR_GPU_OUT_OF_MEMORY


def test_a_reference_gone_after_an_earlier_take_was_saved_and_deleted_fails_the_job(
    seeded_db, tmp_path: Path,
) -> None:
    _write_reference(tmp_path, REFERENCE_A)
    reference_id = _name_version_reference(seeded_db, REFERENCE_A)

    def delete_first_take_and_reference() -> None:
        _delete_reference(seeded_db, reference_id, takes=tuple(_saved_takes(seeded_db)))

    _, dispatch = _dispatching(tmp_path, [lambda: None, delete_first_take_and_reference])

    _run_job(seeded_db, tmp_path, count=2, on_dispatch=dispatch)

    assert _job_outcome(seeded_db) == ("failed", DELETED_DURING_TAKE, "generation_error")
    assert _saved_takes(seeded_db) == []


def test_a_job_cancelled_before_the_deletion_is_reported_stays_cancelled(
    seeded_db, tmp_path: Path,
) -> None:
    _write_reference(tmp_path, REFERENCE_A)
    reference_id = _name_version_reference(seeded_db, REFERENCE_A)
    _, dispatch = _dispatching(tmp_path, [lambda: _delete_reference(seeded_db, reference_id)])

    def cancel_as_the_deletion_surfaces(**kwargs):
        try:
            return persist_via_post_process(**kwargs)
        except ReferenceDeletedDuringTake:
            with seeded_db() as session:
                update_job_status(session, "j1", JobStatusUpdate("cancelled"))
                session.commit()
            raise

    _run_job(
        seeded_db, tmp_path, on_dispatch=dispatch, post_process=cancel_as_the_deletion_surfaces,
    )

    assert _job_outcome(seeded_db)[0] == "cancelled"


def test_a_take_number_conflict_fails_as_before_not_with_the_deletion_line(
    seeded_db, tmp_path: Path,
) -> None:
    _write_reference(tmp_path, REFERENCE_A)
    _name_version_reference(seeded_db, REFERENCE_A)
    conflict = IntegrityError("INSERT", {}, Exception("uq_generation_song_number"))

    with patch("songmaker_cli.jobs.generation.create_generation", side_effect=conflict):
        _run_job(seeded_db, tmp_path)

    status, error, _ = _job_outcome(seeded_db)
    assert (status, error) == ("failed", JOB_ERROR_UNEXPECTED)
    assert _saved_takes(seeded_db) == []


def test_deleting_a_reference_a_take_links_is_refused_by_the_database(
    seeded_db, tmp_path: Path,
) -> None:
    _write_reference(tmp_path, REFERENCE_A)
    reference_id = _name_version_reference(seeded_db, REFERENCE_A)
    _run_job(seeded_db, tmp_path)
    with seeded_db() as session:
        session.query(Version).filter_by(id="v1").update({Version.reference_recording_id: None})
        session.query(Generation).update({Generation.is_archived: True})
        session.commit()

    with seeded_db() as session, pytest.raises(IntegrityError):
        session.query(ReferenceRecording).filter_by(id=reference_id).delete()
        session.flush()


def test_the_take_response_names_the_reference_by_its_original_filename(
    seeded_db, tmp_path: Path,
) -> None:
    _write_reference(tmp_path, REFERENCE_A)
    reference_id = _name_version_reference(seeded_db, REFERENCE_A)
    _run_job(seeded_db, tmp_path)

    with seeded_db() as session:
        take = session.query(Generation).filter_by(song_id="s1").one()
        response = GenerationResponse.from_orm(take)

    assert response.reference == ReferenceResponse(id=reference_id, filename="ref.wav")
    assert "reference" not in SharedGenerationResponse.model_fields
