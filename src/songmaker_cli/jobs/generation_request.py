"""The arguments of a generate job as its handler receives them."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast

from songmaker_cli.generation_params import CoverTaskParams, RepaintTaskParams
from songmaker_cli.job_payloads import GeneratePayload


@dataclass(frozen=True)
class GenerationJobRequest:
    """Keep audio_dir/data_dir out of queue_args() because the worker supplies its local paths."""

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

    def queue_args(
        self,
    ) -> tuple[str, str, str, int, str, int | None, str, dict | None, dict | None]:
        return (
            self.job_id,
            self.song_id,
            self.version_id,
            self.count,
            self.user_id,
            self.seed,
            self.target_model,
            self.repaint_params.model_dump() if self.repaint_params is not None else None,
            self.cover_params.model_dump() if self.cover_params is not None else None,
        )
