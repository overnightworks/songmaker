"""Queued music-queue jobs for tests that claim or run them."""

from __future__ import annotations

from datetime import timedelta

from songmaker_cli.constants import MODEL_DEFAULT_MODE
from songmaker_cli.db.models import Job
from songmaker_cli.db.queries.jobs import create_job
from songmaker_cli.job_payloads import LoraTrainingPayload
from songmaker_cli.job_types import JobType
from songmaker_cli.timestamps import utcnow

A_VOICE_THAT_DOES_NOT_EXIST = LoraTrainingPayload(
    lora_id="no-such-voice", user_id="no-such-user", target_mode=MODEL_DEFAULT_MODE,
)
MISSING_VOICE_KEY = "voiceFailure.notFound"


def queued_music_job(session, *, due_in: float = 0) -> Job:
    """A queued voice-training job whose wait ends ``due_in`` seconds from now.

    It names a voice that does not exist, so a run of the job ends at once, failed.
    """
    job = create_job(session, JobType.LORA_TRAINING, payload=A_VOICE_THAT_DOES_NOT_EXIST)
    job.run_after = utcnow() + timedelta(seconds=due_in)
    session.flush()
    return job
