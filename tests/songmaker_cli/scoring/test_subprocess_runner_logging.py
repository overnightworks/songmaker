"""The scorer child writes its failures and crashes as logline JSON lines."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from songmaker_cli.scoring.pipeline import PipelineConfig
from songmaker_cli.scoring.subprocess_runner import ScorerProcess


def test_a_scorer_failing_in_the_child_is_one_json_line_with_its_exception(
    tmp_path: Path, capfd: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    mp3 = tmp_path / "test.mp3"
    mp3.write_bytes(b"fake")
    monkeypatch.delenv("SCORING_AUDIOBOX_CHECKPOINT", raising=False)

    sp = ScorerProcess()
    try:
        sp.score(
            mp3, scorers=["audiobox"], config=PipelineConfig(device="cpu"),
            on_progress=lambda _completed, _total, _scorer: None,
        )
    finally:
        sp.shutdown()

    lines = [json.loads(line) for line in capfd.readouterr().out.splitlines()]
    (failure,) = [line for line in lines if line["level"] == "error"]
    assert "SCORING_AUDIOBOX_CHECKPOINT" in failure["exception"]


def test_a_scorer_process_that_crashes_leaves_one_json_line_with_its_traceback() -> None:
    crash_on_first_message = (
        "from songmaker_cli.scoring.subprocess_runner import _logged_child_main;"
        "_logged_child_main(object())"
    )

    completed = subprocess.run(  # noqa: S603 - runs this interpreter on a fixed program
        [sys.executable, "-I", "-c", crash_on_first_message],
        capture_output=True, text=True, timeout=60, check=False,
    )

    lines = [json.loads(line) for line in completed.stdout.splitlines()]
    (crash,) = [line for line in lines if line["level"] == "critical"]
    assert completed.returncode != 0
    assert "Traceback" in crash["exception"]
