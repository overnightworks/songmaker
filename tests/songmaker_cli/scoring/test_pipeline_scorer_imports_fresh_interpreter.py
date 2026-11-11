"""A fresh scoring child imports every scorer dependency before the scorer threads start."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from support.repository_root import REPOSITORY_ROOT

from songmaker_cli.scoring.models import ScorerOutcome

CPU_SCORERS = ("bpm_accuracy", "emotional_dynamics", "silence", "spectral_quality")
SIGNAL_SECONDS = 12

# Runs in a fresh interpreter so no import of the test process hides a first import.
# The finder sees each module's first import attempt and passes it on unchanged.
CHILD_SCRIPT = """
import json
import sys
import threading
from pathlib import Path

import numpy as np
import soundfile

SAMPLE_RATE = 22050
audio_path = Path(sys.argv[1])
scorers = sys.argv[2].split(",")
seconds = int(sys.argv[3])

first_import_threads = {}
# librosa and scipy attach submodules lazily. numba's first compile loads its own
# modules, serialised by numba's compiler lock.
LAZY_PACKAGES = ("librosa.", "scipy.")


class FirstImportRecorder:
    def find_spec(self, name, path=None, target=None):
        first_import_threads.setdefault(name, threading.current_thread().name)
        return None


time = np.arange(seconds * SAMPLE_RATE) / SAMPLE_RATE
tone = 0.3 * np.sin(2 * np.pi * 220 * time) * (1 + np.sin(2 * np.pi * 2 * time)) / 2
soundfile.write(str(audio_path), tone.astype(np.float32), SAMPLE_RATE)

sys.meta_path.insert(0, FirstImportRecorder())

from songmaker_cli.parser import SongMeta
from songmaker_cli.scoring.pipeline import default_registry, run_scoring_pipeline

default_registry.ensure_loaded()
scores = run_scoring_pipeline(
    audio_path,
    SongMeta(bpm=120),
    scorers=scorers,
    on_progress=lambda completed, total, scorer: None,
)

outside_main_thread = sorted(
    name
    for name, thread in first_import_threads.items()
    if thread != "MainThread" and name in sys.modules and name.startswith(LAZY_PACKAGES)
)
print(json.dumps({
    "outside_main_thread": outside_main_thread,
    "outcomes": {run.scorer: run.outcome.value for run in scores.runs},
}))
"""


def test_scorer_threads_import_nothing_for_the_first_time(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable, "-c", CHILD_SCRIPT,
            str(tmp_path / "synthetic.wav"), ",".join(CPU_SCORERS), str(SIGNAL_SECONDS),
        ],
        cwd=REPOSITORY_ROOT,
        env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.splitlines()[-1])

    assert report["outside_main_thread"] == [], (
        "modules first imported in a scorer thread: "
        + ", ".join(report["outside_main_thread"])
    )
    assert report["outcomes"] == {name: ScorerOutcome.OK.value for name in CPU_SCORERS}
