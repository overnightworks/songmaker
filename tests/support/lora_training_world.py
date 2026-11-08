"""Database and audio-directory arrangement for LoRA training job tests."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from songmaker_cli.constants import USER_LORAS_DIRNAME, LoraStatus
from songmaker_cli.db.models import Job, User, UserLora, UserLoraSample
from songmaker_cli.job_types import JobType


def seed_queued_lora(db_factory: sessionmaker[Session], tmp_path: Path) -> dict:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    user_id = "user-1"
    lora_id = "lora-1"
    sample_dir = audio_dir / USER_LORAS_DIRNAME / user_id / lora_id / "samples"
    sample_dir.mkdir(parents=True)
    sample_ids = ["sample-a", "sample-b", "sample-c"]
    sample_files: list[str] = []
    for sid in sample_ids:
        f = sample_dir / f"{sid}.wav"
        f.write_bytes(b"RIFF0000WAVEfmt ")
        sample_files.append(
            f"{USER_LORAS_DIRNAME}/{user_id}/{lora_id}/samples/{sid}.wav",
        )

    with db_factory() as session:
        session.add(
            User(id=user_id, username="u1", role="user"),
        )
        session.add(
            UserLora(
                id=lora_id,
                user_id=user_id,
                name="My LoRA",
                slug="my-lora",
                status=LoraStatus.QUEUED,
                training_job_id="job-1",
            ),
        )
        for idx, sid in enumerate(sample_ids):
            session.add(
                UserLoraSample(
                    id=sid,
                    user_lora_id=lora_id,
                    audio_path=sample_files[idx],
                    caption=f"caption {idx}",
                    lyrics=f"lyrics {idx}",
                    position=idx,
                ),
            )
        session.add(Job(id="job-1", type=JobType.LORA_TRAINING, status="queued"))
        session.commit()

    return {
        "audio_dir": audio_dir,
        "user_id": user_id,
        "lora_id": lora_id,
        "sample_ids": sample_ids,
    }
