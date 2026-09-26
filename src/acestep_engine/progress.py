"""How far one ACE-Step generation has come, read from the server's own marks.

ACE-Step reports a single ``progress`` value between 0 and 1 on every
running ``/query_result`` entry. The value is not linear in time: the fork
places fixed marks at its phase boundaries, and this module turns the value
into the phase it lies in plus how far that phase has come.

The marks, as set by the vendored fork:

* ``0.1`` — ``llm_inference.py``, "Phase 1: Generating CoT metadata": the
  language model starts writing. ``0.5`` ("Phase 2: Generating audio codes")
  still belongs to writing.
* ``0.51`` — ``core/generation/handler/generate_music.py``, "Preparing
  inputs...": the diffusion model starts rendering; the background
  estimator in ``generate_music_execute.py`` then moves 0.52..0.79 and the
  decode step sits at 0.8.
* ``0.99`` — ``core/generation/handler/generate_music_payload.py``,
  "Preparing audio data...": rendering is done. The job store
  (``api/jobs/store.py``) writes 1.0 only on success, which arrives as a
  completed entry, never as progress.

Before the first mark the value is the job store's own floor. It stays
``0.0`` while the server loads the models it deferred at startup
(``ACESTEP_NO_INIT``): ``api/job_execution_runtime.py`` awaits
``ensure_models_initialized`` before ``mark_running`` (``api/jobs/store.py``)
raises it to ``0.01``. A task below that mark has not started, so it is still
loading its model; from ``0.01`` on it is writing. A generation without the
language model skips writing and jumps straight to the rendering mark.

The free-text ``progress_text`` is never read here: it carries whatever the
server logged last (checkpoint loading bars, LM chunk counters), which is
why parsing it made the percent jump and fall back.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from acestep_engine.models import ResultItem

RUNNING_STARTS_AT: Final[float] = 0.01
WRITING_STARTS_AT: Final[float] = 0.1
RENDERING_STARTS_AT: Final[float] = 0.51
RENDERING_ENDS_AT: Final[float] = 0.99


class AceStepPhase(StrEnum):
    """The stretch of an ACE-Step generation the worker is in."""

    LOADING_MODEL = "loading_model"
    WRITING = "writing"
    RENDERING = "rendering"


@dataclass(frozen=True)
class AceStepProgress:
    """A phase and how far it has come, from 0.0 to 1.0."""

    phase: AceStepPhase
    fraction: float


NOT_STARTED: Final[AceStepProgress] = AceStepProgress(AceStepPhase.LOADING_MODEL, 0.0)
"""Where a generation stands before ACE-Step has started running it."""


def progress_from_result(item: ResultItem) -> AceStepProgress | None:
    """Read the phase and its fraction from one running result entry.

    Returns ``None`` when the entry carries no progress value at all.
    """
    if item.progress is None:
        return None
    if item.progress < RUNNING_STARTS_AT:
        return NOT_STARTED
    if item.progress < RENDERING_STARTS_AT:
        return AceStepProgress(
            AceStepPhase.WRITING,
            _fraction_between(item.progress, WRITING_STARTS_AT, RENDERING_STARTS_AT),
        )
    return AceStepProgress(
        AceStepPhase.RENDERING,
        _fraction_between(item.progress, RENDERING_STARTS_AT, RENDERING_ENDS_AT),
    )


def _fraction_between(value: float, start: float, end: float) -> float:
    return min(max((value - start) / (end - start), 0.0), 1.0)
