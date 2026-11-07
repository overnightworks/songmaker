"""The adapter a worker reports is handed over only when it is the training output folder."""

from __future__ import annotations

from pathlib import Path

import pytest

from songmaker_cli.constants import (
    JOB_ERROR_INTERNAL,
    USER_LORA_TRAINING_TMP_DIRNAME,
    USER_LORAS_DIRNAME,
)
from songmaker_cli.jobs.lora_training import (
    TrainLoraTaskResultDTO,
    _sanitize_training_error,
    _validated_lora_adapter_handoff,
)

USER_ID = "u1"


@pytest.fixture
def audio_dir(tmp_path: Path) -> Path:
    return tmp_path / "audio"


@pytest.fixture
def user_folder(audio_dir: Path) -> Path:
    folder = audio_dir / USER_LORAS_DIRNAME / USER_ID
    folder.mkdir(parents=True)
    return folder


@pytest.fixture
def tmp_output(user_folder: Path) -> Path:
    output = user_folder / "L1" / USER_LORA_TRAINING_TMP_DIRNAME / "final"
    output.mkdir(parents=True)
    (output / "adapter_config.json").write_text("{}")
    return output


def _handoff(tmp_output: Path, reported: str | Path) -> Path:
    result = TrainLoraTaskResultDTO(mode="sft", adapter_dir=str(reported))
    return _validated_lora_adapter_handoff(tmp_output, result)


def test_the_reported_training_output_is_handed_over(
    tmp_output: Path,
) -> None:
    assert _handoff(tmp_output, tmp_output) == tmp_output.resolve()


def test_another_folder_inside_the_user_folder_fails_the_handoff(
    user_folder: Path,
    tmp_output: Path,
) -> None:
    other = user_folder / "L2" / "final"
    other.mkdir(parents=True)
    with pytest.raises(RuntimeError):
        _handoff(tmp_output, other)


def test_the_user_folder_itself_fails_the_handoff(
    user_folder: Path,
    tmp_output: Path,
) -> None:
    with pytest.raises(RuntimeError):
        _handoff(tmp_output, user_folder)


def test_a_path_outside_the_user_folder_fails_the_handoff_as_an_internal_error(
    tmp_output: Path,
) -> None:
    with pytest.raises(RuntimeError) as failure:
        _handoff(tmp_output, "/etc")
    assert _sanitize_training_error(failure.value, "job-1") == JOB_ERROR_INTERNAL


def test_a_link_inside_that_leads_out_fails_the_handoff(
    user_folder: Path,
    tmp_output: Path,
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    link = user_folder / "L1" / "link"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(RuntimeError):
        _handoff(tmp_output, link)


def test_a_missing_training_output_fails_the_handoff(
    tmp_output: Path,
) -> None:
    reported = tmp_output
    for child in tmp_output.iterdir():
        child.unlink()
    tmp_output.rmdir()
    with pytest.raises(RuntimeError):
        _handoff(reported, reported)


def test_a_training_output_that_is_a_file_fails_the_handoff(
    tmp_output: Path,
) -> None:
    for child in tmp_output.iterdir():
        child.unlink()
    tmp_output.rmdir()
    tmp_output.write_text("not a folder")
    with pytest.raises(RuntimeError):
        _handoff(tmp_output, tmp_output)
