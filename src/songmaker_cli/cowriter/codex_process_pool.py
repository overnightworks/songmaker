"""One admission owner for every Codex CLI process."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import StrEnum

from songmaker_cli.cowriter.errors import CodexProcessPoolSaturatedError
from songmaker_cli.settings import get_settings


class CodexProcessKind(StrEnum):
    """The two Codex process classes with distinct admission limits."""

    TEXT = "text"
    COVER = "cover"


@dataclass(eq=False)
class CodexProcessReservation:
    """A reserved process slot, optionally bound to the CLI process PID."""

    kind: CodexProcessKind
    pid: int | None = None


class CodexProcessPool:
    """Keep reserved, live, and zombie Codex processes within their caps."""

    def __init__(self, *, maximum_processes: int, maximum_cover_runs: int) -> None:
        if maximum_processes < 1:
            raise ValueError("Codex process cap must be at least one")
        if maximum_cover_runs < 1:
            raise ValueError("Codex cover cap must be at least one")
        if maximum_cover_runs > maximum_processes:
            raise ValueError("Codex cover cap cannot exceed the total process cap")
        self._maximum_processes = maximum_processes
        self._maximum_cover_runs = maximum_cover_runs
        self._lock = threading.Lock()
        self._reservations: set[CodexProcessReservation] = set()

    def reserve(self, kind: CodexProcessKind) -> CodexProcessReservation:
        """Reserve before spawning, including while a killed process is unreaped."""
        with self._lock:
            if len(self._reservations) >= self._maximum_processes:
                raise CodexProcessPoolSaturatedError(kind=kind, scope="total")
            if (
                kind is CodexProcessKind.COVER
                and self._cover_reservation_count() >= self._maximum_cover_runs
            ):
                raise CodexProcessPoolSaturatedError(kind=kind, scope="cover")
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

    def cover_reservation_count(self) -> int:
        """Return cover slots, including unbound and zombie reservations."""
        with self._lock:
            return self._cover_reservation_count()

    def _cover_reservation_count(self) -> int:
        return sum(
            reservation.kind is CodexProcessKind.COVER
            for reservation in self._reservations
        )


_process_pool: CodexProcessPool | None = None
_process_pool_lock = threading.Lock()


def get_codex_process_pool() -> CodexProcessPool:
    """Return the one process-wide Codex admission owner."""
    global _process_pool
    with _process_pool_lock:
        if _process_pool is None:
            settings = get_settings()
            _process_pool = CodexProcessPool(
                maximum_processes=settings.codex_cli_max_concurrent_processes,
                maximum_cover_runs=settings.cover_max_concurrent_runs,
            )
        return _process_pool
