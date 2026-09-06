"""One admission owner for every Codex CLI process."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import StrEnum

from agent_providers.config import current_config
from agent_providers.errors import CodexProcessPoolSaturatedError


class CodexProcessKind(StrEnum):
    """The two Codex process classes with distinct admission limits."""

    TEXT = "text"
    IMAGE = "image"


@dataclass(eq=False)
class CodexProcessReservation:
    """A reserved process slot, optionally bound to the CLI process PID."""

    kind: CodexProcessKind
    pid: int | None = None


class CodexProcessPool:
    """Keep reserved, live, and zombie Codex processes within their caps."""

    def __init__(self, *, maximum_processes: int, maximum_image_runs: int) -> None:
        if maximum_processes < 1:
            raise ValueError("Codex process cap must be at least one")
        if maximum_image_runs < 1:
            raise ValueError("Codex image cap must be at least one")
        if maximum_image_runs > maximum_processes:
            raise ValueError("Codex image cap cannot exceed the total process cap")
        self._maximum_processes = maximum_processes
        self._maximum_image_runs = maximum_image_runs
        self._lock = threading.Lock()
        self._reservations: set[CodexProcessReservation] = set()

    def reserve(self, kind: CodexProcessKind) -> CodexProcessReservation:
        """Reserve before spawning, including while a killed process is unreaped."""
        with self._lock:
            if len(self._reservations) >= self._maximum_processes:
                raise CodexProcessPoolSaturatedError(kind=kind, scope="total")
            if (
                kind is CodexProcessKind.IMAGE
                and self._image_reservation_count() >= self._maximum_image_runs
            ):
                raise CodexProcessPoolSaturatedError(kind=kind, scope="image")
            reservation = CodexProcessReservation(kind=kind)
            self._reservations.add(reservation)
            return reservation

    def bind(self, reservation: CodexProcessReservation, process_id: int) -> None:
        """Bind a reservation only after the bounded runner has spawned."""
        if process_id < 1:
            raise ValueError("Cannot bind a Codex process reservation without a PID")
        with self._lock:
            if reservation not in self._reservations:
                raise RuntimeError("Cannot bind a released Codex process reservation")
            reservation.pid = process_id

    def reap(self, reservation: CodexProcessReservation, process_id: int) -> None:
        """Free a slot only after the bounded runner reports the process reaped."""
        with self._lock:
            if reservation not in self._reservations:
                return
            if reservation.pid != process_id:
                raise RuntimeError("Codex process reap did not match its reservation")
            self._reservations.remove(reservation)

    def abandon_unspawned(self, reservation: CodexProcessReservation) -> None:
        """Free an admission only when spawning failed without creating a process."""
        with self._lock:
            if reservation not in self._reservations:
                return
            if reservation.pid is not None:
                return
            self._reservations.remove(reservation)

    def reservation_count(self) -> int:
        """Return all slots, including unbound and zombie reservations."""
        with self._lock:
            return len(self._reservations)

    def image_reservation_count(self) -> int:
        """Return image slots, including unbound and zombie reservations."""
        with self._lock:
            return self._image_reservation_count()

    def _image_reservation_count(self) -> int:
        return sum(
            reservation.kind is CodexProcessKind.IMAGE
            for reservation in self._reservations
        )


_process_pool: CodexProcessPool | None = None
_process_pool_lock = threading.Lock()


def get_codex_process_pool() -> CodexProcessPool:
    """Return the one process-wide Codex admission owner."""
    global _process_pool
    with _process_pool_lock:
        if _process_pool is None:
            config = current_config()
            _process_pool = CodexProcessPool(
                maximum_processes=config.codex_max_concurrent_processes,
                maximum_image_runs=config.codex_max_concurrent_image_runs,
            )
        return _process_pool
