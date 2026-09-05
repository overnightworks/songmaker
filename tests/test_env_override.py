"""Tests for ``songmaker_cli.env_override``."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from songmaker_cli.env_override import temporary_env_override

_KEY = "SONGMAKER_TEST_OVERRIDE"


@pytest.fixture(autouse=True)
def _clean_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv(_KEY, raising=False)
    yield


def test_override_is_visible_inside_the_block() -> None:
    with temporary_env_override(_KEY, "hidden"):
        assert os.environ[_KEY] == "hidden"


def test_absent_variable_is_absent_again_afterwards() -> None:
    with temporary_env_override(_KEY, "hidden"):
        pass

    assert _KEY not in os.environ


def test_value_set_at_runtime_is_restored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_KEY, "0,1")

    with temporary_env_override(_KEY, ""):
        assert os.environ[_KEY] == ""

    assert os.environ[_KEY] == "0,1"


def test_restore_survives_an_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_KEY, "before")

    with pytest.raises(RuntimeError), temporary_env_override(_KEY, "during"):
        raise RuntimeError("boom")

    assert os.environ[_KEY] == "before"
