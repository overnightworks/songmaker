"""The arguments of a generate job as its handler receives them."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast

from songmaker_cli.generation_params import CoverTaskParams, RepaintTaskParams
from songmaker_cli.job_payloads import GeneratePayload


@dataclass(frozen=True)
class GenerationJobRequest:
    """The arguments of a generate job; audio_dir and data_dir are the worker's local paths."""

    job_id: str
    song_id: str
    version_id: str
    count: int
    user_id: str
    audio_dir: Path
    data_dir: Path
    seed: int | None
    target_model: str
    repaint_params: RepaintTaskParams | None
    cover_params: CoverTaskParams | None

    def with_takes_left(self, count: int) -> GenerationJobRequest:
        return cast(GenerationJobRequest, replace(self, count=count))

    def payload(self) -> GeneratePayload:
        return GeneratePayload(
            song_id=self.song_id, version_id=self.version_id, count=self.count,
            user_id=self.user_id, seed=self.seed, target_model=self.target_model,
            task_params=self.repaint_params or self.cover_params,
        )
