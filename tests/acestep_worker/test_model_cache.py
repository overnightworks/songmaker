from __future__ import annotations

import asyncio

import pytest

from acestep_worker.model_cache import (
    CapacityError,
    LoadedModel,
    ModelCache,
    UnknownModeError,
)


def _run(coro):
    return asyncio.run(coro)


def _make_cache(*, budget: float = 24.0, sizes: dict[str, float] | None = None):
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
    )
    return cache, loaded_log, unloaded_log


def test_initial_state() -> None:
    cache, _, _ = _make_cache()
    assert cache.loaded_modes() == []
    assert cache.target_loading is None
    assert cache.vram_used_gb() == 0.0
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
    assert cache.vram_used_gb() == 6.0
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
    assert cache.vram_used_gb() == 18.0


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
