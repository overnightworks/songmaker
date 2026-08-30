from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class LoadedModel:
    mode: str
    handle: Any
    port: int
    loaded_at: datetime = field(default_factory=_now)


@dataclass
class LoadResult:
    loaded: list[str]
    evicted: list[str]


@dataclass(frozen=True)
class LoadedModelInfo:
    mode: str
    size_gb: float


@dataclass(frozen=True)
class VramStats:
    used_gb: float
    total_gb: float


VramReader = Callable[[], "VramStats | None"]


@dataclass(frozen=True)
class CacheStateSnapshot:
    loaded: tuple[LoadedModelInfo, ...]
    target_loading: str | None
    vram_used_gb: float
    vram_total_gb: float
    vram_measured: bool
    pinned: tuple[str, ...]
    loading_started_at: datetime | None
    loading_last_log_line: str | None = None


class CapacityError(Exception):
    pass


class UnknownModeError(Exception):
    pass


class ModelNotLoadedError(Exception):
    pass


Loader = Callable[[str], Awaitable[LoadedModel]]
Unloader = Callable[[LoadedModel], Awaitable[None]]


class ModelCache:
    def __init__(
        self,
        *,
        vram_budget_gb: float,
        model_sizes: dict[str, float],
        loader: Loader,
        unloader: Unloader,
        vram_reader: VramReader | None = None,
    ) -> None:
        self._loaded: OrderedDict[str, LoadedModel] = OrderedDict()
        self._lock = asyncio.Lock()
        self._target_loading: str | None = None
        self._loading_started_at: datetime | None = None
        self._loading_last_log_line: str | None = None
        self._budget_gb = vram_budget_gb
        self._sizes = dict(model_sizes)
        self._loader = loader
        self._unloader = unloader
        self._vram_reader = vram_reader
        self._in_use: dict[str, int] = {}
        self._pinned: set[str] = set()

    @property
    def target_loading(self) -> str | None:
        return self._target_loading

    @property
    def loading_last_log_line(self) -> str | None:
        return self._loading_last_log_line

    def set_loading_log_line(self, line: str) -> None:
        if self._target_loading is None:
            return
        self._loading_last_log_line = line

    @property
    def vram_budget_gb(self) -> float:
        return self._budget_gb

    def loaded_modes(self) -> list[str]:
        return list(self._loaded)

    def get_loaded(self, mode: str) -> LoadedModel | None:
        return self._loaded.get(mode)

    def is_pinned(self, mode: str) -> bool:
        return mode in self._pinned

    def in_use_count(self, mode: str) -> int:
        return self._in_use.get(mode, 0)

    def _current_usage(self) -> tuple[float, float, bool]:
        measured = self._vram_reader() if self._vram_reader is not None else None
        if measured is not None:
            return measured.used_gb, measured.total_gb, True
        estimated_used_gb = sum(self._sizes.get(m, 0.0) for m in self._loaded)
        return estimated_used_gb, self._budget_gb, False

    def snapshot(self) -> CacheStateSnapshot:
        loaded_tuple = tuple(
            LoadedModelInfo(mode=m, size_gb=self._sizes.get(m, 0.0))
            for m in self._loaded
        )
        used_gb, total_gb, measured = self._current_usage()
        return CacheStateSnapshot(
            loaded=loaded_tuple,
            target_loading=self._target_loading,
            vram_used_gb=used_gb,
            vram_total_gb=total_gb,
            vram_measured=measured,
            pinned=tuple(sorted(self._pinned)),
            loading_started_at=self._loading_started_at,
            loading_last_log_line=self._loading_last_log_line,
        )

    async def load(self, mode: str) -> LoadResult:
        if mode not in self._sizes:
            raise UnknownModeError(mode)
        async with self._lock:
            if mode in self._loaded:
                self._loaded.move_to_end(mode)
                return LoadResult(loaded=list(self._loaded), evicted=[])
            target_size = self._sizes[mode]
            if target_size > self._budget_gb:
                raise CapacityError(
                    f"Model {mode} requires {target_size:.1f}GB > "
                    f"budget {self._budget_gb:.1f}GB"
                )
            self._target_loading = mode
            self._loading_started_at = _now()
            self._loading_last_log_line = None
            try:
                evicted = await self._evict_to_fit(target_size)
                model = await self._loader(mode)
                self._loaded[mode] = model
                return LoadResult(loaded=list(self._loaded), evicted=evicted)
            finally:
                self._target_loading = None
                self._loading_started_at = None
                self._loading_last_log_line = None

    async def evict(self, mode: str) -> list[str]:
        async with self._lock:
            if mode not in self._loaded:
                return []
            if self._in_use.get(mode, 0) > 0:
                raise CapacityError(
                    f"Cannot evict {mode}: in use by "
                    f"{self._in_use[mode]} in-flight tasks",
                )
            await self._unloader(self._loaded[mode])
            del self._loaded[mode]
            self._pinned.discard(mode)
            return [mode]

    async def evict_all(self) -> list[str]:
        async with self._lock:
            evicted = list(self._loaded)
            for model in self._loaded.values():
                await self._unloader(model)
            self._loaded.clear()
            self._pinned.clear()
            self._in_use.clear()
            return evicted

    async def pin(self, mode: str) -> None:
        async with self._lock:
            if mode not in self._loaded:
                raise ModelNotLoadedError(f"Cannot pin {mode}: not loaded")
            self._pinned.add(mode)

    async def unpin(self, mode: str) -> None:
        async with self._lock:
            self._pinned.discard(mode)

    async def acquire_for_use(self, mode: str) -> LoadedModel | None:
        async with self._lock:
            loaded = self._loaded.get(mode)
            if loaded is None:
                return None
            self._loaded.move_to_end(mode)
            self._in_use[mode] = self._in_use.get(mode, 0) + 1
            return loaded

    async def release(self, mode: str) -> None:
        async with self._lock:
            if mode not in self._in_use:
                return
            self._in_use[mode] -= 1
            if self._in_use[mode] <= 0:
                del self._in_use[mode]

    def _declared_used_gb(self) -> float:
        return sum(self._sizes.get(m, 0.0) for m in self._loaded)

    def _planning_used_gb(self) -> tuple[float, bool]:
        """The number capacity decisions plan against: never below what the
        declared-size table says is already loaded, so a model ACE-Step
        hasn't lazily grown into yet still counts for at least its estimate.
        ``snapshot()`` never uses this — it reports the raw measurement so
        ``vram_measured`` stays honest."""
        used_gb, _, measured = self._current_usage()
        return max(used_gb, self._declared_used_gb()), measured

    def _build_eviction_plan(
        self, planning_used_gb: float, incoming_size_gb: float,
    ) -> tuple[list[str], float]:
        plan: list[str] = []
        projected_used_gb = planning_used_gb
        for mode in self._loaded:
            if projected_used_gb + incoming_size_gb <= self._budget_gb:
                break
            if mode in self._pinned or self._in_use.get(mode, 0) > 0:
                continue
            plan.append(mode)
            projected_used_gb -= self._sizes.get(mode, 0.0)
        return plan, projected_used_gb

    def _capacity_error(
        self, incoming_size_gb: float, planning_used_gb: float,
        projected_used_gb: float, measured: bool,
    ) -> CapacityError:
        used_label = "measured" if measured else "estimated from declared sizes"
        if not self._loaded:
            return CapacityError(
                f"Cannot fit {incoming_size_gb:.1f}GB (estimated, not yet loaded) within "
                f"the {self._budget_gb:.1f}GB budget: {planning_used_gb:.1f}GB is already "
                f"in use on the GPU ({used_label}) although this worker has no model "
                f"loaded — that VRAM is not tracked by this cache (a stray process or an "
                f"unreleased subprocess). Check nvidia-smi on the worker host; loading "
                f"cannot proceed until it is freed.",
            )
        return CapacityError(
            f"Cannot fit {incoming_size_gb:.1f}GB (estimated, not yet loaded) on top of "
            f"{planning_used_gb:.1f}GB already in use ({used_label}) within a "
            f"{self._budget_gb:.1f}GB budget: evicting every eligible model still leaves "
            f"{projected_used_gb:.1f}GB in use (loaded={list(self._loaded)}, "
            f"in_use={dict(self._in_use)}, pinned={sorted(self._pinned)})",
        )

    async def _evict_to_fit(self, incoming_size_gb: float) -> list[str]:
        planning_used_gb, measured = self._planning_used_gb()
        plan, projected_used_gb = self._build_eviction_plan(
            planning_used_gb, incoming_size_gb,
        )
        if projected_used_gb + incoming_size_gb > self._budget_gb:
            raise self._capacity_error(
                incoming_size_gb, planning_used_gb, projected_used_gb, measured,
            )

        evicted: list[str] = []
        running_used_gb = planning_used_gb
        for mode in plan:
            if running_used_gb + incoming_size_gb <= self._budget_gb:
                break
            victim_model = self._loaded[mode]
            await self._unloader(victim_model)
            del self._loaded[mode]
            evicted.append(mode)
            running_used_gb = min(
                self._planning_used_gb()[0], running_used_gb - self._sizes.get(mode, 0.0),
            )
        return evicted
