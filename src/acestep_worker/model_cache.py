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


class CapacityError(Exception):
    pass


class UnknownModeError(Exception):
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
    ) -> None:
        self._loaded: OrderedDict[str, LoadedModel] = OrderedDict()
        self._lock = asyncio.Lock()
        self._target_loading: str | None = None
        self._budget_gb = vram_budget_gb
        self._sizes = dict(model_sizes)
        self._loader = loader
        self._unloader = unloader

    @property
    def target_loading(self) -> str | None:
        return self._target_loading

    @property
    def vram_budget_gb(self) -> float:
        return self._budget_gb

    def loaded_modes(self) -> list[str]:
        return list(self._loaded)

    def get_loaded(self, mode: str) -> LoadedModel | None:
        return self._loaded.get(mode)

    def vram_used_gb(self) -> float:
        return sum(self._sizes.get(mode, 0.0) for mode in self._loaded)

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
            try:
                evicted = await self._evict_to_fit(target_size)
                model = await self._loader(mode)
                self._loaded[mode] = model
                return LoadResult(loaded=list(self._loaded), evicted=evicted)
            finally:
                self._target_loading = None

    async def evict(self, mode: str) -> list[str]:
        async with self._lock:
            if mode not in self._loaded:
                return []
            await self._unloader(self._loaded[mode])
            del self._loaded[mode]
            return [mode]

    async def evict_all(self) -> list[str]:
        async with self._lock:
            evicted = list(self._loaded)
            for model in self._loaded.values():
                await self._unloader(model)
            self._loaded.clear()
            return evicted

    async def _evict_to_fit(self, incoming_size_gb: float) -> list[str]:
        evicted: list[str] = []
        used = sum(self._sizes.get(m, 0.0) for m in self._loaded)
        while self._loaded and used + incoming_size_gb > self._budget_gb:
            victim_mode = next(iter(self._loaded))
            victim_model = self._loaded[victim_mode]
            await self._unloader(victim_model)
            del self._loaded[victim_mode]
            used -= self._sizes.get(victim_mode, 0.0)
            evicted.append(victim_mode)
        return evicted
