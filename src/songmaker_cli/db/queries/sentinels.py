"""Sentinel shared by query modules for partial-update signatures.

Distinguishes "the caller did not pass this argument" from an explicit
value (including `None`, which is itself meaningful for some fields). Lives
here rather than in `songs.py` or `albums.py` so both can import it without
creating a cycle between those two modules.
"""

from __future__ import annotations


class _Unset:
    """Sentinel distinguishing "not provided" from an explicit value."""


UNSET = _Unset()
