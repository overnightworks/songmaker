"""The trace context arq producers put in a job's keyword arguments and workers take out."""

from __future__ import annotations

from typing import Final

# The enqueuer's trace rides in the job's keyword arguments; the worker's job wrapper takes it out.
TRACEPARENT_KWARG: Final = "traceparent"
