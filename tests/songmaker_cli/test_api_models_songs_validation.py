"""The song request models reject values the app has no sentence for."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from songmaker_cli.api_models.songs import RepaintRequest, ScoreRequest
from songmaker_cli.constants import MODEL_AVAILABLE_MODES
from songmaker_cli.scoring.registry import VALID_SCORER_NAMES


def _repaint_request(**overrides: object) -> RepaintRequest:
    fields: dict[str, object] = {
        "src_generation_id": "take",
        "repainting_start": 0.1,
        "repainting_end": 0.5,
        "model": sorted(MODEL_AVAILABLE_MODES)[0],
    }
    return RepaintRequest(**{**fields, **overrides})


@pytest.mark.parametrize("repaint_mode", ["conservative", "balanced", "aggressive", None])
def test_repaint_request_accepts_a_documented_mode(repaint_mode: str | None) -> None:
    assert _repaint_request(repaint_mode=repaint_mode).repaint_mode == repaint_mode


def test_repaint_request_rejects_an_unknown_mode() -> None:
    with pytest.raises(ValidationError, match="repaint_mode must be one of"):
        _repaint_request(repaint_mode="reckless")


def test_score_request_accepts_every_known_scorer() -> None:
    scorers = sorted(VALID_SCORER_NAMES)
    assert ScoreRequest(scorers=scorers).scorers == scorers


def test_score_request_rejects_an_unknown_scorer_and_names_it() -> None:
    with pytest.raises(ValidationError, match="Unknown scorers: not-a-scorer"):
        ScoreRequest(scorers=[sorted(VALID_SCORER_NAMES)[0], "not-a-scorer"])
