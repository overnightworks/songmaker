"""Fixtures shared by the job modules' tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from support.lora_training_world import seed_queued_lora


@pytest.fixture
def seeded(pg_factory, tmp_path: Path) -> dict:
    return seed_queued_lora(pg_factory, tmp_path)
