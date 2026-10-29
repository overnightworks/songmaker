from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from acestep_engine.errors import AceStepError
from acestep_engine.models import AceStepConfig
from acestep_engine.progress import AceStepPhase, AceStepProgress
from acestep_worker.task_store import TaskStore
from acestep_worker.wrapper import default_generate_runner


@pytest.mark.parametrize(("engine_error", "expected_state", "expected_error"), [
    (None, "done", None),
    ("engine exploded", "error", "engine exploded"),
])
def test_runner_outcome_ignores_a_failed_progress_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    engine_error: str | None,
    expected_state: str,
    expected_error: str | None,
) -> None:
    def generate(ace_config, on_progress=None):
        on_progress(AceStepProgress(AceStepPhase.WRITING, 0.5))
        if engine_error is not None:
            raise AceStepError(engine_error)
        return MagicMock(
            wav_bytes=b"WAV", seed=1, cot_caption="", cot_lyrics="", delivered_batch_size=None,
        )

    client_class = MagicMock()
    client_class.return_value.generate = generate
    monkeypatch.setitem(sys.modules, "acestep_engine.client", MagicMock(AceStepClient=client_class))

    async def go():
        store = TaskStore()
        task_id = await store.create("generate", phase=AceStepPhase.WRITING)

        async def failing_update_progress(*args, **kwargs):
            raise RuntimeError("progress write failed")

        monkeypatch.setattr(store, "update_progress", failing_update_progress)
        await default_generate_runner(
            store, task_id, mode="sft", config=AceStepConfig(prompt="x", lyrics=""),
            port=8101, audio_output_dir=tmp_path / "audio",
        )
        return await store.get(task_id)

    snapshot = asyncio.run(go())
    assert snapshot is not None
    assert (snapshot.state, snapshot.error) == (expected_state, expected_error)
    assert (snapshot.result is not None) == (engine_error is None)
