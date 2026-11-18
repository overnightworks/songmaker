"""A job row stores its arguments as the typed payload of its type and reads them back."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from songmaker_cli.db.models import Job
from songmaker_cli.db.queries.jobs import create_job, get_job
from songmaker_cli.generation_params import CoverTaskParams, RepaintTaskParams
from songmaker_cli.job_payloads import (
    DownloadModelPayload,
    GeneratePayload,
    JobPayload,
    LoadModelPayload,
    LoraTrainingPayload,
    ScorePayload,
)
from songmaker_cli.job_types import JobType

REPAINT = RepaintTaskParams(
    src_wav_path="/audio/u/take.wav", src_generation_id="take",
    repainting_start=0.2, repainting_end=0.6, lyrics="la", prompt="warm",
)
COVER = CoverTaskParams(
    src_wav_path="/audio/u/take.wav", src_generation_id="take",
    audio_cover_strength=0.5, lyrics="la", prompt="warm",
)


def _generate(task_params) -> GeneratePayload:
    return GeneratePayload(
        song_id="song", version_id="version", count=2, user_id="user", seed=7,
        target_model="turbo", task_params=task_params,
    )


PAYLOADS = [
    pytest.param(JobType.GENERATE, _generate(None), id="generate"),
    pytest.param(JobType.GENERATE, _generate(REPAINT), id="repaint"),
    pytest.param(JobType.GENERATE, _generate(COVER), id="cover-take"),
    pytest.param(JobType.SCORE, ScorePayload(gen_id="take", scorers=("silence",)), id="score"),
    pytest.param(JobType.SCORE, ScorePayload(gen_id="take", scorers=None), id="score-all"),
    pytest.param(
        JobType.LORA_TRAINING,
        LoraTrainingPayload(lora_id="voice", user_id="user", target_mode="sft"),
        id="lora-training",
    ),
    pytest.param(
        JobType.LOAD_MODEL_ON_WORKER, LoadModelPayload(worker_id="gpu", mode="turbo"),
        id="load-model",
    ),
    pytest.param(
        JobType.DOWNLOAD_MODEL_ON_WORKER, DownloadModelPayload(mode="turbo"), id="download-model",
    ),
]


@pytest.mark.parametrize(("job_type", "payload"), PAYLOADS)
def test_a_payload_reads_back_as_the_record_that_was_stored(
    pg_factory, job_type, payload: JobPayload,
) -> None:
    with pg_factory() as session:
        job_id = create_job(session, job_type, payload=payload).id
        session.commit()

    with pg_factory() as session:
        assert get_job(session, job_id).payload == payload


@pytest.mark.parametrize(("job_type", "payload"), PAYLOADS)
def test_a_stored_payload_names_the_job_type_it_belongs_to(
    pg_factory, job_type, payload: JobPayload,
) -> None:
    with pg_factory() as session:
        job = create_job(session, job_type, payload=payload)
        session.commit()
        stored_type = session.execute(
            text("SELECT payload->>'job_type' FROM jobs WHERE id = :id"), {"id": job.id},
        ).scalar_one()

    assert stored_type == job_type


def test_a_job_created_without_a_payload_has_none(pg_factory) -> None:
    with pg_factory() as session:
        job_id = create_job(session, JobType.COVER).id
        session.commit()

    with pg_factory() as session:
        assert get_job(session, job_id).payload is None


def test_a_stored_payload_that_is_not_a_record_of_any_type_is_refused_on_read(pg_factory) -> None:
    with pg_factory() as session:
        job_id = create_job(session, JobType.SCORE).id
        session.execute(
            text("UPDATE jobs SET payload = CAST(:payload AS jsonb) WHERE id = :id"),
            {"payload": '{"job_type": "score"}', "id": job_id},
        )
        session.commit()

    with pg_factory() as session:
        with pytest.raises(ValidationError):
            session.get(Job, job_id)


@pytest.mark.parametrize("change", [
    pytest.param(lambda: setattr(_generate(None), "count", 5), id="field"),
    pytest.param(lambda: setattr(_generate(REPAINT).task_params, "lyrics", "x"), id="task"),
    pytest.param(lambda: setattr(_generate(COVER).task_params, "prompt", "x"), id="cover-task"),
    pytest.param(
        lambda: ScorePayload(gen_id="take", scorers=["silence"]).scorers.append("clip"),
        id="scorers",
    ),
])
def test_a_payload_cannot_change_in_place(change) -> None:
    with pytest.raises((ValidationError, AttributeError)):
        change()
