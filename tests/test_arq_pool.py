"""Tests for the arq connection pool module."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

import songmaker_cli.arq_pool as pool_mod


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _isolate_pool():
    saved = pool_mod._pool
    pool_mod._pool = None
    yield
    pool_mod._pool = saved


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


def test_get_arq_pool_returns_existing() -> None:
    mock_pool = AsyncMock()
    pool_mod._pool = mock_pool
    result = pool_mod.get_arq_pool()
    assert result is mock_pool


def test_get_arq_pool_raises_when_not_initialized() -> None:
    with pytest.raises(RuntimeError, match="arq pool not initialized"):
        pool_mod.get_arq_pool()


# ── close_arq_pool ─────────────────────────────────────────────────


def test_close_arq_pool() -> None:
    mock_pool = AsyncMock()
    pool_mod._pool = mock_pool

    _run(pool_mod.close_arq_pool())

    mock_pool.aclose.assert_called_once()
    assert pool_mod._pool is None


def test_close_arq_pool_noop_when_none() -> None:
    pool_mod._pool = None
    _run(pool_mod.close_arq_pool())


# ── get_queue_depth ────────────────────────────────────────────────


def test_get_queue_depth() -> None:
    mock_pool = AsyncMock()
    mock_pool.zcard = AsyncMock(return_value=5)
    pool_mod._pool = mock_pool

    result = _run(pool_mod.get_queue_depth())
    assert result == 5


def test_get_queue_depth_error_returns_zero() -> None:
    mock_pool = AsyncMock()
    mock_pool.zcard = AsyncMock(side_effect=ConnectionError)
    pool_mod._pool = mock_pool

    result = _run(pool_mod.get_queue_depth())
    assert result == 0


def test_get_queue_depth_no_pool_returns_zero() -> None:
    result = _run(pool_mod.get_queue_depth())
    assert result == 0


# ── is_worker_healthy ──────────────────────────────────────────────


def test_is_worker_healthy_true() -> None:
    mock_pool = AsyncMock()
    mock_pool.keys = AsyncMock(return_value=[b"arq:worker:test"])
    pool_mod._pool = mock_pool

    result = _run(pool_mod.is_worker_healthy())
    assert result is True


def test_is_worker_healthy_false() -> None:
    mock_pool = AsyncMock()
    mock_pool.keys = AsyncMock(return_value=[])
    pool_mod._pool = mock_pool

    result = _run(pool_mod.is_worker_healthy())
    assert result is False


def test_is_worker_healthy_error() -> None:
    mock_pool = AsyncMock()
    mock_pool.keys = AsyncMock(side_effect=ConnectionError)
    pool_mod._pool = mock_pool

    result = _run(pool_mod.is_worker_healthy())
    assert result is False


# ── get_active_model ───────────────────────────────────────────────


def test_get_active_model() -> None:
    mock_pool = AsyncMock()
    mock_pool.get = AsyncMock(return_value=b"sft")
    pool_mod._pool = mock_pool

    result = _run(pool_mod.get_active_model())
    assert result == "sft"


def test_get_active_model_none() -> None:
    mock_pool = AsyncMock()
    mock_pool.get = AsyncMock(return_value=None)
    pool_mod._pool = mock_pool

    result = _run(pool_mod.get_active_model())
    assert result is None


def test_get_active_model_error() -> None:
    mock_pool = AsyncMock()
    mock_pool.get = AsyncMock(side_effect=ConnectionError)
    pool_mod._pool = mock_pool

    result = _run(pool_mod.get_active_model())
    assert result is None
