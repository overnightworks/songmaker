"""Tests for the arq connection pool module."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

import songmaker_cli.arq_pool as pool_mod


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _isolate_pool(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(pool_mod, "_pool", None)
    yield


# ── init_arq_pool ─────────────────────────────────────────────────


def test_init_arq_pool_creates_pool() -> None:
    mock_pool = AsyncMock()
    with patch(
        "songmaker_cli.arq_pool.create_pool", new_callable=AsyncMock, return_value=mock_pool,
    ):
        result = _run(pool_mod.init_arq_pool())

    assert result is mock_pool
    assert pool_mod._pool is mock_pool


# ── get_arq_pool ──────────────────────────────────────────────────


def test_get_arq_pool_returns_existing(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_pool = AsyncMock()
    monkeypatch.setattr(pool_mod, "_pool", mock_pool)
    result = pool_mod.get_arq_pool()
    assert result is mock_pool


def test_get_arq_pool_raises_when_not_initialized() -> None:
    with pytest.raises(RuntimeError, match="arq pool not initialized"):
        pool_mod.get_arq_pool()


# ── close_arq_pool ─────────────────────────────────────────────────


def test_close_arq_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_pool = AsyncMock()
    monkeypatch.setattr(pool_mod, "_pool", mock_pool)

    _run(pool_mod.close_arq_pool())

    mock_pool.aclose.assert_called_once()
    assert pool_mod._pool is None


def test_close_arq_pool_noop_when_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pool_mod, "_pool", None)
    _run(pool_mod.close_arq_pool())


