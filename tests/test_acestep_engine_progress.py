"""ACE-Step's progress value, read as a phase and how far that phase has come."""

from __future__ import annotations

import pytest

from acestep_engine.models import ResultItem
from acestep_engine.progress import (
    RENDERING_ENDS_AT,
    RENDERING_STARTS_AT,
    WRITING_STARTS_AT,
    AceStepPhase,
    progress_from_result,
)


def test_the_phase_marks_are_the_forks_own_progress_calls() -> None:
    assert (WRITING_STARTS_AT, RENDERING_STARTS_AT, RENDERING_ENDS_AT) == (0.1, 0.51, 0.99)


@pytest.mark.parametrize(
    ("server_progress", "phase", "fraction"),
    [
        (0.0, AceStepPhase.WRITING, 0.0),
        (0.01, AceStepPhase.WRITING, 0.0),
        (0.1, AceStepPhase.WRITING, 0.0),
        (0.5, AceStepPhase.WRITING, (0.5 - 0.1) / (0.51 - 0.1)),
        (0.51, AceStepPhase.RENDERING, 0.0),
        (0.52, AceStepPhase.RENDERING, (0.52 - 0.51) / (0.99 - 0.51)),
        (0.8, AceStepPhase.RENDERING, (0.8 - 0.51) / (0.99 - 0.51)),
        (0.99, AceStepPhase.RENDERING, 1.0),
        (1.0, AceStepPhase.RENDERING, 1.0),
    ],
)
def test_a_progress_value_maps_to_its_phase_and_fraction(
    server_progress: float, phase: AceStepPhase, fraction: float,
) -> None:
    progress = progress_from_result(ResultItem(progress=server_progress))

    assert progress is not None
    assert progress.phase == phase
    assert progress.fraction == pytest.approx(fraction)


def test_an_entry_without_a_progress_value_has_no_phase() -> None:
    assert progress_from_result(ResultItem()) is None
