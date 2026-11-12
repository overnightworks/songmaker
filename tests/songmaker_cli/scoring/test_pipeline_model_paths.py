"""The two model scorers load their weights from the configured path and nowhere else."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from songmaker_cli.jobs.scoring import ScoringInput, run_scoring_job
from songmaker_cli.parser import SongMeta
from songmaker_cli.scoring import audiobox_aesthetics, text_accuracy
from songmaker_cli.scoring.pipeline import (
    SCORING_AUDIOBOX_CHECKPOINT_SETTING,
    SCORING_WHISPER_MODEL_DIR_SETTING,
    PipelineConfig,
)


@dataclass(frozen=True)
class ModelScorer:
    """One model scorer, the library class it constructs and the setting it reads."""

    setting: str
    library_module: str
    library_class: str
    config_field: str
    score: Callable[..., object]
    make_path: Callable[[Path], Path]

    def config(self, path: Path | None) -> PipelineConfig:
        return PipelineConfig(device="cpu", **{self.config_field: path})

    def stub_library(self) -> AbstractContextManager[MagicMock]:
        pytest.importorskip(self.library_module)
        stub = MagicMock()
        stub.return_value.forward.return_value = [{"CE": 7.5, "CU": 6.0, "PC": 8.0, "PQ": 7.0}]
        stub.return_value.transcribe.return_value = (iter(()), MagicMock(language="en"))
        return patch(f"{self.library_module}.{self.library_class}", stub)


def _make_directory(parent: Path) -> Path:
    directory = parent / "whisper"
    directory.mkdir()
    return directory


def _make_file(parent: Path) -> Path:
    checkpoint = parent / "checkpoint.pt"
    checkpoint.write_bytes(b"weights")
    return checkpoint


WHISPER = ModelScorer(
    setting=SCORING_WHISPER_MODEL_DIR_SETTING,
    library_module="faster_whisper",
    library_class="WhisperModel",
    config_field="whisper_model_dir",
    score=text_accuracy.score_text_accuracy,
    make_path=_make_directory,
)
AUDIOBOX = ModelScorer(
    setting=SCORING_AUDIOBOX_CHECKPOINT_SETTING,
    library_module="audiobox_aesthetics.infer",
    library_class="AesPredictor",
    config_field="audiobox_checkpoint",
    score=audiobox_aesthetics.score_audiobox,
    make_path=_make_file,
)
MODEL_SCORERS = pytest.mark.parametrize(
    "scorer", [WHISPER, AUDIOBOX], ids=["whisper", "audiobox"],
)


@pytest.fixture(autouse=True)
def _empty_model_caches() -> Iterator[None]:
    text_accuracy.clear_cache()
    audiobox_aesthetics.clear_cache()
    yield
    text_accuracy.clear_cache()
    audiobox_aesthetics.clear_cache()


@MODEL_SCORERS
def test_scorer_loads_the_model_from_the_configured_path(
    scorer: ModelScorer, tmp_path: Path,
) -> None:
    path = scorer.make_path(tmp_path)

    with scorer.stub_library() as library:
        scorer.score(tmp_path / "take.mp3", config=scorer.config(path))

    call = library.call_args
    assert str(path) in [str(argument) for argument in (*call.args, *call.kwargs.values())]


def test_whisper_never_resolves_a_model_through_the_hub(tmp_path: Path) -> None:
    path = WHISPER.make_path(tmp_path)

    with WHISPER.stub_library() as library:
        WHISPER.score(tmp_path / "take.mp3", config=WHISPER.config(path))

    assert library.call_args.kwargs["local_files_only"] is True


@MODEL_SCORERS
def test_scorer_without_a_configured_path_fails_naming_the_setting(
    scorer: ModelScorer, tmp_path: Path,
) -> None:
    with scorer.stub_library() as library, pytest.raises(ValueError, match=scorer.setting):
        scorer.score(tmp_path / "take.mp3", config=scorer.config(None))

    library.assert_not_called()


@MODEL_SCORERS
def test_scorer_with_a_missing_path_fails_instead_of_asking_the_hub(
    scorer: ModelScorer, tmp_path: Path,
) -> None:
    with scorer.stub_library() as library, pytest.raises(FileNotFoundError, match=scorer.setting):
        scorer.score(tmp_path / "take.mp3", config=scorer.config(tmp_path / "absent"))

    library.assert_not_called()


def _scoring_job_config(
    scorer: ModelScorer, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, configured: str | None,
) -> PipelineConfig:
    """The scorer configuration the parent builds from the environment for one scoring run."""
    if configured is None:
        monkeypatch.delenv(scorer.setting, raising=False)
    else:
        monkeypatch.setenv(scorer.setting, configured)
    (tmp_path / "take.mp3").write_bytes(b"audio")
    child = MagicMock()
    job_module = "songmaker_cli.jobs.scoring"
    with (
        patch("songmaker_cli.jobs.get_scorer_process", return_value=child),
        patch(f"{job_module}._job_is_terminal", return_value=False),
        patch(f"{job_module}._update_job"),
        patch(
            f"{job_module}._load_scoring_input",
            return_value=ScoringInput(mp3_path_rel="take.mp3", meta=SongMeta()),
        ),
        patch(f"{job_module}._persist_scores", return_value=False),
    ):
        run_scoring_job("job", "gen", None, db_factory=MagicMock(), audio_dir=tmp_path)
    return child.score.call_args.kwargs["config"]


@MODEL_SCORERS
def test_scoring_job_passes_the_configured_path_to_the_scorer_configuration(
    scorer: ModelScorer, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    path = scorer.make_path(tmp_path)

    config = _scoring_job_config(scorer, monkeypatch, tmp_path, str(path))

    assert getattr(config, scorer.config_field) == path


@MODEL_SCORERS
@pytest.mark.parametrize("configured", [None, ""], ids=["unset", "empty"])
def test_scoring_job_without_a_configured_path_fails_at_the_first_load_naming_the_setting(
    scorer: ModelScorer, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, configured: str | None,
) -> None:
    config = _scoring_job_config(scorer, monkeypatch, tmp_path, configured)

    with scorer.stub_library() as library, pytest.raises(ValueError, match=scorer.setting):
        scorer.score(tmp_path / "take.mp3", config=config)

    library.assert_not_called()

