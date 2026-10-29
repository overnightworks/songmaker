"""A take records the reference audio its job actually ran with."""

from __future__ import annotations

import contextlib
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
from songmaker_cli.config import save_generation_defaults
from songmaker_cli.db.models import Generation, GenerationPreset, Version
from songmaker_cli.db.queries.songs import update_song
from songmaker_cli.jobs import run_generation_job

REFERENCE_A = "u1/refs/aaaaaaaa-0000-0000-0000-000000000001.wav"
REFERENCE_B = "u1/refs/bbbbbbbb-0000-0000-0000-000000000002.wav"
REFERENCE_C = "u1/refs/cccccccc-0000-0000-0000-000000000003.wav"


def _write_reference(tmp_path: Path, relative: str) -> None:
    path = tmp_path / "audio" / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"RIFF" + b"\x00" * 40)


def _run_job(
    seeded_db,
    tmp_path: Path,
    *,
    count: int = 1,
    stored_global_defaults: bool = False,
    **task,
) -> None:
    dispatch, post_process, defaults = patch_generation_dispatch(make_generation_dto(seed=42))
    if stored_global_defaults:
        defaults = contextlib.nullcontext()
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


def _name_version_reference(seeded_db, relative: str) -> None:
    with seeded_db() as session:
        version = session.query(Version).filter_by(id="v1").one()
        version.generation_params = {"reference_audio_path": relative}
        session.commit()


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("version", REFERENCE_A),
        ("preset", REFERENCE_C),
        ("global default", REFERENCE_C),
        ("none", ""),
    ],
)
def test_take_records_the_reference_the_job_resolved(
    seeded_db, tmp_path: Path, source: str, expected: str
) -> None:
    _write_reference(tmp_path, REFERENCE_A)
    _write_reference(tmp_path, REFERENCE_C)
    if source == "version":
        _name_version_reference(seeded_db, REFERENCE_A)
    if source == "preset":
        with seeded_db() as session:
            session.add(
                GenerationPreset(
                    name="p",
                    model_mode="sft",
                    is_default=True,
                    created_by="u1",
                    params={"reference_audio_path": REFERENCE_C},
                )
            )
            session.commit()
    if source == "global default":
        save_generation_defaults(seeded_db, {"sft": {"reference_audio_path": REFERENCE_C}})

    _run_job(seeded_db, tmp_path, stored_global_defaults=source == "global default")

    assert _recorded_references(seeded_db) == [expected]


def test_take_keeps_its_reference_after_the_version_is_edited_in_place(
    seeded_db, tmp_path: Path
) -> None:
    _write_reference(tmp_path, REFERENCE_A)
    _write_reference(tmp_path, REFERENCE_B)
    _name_version_reference(seeded_db, REFERENCE_A)
    _run_job(seeded_db, tmp_path)

    with seeded_db() as session:
        update_song(session, "s1", generation_params={"reference_audio_path": REFERENCE_B})
        session.commit()

    with seeded_db() as session:
        assert session.query(Version).filter_by(id="v1").one().generation_params == {
            "reference_audio_path": REFERENCE_B
        }
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
