"""Codex CLI process admission tests."""

from __future__ import annotations

import pytest

from songmaker_cli.cowriter.codex_process_pool import CodexProcessKind, CodexProcessPool
from songmaker_cli.cowriter.errors import CodexProcessPoolSaturatedError


def test_total_cap_counts_text_cover_and_unspawned_reservations() -> None:
    pool = CodexProcessPool(maximum_processes=2, maximum_cover_runs=1)
    pool.reserve(CodexProcessKind.TEXT)
    pool.reserve(CodexProcessKind.COVER)

    with pytest.raises(CodexProcessPoolSaturatedError) as raised:
        pool.reserve(CodexProcessKind.TEXT)

    assert raised.value.scope == "total"


def test_cover_cap_leaves_capacity_for_a_text_turn() -> None:
    pool = CodexProcessPool(maximum_processes=3, maximum_cover_runs=1)
    pool.reserve(CodexProcessKind.COVER)

    with pytest.raises(CodexProcessPoolSaturatedError) as raised:
        pool.reserve(CodexProcessKind.COVER)

    assert raised.value.scope == "cover"
    pool.reserve(CodexProcessKind.TEXT)
    assert pool.reservation_count() == 2


def test_reservation_remains_held_from_bind_until_reap() -> None:
    pool = CodexProcessPool(maximum_processes=1, maximum_cover_runs=1)
    reservation = pool.reserve(CodexProcessKind.COVER)
    pool.bind(reservation, 42)

    with pytest.raises(CodexProcessPoolSaturatedError):
        pool.reserve(CodexProcessKind.TEXT)

    pool.reap(reservation, 42)
    pool.reserve(CodexProcessKind.TEXT)


def test_unspawned_reservation_is_released_after_spawn_failure() -> None:
    pool = CodexProcessPool(maximum_processes=1, maximum_cover_runs=1)
    reservation = pool.reserve(CodexProcessKind.TEXT)

    pool.abandon_unspawned(reservation)

    pool.reserve(CodexProcessKind.TEXT)


def test_zombie_reservation_blocks_new_processes_until_background_reap() -> None:
    pool = CodexProcessPool(maximum_processes=1, maximum_cover_runs=1)
    reservation = pool.reserve(CodexProcessKind.TEXT)
    pool.bind(reservation, 99)

    with pytest.raises(CodexProcessPoolSaturatedError):
        pool.reserve(CodexProcessKind.TEXT)

    pool.reap(reservation, 99)
    assert pool.reservation_count() == 0
