from __future__ import annotations

import asyncio
from typing import Any

import pytest

from acestep_worker.model_cache import (
    CapacityError,
    LoadedModel,
    LoadedModelInfo,
    ModelCache,
    ModelNotLoadedError,
    UnknownModeError,
    VramStats,
)


def _run(coro):
    return asyncio.run(coro)


def _make_cache(
    *,
    budget: float = 24.0,
    sizes: dict[str, float] | None = None,
    vram_reader=None,
):
    sizes = sizes or {"sft": 6.0, "xl-sft": 12.0, "huge": 30.0}
    loaded_log: list[str] = []
    unloaded_log: list[LoadedModel] = []

    async def loader(mode: str) -> LoadedModel:
        loaded_log.append(mode)
        return LoadedModel(mode=mode, handle=f"handle-{mode}", port=8101)

    async def unloader(model: LoadedModel) -> None:
        unloaded_log.append(model)

    cache = ModelCache(
        vram_budget_gb=budget,
        model_sizes=sizes,
        loader=loader,
        unloader=unloader,
        vram_reader=vram_reader,
    )
    return cache, loaded_log, unloaded_log


def test_initial_state() -> None:
    cache, _, _ = _make_cache()
    assert cache.loaded_modes() == []
    assert cache.target_loading is None
    assert cache.snapshot().vram_used_gb == 0.0
    assert cache.vram_budget_gb == 24.0


def test_load_unknown_mode_raises() -> None:
    cache, _, _ = _make_cache()
    with pytest.raises(UnknownModeError):
        _run(cache.load("nonexistent"))


def test_load_too_big_raises_capacity() -> None:
    cache, _, _ = _make_cache()
    with pytest.raises(CapacityError):
        _run(cache.load("huge"))


def test_load_single_model() -> None:
    cache, loaded_log, _ = _make_cache()
    result = _run(cache.load("sft"))
    assert result.loaded == ["sft"]
    assert result.evicted == []
    assert cache.loaded_modes() == ["sft"]
    assert cache.snapshot().vram_used_gb == 6.0
    assert loaded_log == ["sft"]


def test_load_idempotent_no_reload() -> None:
    cache, loaded_log, _ = _make_cache()
    _run(cache.load("sft"))
    result = _run(cache.load("sft"))
    assert result.loaded == ["sft"]
    assert result.evicted == []
    assert loaded_log == ["sft"]


def test_load_lru_eviction_lru1() -> None:
    cache, loaded_log, unloaded_log = _make_cache(budget=12.0)
    _run(cache.load("sft"))
    result = _run(cache.load("xl-sft"))
    assert result.loaded == ["xl-sft"]
    assert result.evicted == ["sft"]
    assert cache.loaded_modes() == ["xl-sft"]
    assert len(unloaded_log) == 1
    assert unloaded_log[0].mode == "sft"


def test_load_multi_model_no_eviction_when_fits() -> None:
    cache, _, _ = _make_cache(budget=24.0)
    _run(cache.load("sft"))
    result = _run(cache.load("xl-sft"))
    assert sorted(result.loaded) == ["sft", "xl-sft"]
    assert result.evicted == []
    assert cache.snapshot().vram_used_gb == 18.0


def test_load_multi_then_evict_oldest() -> None:
    cache, _, unloaded_log = _make_cache(budget=18.0)
    _run(cache.load("sft"))
    _run(cache.load("xl-sft"))
    cache._loaded.move_to_end("sft")
    result = _run(cache.load("xl-sft"))
    assert result.loaded == ["sft", "xl-sft"]
    assert result.evicted == []
    assert unloaded_log == []


def test_load_evicts_lru_first() -> None:
    cache, _, unloaded_log = _make_cache(budget=12.0, sizes={"a": 6.0, "b": 6.0, "c": 6.0})
    _run(cache.load("a"))
    _run(cache.load("b"))
    result = _run(cache.load("c"))
    assert "a" in result.evicted
    assert "c" in cache.loaded_modes()
    assert len(unloaded_log) >= 1


def test_evict_known_mode() -> None:
    cache, _, unloaded_log = _make_cache()
    _run(cache.load("sft"))
    evicted = _run(cache.evict("sft"))
    assert evicted == ["sft"]
    assert cache.loaded_modes() == []
    assert len(unloaded_log) == 1


def test_evict_unknown_mode_returns_empty() -> None:
    cache, _, unloaded_log = _make_cache()
    evicted = _run(cache.evict("sft"))
    assert evicted == []
    assert unloaded_log == []


def test_evict_all() -> None:
    cache, _, unloaded_log = _make_cache(budget=24.0)
    _run(cache.load("sft"))
    _run(cache.load("xl-sft"))
    evicted = _run(cache.evict_all())
    assert sorted(evicted) == ["sft", "xl-sft"]
    assert cache.loaded_modes() == []
    assert len(unloaded_log) == 2


def test_evict_all_empty() -> None:
    cache, _, _ = _make_cache()
    evicted = _run(cache.evict_all())
    assert evicted == []


def test_get_loaded_returns_handle() -> None:
    cache, _, _ = _make_cache()
    _run(cache.load("sft"))
    model = cache.get_loaded("sft")
    assert model is not None
    assert model.mode == "sft"
    assert cache.get_loaded("nope") is None


def test_target_loading_set_during_load() -> None:
    target_during_load: list[str | None] = []

    async def slow_loader(mode: str) -> LoadedModel:
        target_during_load.append(cache.target_loading)
        return LoadedModel(mode=mode, handle=None, port=8101)

    async def unloader(_: LoadedModel) -> None:
        pass

    cache = ModelCache(
        vram_budget_gb=24.0,
        model_sizes={"sft": 6.0},
        loader=slow_loader,
        unloader=unloader,
    )
    _run(cache.load("sft"))
    assert target_during_load == ["sft"]
    assert cache.target_loading is None


def test_snapshot_initial_state() -> None:
    cache, _, _ = _make_cache()
    snap = cache.snapshot()
    assert snap.loaded == ()
    assert snap.target_loading is None
    assert snap.vram_used_gb == 0.0
    assert snap.vram_total_gb == 24.0


def test_snapshot_after_load_is_consistent() -> None:
    cache, _, _ = _make_cache()
    _run(cache.load("sft"))
    snap = cache.snapshot()
    assert snap.loaded == (LoadedModelInfo(mode="sft", size_gb=6.0),)
    assert snap.vram_used_gb == 6.0
    assert snap.target_loading is None
    assert snap.pinned == ()
    assert snap.loading_started_at is None


def test_snapshot_is_immutable_against_subsequent_mutation() -> None:
    cache, _, _ = _make_cache()
    _run(cache.load("sft"))
    snap = cache.snapshot()
    _run(cache.evict("sft"))
    assert snap.loaded == (LoadedModelInfo(mode="sft", size_gb=6.0),)
    assert snap.vram_used_gb == 6.0


def test_snapshot_during_load_sees_target_loading() -> None:
    captured: list[Any] = []

    async def slow_loader(mode: str) -> LoadedModel:
        captured.append(cache.snapshot())
        return LoadedModel(mode=mode, handle=None, port=8101)

    async def unloader(_: LoadedModel) -> None:
        pass

    cache = ModelCache(
        vram_budget_gb=24.0,
        model_sizes={"sft": 6.0},
        loader=slow_loader,
        unloader=unloader,
    )
    _run(cache.load("sft"))
    assert len(captured) == 1
    snap = captured[0]
    assert snap.loaded == ()
    assert snap.target_loading == "sft"
    assert snap.vram_used_gb == 0.0
    assert snap.loading_started_at is not None


def test_snapshot_after_eviction_during_load_is_consistent() -> None:
    captured: list[Any] = []

    async def loader(mode: str) -> LoadedModel:
        captured.append(cache.snapshot())
        return LoadedModel(mode=mode, handle=None, port=8101)

    async def unloader(_: LoadedModel) -> None:
        pass

    cache = ModelCache(
        vram_budget_gb=12.0,
        model_sizes={"sft": 6.0, "xl-sft": 12.0},
        loader=loader,
        unloader=unloader,
    )
    _run(cache.load("sft"))
    captured.clear()
    _run(cache.load("xl-sft"))
    assert len(captured) == 1
    snap = captured[0]
    assert snap.loaded == ()
    assert snap.vram_used_gb == 0.0
    assert snap.target_loading == "xl-sft"


def test_target_loading_cleared_on_loader_failure() -> None:
    async def failing_loader(mode: str) -> LoadedModel:
        raise RuntimeError("kaboom")

    async def unloader(_: LoadedModel) -> None:
        pass

    cache = ModelCache(
        vram_budget_gb=24.0,
        model_sizes={"sft": 6.0},
        loader=failing_loader,
        unloader=unloader,
    )
    with pytest.raises(RuntimeError, match="kaboom"):
        _run(cache.load("sft"))
    assert cache.target_loading is None
    assert cache.loaded_modes() == []


# ── D5: pin / unpin ───────────────────────────────────────────────


def test_pin_unknown_mode_raises() -> None:
    cache, _, _ = _make_cache()
    with pytest.raises(ModelNotLoadedError):
        _run(cache.pin("sft"))


def test_pin_then_is_pinned() -> None:
    cache, _, _ = _make_cache()
    _run(cache.load("sft"))
    _run(cache.pin("sft"))
    assert cache.is_pinned("sft") is True
    snap = cache.snapshot()
    assert snap.pinned == ("sft",)


def test_unpin_idempotent() -> None:
    cache, _, _ = _make_cache()
    _run(cache.load("sft"))
    _run(cache.unpin("sft"))
    _run(cache.pin("sft"))
    _run(cache.unpin("sft"))
    assert cache.is_pinned("sft") is False


def test_evict_to_fit_skips_pinned_then_capacity_error() -> None:
    cache, _, unloaded_log = _make_cache(
        budget=12.0, sizes={"a": 6.0, "b": 6.0, "c": 6.0},
    )
    _run(cache.load("a"))
    _run(cache.load("b"))
    _run(cache.pin("a"))
    _run(cache.pin("b"))
    with pytest.raises(CapacityError, match="pinned"):
        _run(cache.load("c"))
    assert sorted(cache.loaded_modes()) == ["a", "b"]
    assert unloaded_log == []


def test_evict_to_fit_skips_pinned_evicts_unpinned() -> None:
    cache, _, unloaded_log = _make_cache(
        budget=12.0, sizes={"a": 6.0, "b": 6.0, "c": 6.0},
    )
    _run(cache.load("a"))
    _run(cache.load("b"))
    _run(cache.pin("a"))
    _run(cache.load("c"))
    assert "a" in cache.loaded_modes()
    assert "c" in cache.loaded_modes()
    assert "b" not in cache.loaded_modes()
    assert any(m.mode == "b" for m in unloaded_log)


def test_evict_implicitly_unpins() -> None:
    cache, _, _ = _make_cache()
    _run(cache.load("sft"))
    _run(cache.pin("sft"))
    _run(cache.evict("sft"))
    assert cache.is_pinned("sft") is False
    assert cache.loaded_modes() == []


# ── D6: refcount / acquire-release ──────────────────────────────


def test_acquire_for_use_unknown_mode_returns_none() -> None:
    cache, _, _ = _make_cache()
    result = _run(cache.acquire_for_use("sft"))
    assert result is None


def test_acquire_for_use_increments_refcount_and_moves_to_end() -> None:
    cache, _, _ = _make_cache()
    _run(cache.load("sft"))
    _run(cache.load("xl-sft"))
    handle = _run(cache.acquire_for_use("sft"))
    assert handle is not None
    assert handle.mode == "sft"
    assert cache.in_use_count("sft") == 1
    assert list(cache._loaded.keys())[-1] == "sft"


def test_release_decrements_refcount() -> None:
    cache, _, _ = _make_cache()
    _run(cache.load("sft"))
    _run(cache.acquire_for_use("sft"))
    _run(cache.acquire_for_use("sft"))
    assert cache.in_use_count("sft") == 2
    _run(cache.release("sft"))
    assert cache.in_use_count("sft") == 1
    _run(cache.release("sft"))
    assert cache.in_use_count("sft") == 0


def test_release_unknown_mode_no_op() -> None:
    cache, _, _ = _make_cache()
    _run(cache.release("sft"))
    assert cache.in_use_count("sft") == 0


def test_evict_to_fit_skips_in_use_then_capacity_error() -> None:
    cache, _, unloaded_log = _make_cache(
        budget=12.0, sizes={"a": 6.0, "b": 6.0, "c": 6.0},
    )
    _run(cache.load("a"))
    _run(cache.load("b"))
    _run(cache.acquire_for_use("a"))
    _run(cache.acquire_for_use("b"))
    with pytest.raises(CapacityError, match="in use"):
        _run(cache.load("c"))
    assert sorted(cache.loaded_modes()) == ["a", "b"]
    assert unloaded_log == []


def test_evict_to_fit_skips_in_use_evicts_idle() -> None:
    cache, _, unloaded_log = _make_cache(
        budget=12.0, sizes={"a": 6.0, "b": 6.0, "c": 6.0},
    )
    _run(cache.load("a"))
    _run(cache.load("b"))
    _run(cache.acquire_for_use("a"))
    _run(cache.load("c"))
    assert "a" in cache.loaded_modes()
    assert "c" in cache.loaded_modes()
    assert "b" not in cache.loaded_modes()
    assert any(m.mode == "b" for m in unloaded_log)


def test_evict_explicit_refuses_in_use() -> None:
    cache, _, unloaded_log = _make_cache()
    _run(cache.load("sft"))
    _run(cache.acquire_for_use("sft"))
    with pytest.raises(CapacityError, match="in use"):
        _run(cache.evict("sft"))
    assert cache.loaded_modes() == ["sft"]
    assert unloaded_log == []


# ── D8: loading_started_at ──────────────────────────────────────


def test_loading_started_at_set_during_load_then_cleared() -> None:
    captured: list[Any] = []

    async def slow_loader(mode: str) -> LoadedModel:
        captured.append(cache.snapshot())
        return LoadedModel(mode=mode, handle=None, port=8101)

    async def unloader(_: LoadedModel) -> None:
        pass

    cache = ModelCache(
        vram_budget_gb=24.0,
        model_sizes={"sft": 6.0},
        loader=slow_loader,
        unloader=unloader,
    )
    _run(cache.load("sft"))
    assert len(captured) == 1
    assert captured[0].loading_started_at is not None
    final = cache.snapshot()
    assert final.loading_started_at is None


def test_snapshot_uses_vram_reader_when_available() -> None:
    cache, _, _ = _make_cache(
        vram_reader=lambda: VramStats(used_gb=15.3, total_gb=24.0),
    )
    _run(cache.load("sft"))
    snapshot = cache.snapshot()
    assert snapshot.vram_used_gb == 15.3
    assert snapshot.vram_total_gb == 24.0


def test_snapshot_falls_back_to_declared_sizes_when_reader_returns_none() -> None:
    cache, _, _ = _make_cache(budget=22.0, vram_reader=lambda: None)
    _run(cache.load("sft"))
    snapshot = cache.snapshot()
    assert snapshot.vram_used_gb == 6.0
    assert snapshot.vram_total_gb == 22.0


def test_snapshot_without_reader_uses_declared_sizes() -> None:
    cache, _, _ = _make_cache(budget=22.0)
    _run(cache.load("sft"))
    snapshot = cache.snapshot()
    assert snapshot.vram_used_gb == 6.0
    assert snapshot.vram_total_gb == 22.0
