import asyncio
import sys
from collections.abc import Iterator

import pytest
from arq import cli as arq_cli
from arq.worker import create_worker

from songmaker_cli import arq_worker


@pytest.fixture
def no_current_event_loop() -> Iterator[None]:
    asyncio.set_event_loop(None)
    yield
    asyncio.set_event_loop(None)


@pytest.mark.parametrize(
    "settings_path",
    [
        "songmaker_cli.music_worker.MusicWorkerSettings",
        "songmaker_cli.scoring_worker.ScoringWorkerSettings",
    ],
)
def test_entry_lets_arq_construct_its_worker_without_a_current_loop(
    settings_path: str, monkeypatch: pytest.MonkeyPatch, no_current_event_loop: None
) -> None:
    constructed = []

    def construct_instead_of_run(settings: object, **_: object) -> None:
        worker = create_worker(settings)
        constructed.append(worker)
        worker.loop.close()

    monkeypatch.setattr(arq_cli, "run_worker", construct_instead_of_run)
    monkeypatch.setattr(sys, "argv", ["arq_worker", settings_path])

    with pytest.raises(SystemExit):
        arq_worker.main()

    assert len(constructed) == 1
