"""The one place that may take an environment variable over at runtime.

Configuration is read through ``Settings``. This module owns the other
thing an environment variable can be: live process state that a
third-party library reads on its own, which we must set for the length
of one call and put back exactly as we found it. Keeping that idiom
here — instead of spreading raw ``os.environ`` handling through the
codebase — is why the no-silent-fallbacks check can forbid environment
reads everywhere else without exceptions.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager


@contextmanager
def temporary_env_override(key: str, value: str) -> Iterator[None]:
    """Set ``key`` to ``value`` for the duration of the block.

    The value found on entry — or its absence — is restored on exit,
    including when the block raises. The environment is process-wide
    state shared with every thread, so the caller owns serializing
    overlapping overrides.
    """
    previous = os.environ.get(key)
    os.environ[key] = value
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous
