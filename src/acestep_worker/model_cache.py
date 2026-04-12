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

    def snapshot(self) -> CacheStateSnapshot:
        loaded_tuple = tuple(
            LoadedModelInfo(mode=m, size_gb=self._sizes.get(m, 0.0))
            for m in self._loaded
        )
        measured = self._vram_reader() if self._vram_reader is not None else None
        if measured is not None:
            used_gb = measured.used_gb
            total_gb = measured.total_gb
        else:
            used_gb = sum(info.size_gb for info in loaded_tuple)
            total_gb = self._budget_gb
        return CacheStateSnapshot(
            loaded=loaded_tuple,
            target_loading=self._target_loading,
            vram_used_gb=used_gb,
            vram_total_gb=total_gb,
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

    async def _evict_to_fit(self, incoming_size_gb: float) -> list[str]:
        evicted: list[str] = []
        used = sum(self._sizes.get(m, 0.0) for m in self._loaded)
        while self._loaded and used + incoming_size_gb > self._budget_gb:
            victim_mode = next(
                (
                    m for m in self._loaded
                    if m not in self._pinned and self._in_use.get(m, 0) == 0
                ),
                None,
            )
            if victim_mode is None:
                raise CapacityError(
                    f"Cannot fit {incoming_size_gb:.1f}GB: all eligible models "
                    f"are in use or pinned (loaded={list(self._loaded)}, "
                    f"in_use={dict(self._in_use)}, pinned={sorted(self._pinned)})",
                )
            victim_model = self._loaded[victim_mode]
            await self._unloader(victim_model)
            del self._loaded[victim_mode]
            used -= self._sizes.get(victim_mode, 0.0)
            evicted.append(victim_mode)
        return evicted
