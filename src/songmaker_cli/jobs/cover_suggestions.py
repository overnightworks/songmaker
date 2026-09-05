"""Music-worker handoff to the shared cover-job execution owner."""

from __future__ import annotations

import asyncio
from pathlib import Path

from songmaker_cli.constants import JobStatus
from songmaker_cli.cover_job_errors import CoverSuggestionJobError
from songmaker_cli.cowriter.codex_cli_adapter import generate_codex_cover_image
from songmaker_cli.cowriter.dispatch import cover_image_provider_method
from songmaker_cli.jobs._runtime import _update_job
from songmaker_cli.settings import Settings, get_settings


def build_cover_prompt(album, songs) -> str:
    """Delegate prompt construction to the shared cover execution owner."""
    from songmaker_cli.cover_runner import build_cover_prompt as _build_cover_prompt

    return _build_cover_prompt(album, songs)


async def run_cover_suggestion_job(
    job_id: str,
    *,
    db_factory,
    audio_dir: Path,
    settings: Settings | None = None,
) -> None:
    """Claim the arq-delivered job, then use the shared cover execution path."""
    settings = settings or get_settings()
    started = await asyncio.to_thread(_update_job, db_factory, job_id, JobStatus.RUNNING)
    if not started:
        return
    from songmaker_cli.cover_runner import run_claimed_cover_suggestion_job

    await run_claimed_cover_suggestion_job(
        job_id,
        db_factory=db_factory,
        audio_dir=audio_dir,
        settings=settings,
        image_generator=generate_codex_cover_image,
        provider_method=cover_image_provider_method,
    )


__all__ = ["CoverSuggestionJobError", "build_cover_prompt", "run_cover_suggestion_job"]
