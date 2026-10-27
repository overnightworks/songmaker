"""The web process's registry of agent-service runs that songmaker started.

``/mcp`` accepts a tool call only while its capability's run is registered here
for the person whose co-writer turn is running (Q8): a valid signature alone
proves a run id, not that the run is live. The turn registers its run when it
reads ``run_started`` and releases it when the turn ends. The registry lives in
the process that runs the turn, like ``_running_chat_turns``; a restart empties
it, which refuses every earlier capability.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RunPerson:
    """The person exactly as the agent service saw them: issuer and subject."""

    issuer: str
    subject: str


class RunAlreadyRegisteredError(ValueError):
    """A run id is registered once: a second registration would hand a live run to another turn."""


_RUNNING: dict[str, RunPerson] = {}


def register(run_id: str, person: RunPerson) -> None:
    if run_id in _RUNNING:
        raise RunAlreadyRegisteredError(run_id)
    _RUNNING[run_id] = person


def release(run_id: str) -> None:
    _RUNNING.pop(run_id, None)


def holder(run_id: str) -> RunPerson | None:
    return _RUNNING.get(run_id)
