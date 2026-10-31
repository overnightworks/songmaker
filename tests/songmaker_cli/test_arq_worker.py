import subprocess
import sys
import textwrap

import pytest

# A fresh interpreter keeps arq's sys.path, logging and signal-handler changes out of pytest.
WORKER_START_PROGRAM = textwrap.dedent(
    """
    import sys

    from arq import cli as arq_cli
    from arq.worker import create_worker

    from songmaker_cli import arq_worker


    def construct_instead_of_run(settings, **_):
        create_worker(settings).loop.close()


    arq_cli.run_worker = construct_instead_of_run
    sys.argv = ["arq_worker", sys.argv[1]]
    arq_worker.main()
    """
)


@pytest.mark.parametrize(
    "settings_path",
    [
        "songmaker_cli.music_worker.MusicWorkerSettings",
        "songmaker_cli.scoring_worker.ScoringWorkerSettings",
    ],
)
def test_entry_lets_arq_construct_its_worker_without_a_current_loop(settings_path: str) -> None:
    result = subprocess.run(  # noqa: S603 - fixed interpreter and program
        [sys.executable, "-c", WORKER_START_PROGRAM, settings_path],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )

    assert "no current event loop" not in result.stderr
    assert result.returncode == 0, result.stderr
