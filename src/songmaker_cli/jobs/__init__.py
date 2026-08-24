"""Background job runners for generation and scoring.

The package exposes the same public surface as the pre-split ``jobs.py`` module.
External callers and tests use ``songmaker_cli.jobs.X`` for both imports
(``from songmaker_cli.jobs import run_generation_job``) and patching
(``mock.patch("songmaker_cli.jobs.dispatch_generation")``). To keep the patches
effective after the split, submodules call the patchable names through this
package namespace (``from songmaker_cli import jobs; jobs.dispatch_generation(...)``)
rather than via direct imports — that way ``mock.patch`` rebinding the attribute
on this module is observed at call time.
"""

from __future__ import annotations

import asyncio  # noqa: F401

from songmaker_cli.config import (
    audio_file_path,
    build_ace_config,
    load_generation_defaults,
    resolve_model_mode,
)
from songmaker_cli.scheduler import (
    NoCapacityError,
    WorkerTaskFailed,
    dispatch_generation,
)
from songmaker_cli.scoring.subprocess_runner import get_scorer_process

from ._runtime import (
    GenerationSetupError,
    _job_is_terminal,
    _sanitize_error,
    _touch_heartbeat,
    _update_job,
)
from .generation import (
    GenerationContext,
    _apply_cover_overrides,
    _apply_repaint_overrides,
    _auto_score_generation,
    _build_generation_context,
    _cleanup_orphaned_files,
    _create_auto_score_job,
    _dispatch_auto_score,
    _finalize_generation_job,
    _load_preset_params,
    _load_song_meta,
    _make_generation_progress_callback,
    _make_heartbeat_callback,
    _persist_generation_row,
    post_process_generation,
    run_generation_job,
)
from .lora_training import cleanup_failed_lora, run_lora_training_job
from .model_lifecycle import (
    DOWNLOAD_MAX_ATTEMPTS,
    DOWNLOAD_RETRY_BASE_DELAY_SECONDS,
    download_model_on_worker,
    load_model_on_worker,
)
from .scoring import run_scoring_job

__all__ = [
    "DOWNLOAD_MAX_ATTEMPTS",
    "DOWNLOAD_RETRY_BASE_DELAY_SECONDS",
    "GenerationContext",
    "GenerationSetupError",
    "NoCapacityError",
    "WorkerTaskFailed",
    "_apply_cover_overrides",
    "_apply_repaint_overrides",
    "_auto_score_generation",
    "_build_generation_context",
    "_cleanup_orphaned_files",
    "_create_auto_score_job",
    "_dispatch_auto_score",
    "_finalize_generation_job",
    "_job_is_terminal",
    "_load_preset_params",
    "_load_song_meta",
    "_make_generation_progress_callback",
    "_make_heartbeat_callback",
    "_persist_generation_row",
    "_sanitize_error",
    "_touch_heartbeat",
    "_update_job",
    "audio_file_path",
    "build_ace_config",
    "cleanup_failed_lora",
    "dispatch_generation",
    "download_model_on_worker",
    "get_scorer_process",
    "load_generation_defaults",
    "load_model_on_worker",
    "post_process_generation",
    "resolve_model_mode",
    "run_generation_job",
    "run_lora_training_job",
    "run_scoring_job",
]
