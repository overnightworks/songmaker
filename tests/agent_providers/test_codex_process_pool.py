"""Codex CLI process admission tests."""

from __future__ import annotations

import pytest
from conftest import override_provider_runtime

from agent_providers.codex.pool import (
    CodexProcessKind,
    CodexProcessPool,
    get_codex_process_pool,
)
from agent_providers.errors import CodexProcessPoolSaturatedError


def test_the_process_wide_pool_admits_only_as_many_runs_as_the_runtime_allows() -> None:
    override_provider_runtime(
        codex_max_concurrent_processes=2,
        codex_max_concurrent_image_runs=1,
    )

    get_codex_process_pool().reserve(CodexProcessKind.IMAGE)

    with pytest.raises(CodexProcessPoolSaturatedError) as raised:
        get_codex_process_pool().reserve(CodexProcessKind.IMAGE)

    assert raised.value.scope == "image"


def test_every_caller_shares_the_one_process_wide_pool() -> None:
    assert get_codex_process_pool() is get_codex_process_pool()



def test_total_cap_counts_text_image_and_unspawned_reservations() -> None:
    pool = CodexProcessPool(maximum_processes=2, maximum_image_runs=1)
    pool.reserve(CodexProcessKind.TEXT)
    pool.reserve(CodexProcessKind.IMAGE)

    with pytest.raises(CodexProcessPoolSaturatedError) as raised:
        pool.reserve(CodexProcessKind.TEXT)

    assert raised.value.scope == "total"


def test_image_cap_leaves_capacity_for_a_text_turn() -> None:
    pool = CodexProcessPool(maximum_processes=3, maximum_image_runs=1)
    pool.reserve(CodexProcessKind.IMAGE)

    with pytest.raises(CodexProcessPoolSaturatedError) as raised:
        pool.reserve(CodexProcessKind.IMAGE)

    assert raised.value.scope == "image"
    pool.reserve(CodexProcessKind.TEXT)
    assert pool.reservation_count() == 2


def test_reservation_remains_held_from_bind_until_reap() -> None:
    pool = CodexProcessPool(maximum_processes=1, maximum_image_runs=1)
    reservation = pool.reserve(CodexProcessKind.IMAGE)
    pool.bind(reservation, 42)

    with pytest.raises(CodexProcessPoolSaturatedError):
        pool.reserve(CodexProcessKind.TEXT)

    pool.reap(reservation, 42)
    pool.reserve(CodexProcessKind.TEXT)


def test_unspawned_reservation_is_released_after_spawn_failure() -> None:
    pool = CodexProcessPool(maximum_processes=1, maximum_image_runs=1)
    reservation = pool.reserve(CodexProcessKind.TEXT)

    pool.abandon_unspawned(reservation)

    pool.reserve(CodexProcessKind.TEXT)


def test_zombie_reservation_blocks_new_processes_until_background_reap() -> None:
    pool = CodexProcessPool(maximum_processes=1, maximum_image_runs=1)
    reservation = pool.reserve(CodexProcessKind.TEXT)
    pool.bind(reservation, 99)

    with pytest.raises(CodexProcessPoolSaturatedError):
        pool.reserve(CodexProcessKind.TEXT)

    pool.reap(reservation, 99)
    assert pool.reservation_count() == 0
