"""WorkerSettings reads the internal token from a secrets directory."""

from __future__ import annotations

from pathlib import Path

import pytest

from acestep_worker.settings import WorkerSettings


@pytest.fixture(autouse=True)
def _worker_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKER_ID", "worker-1")
    monkeypatch.setenv("REDIS_URL", "redis://example")
    monkeypatch.delenv("SONGMAKER_INTERNAL_TOKEN", raising=False)


def test_a_token_file_sets_the_internal_token(tmp_path: Path) -> None:
    (tmp_path / "songmaker_internal_token").write_text("from-file\n")

    settings = WorkerSettings(_secrets_dir=tmp_path)

    assert settings.songmaker_internal_token.get_secret_value() == "from-file"


def test_the_environment_wins_over_the_token_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "songmaker_internal_token").write_text("from-file")
    monkeypatch.setenv("SONGMAKER_INTERNAL_TOKEN", "from-environment")

    settings = WorkerSettings(_secrets_dir=tmp_path)

    assert settings.songmaker_internal_token.get_secret_value() == "from-environment"


def test_an_empty_token_file_is_refused(tmp_path: Path) -> None:
    (tmp_path / "songmaker_internal_token").write_text("")

    with pytest.raises(ValueError, match="songmaker_internal_token"):
        WorkerSettings(_secrets_dir=tmp_path)
