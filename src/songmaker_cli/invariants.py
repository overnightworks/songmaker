"""Checks of conditions the code's own structure guarantees, run on the real path."""

from __future__ import annotations


def expect(condition: bool, broken_invariant: str) -> None:
    """Raise ``RuntimeError`` naming the broken invariant when the condition is false."""
    if not condition:
        raise RuntimeError(broken_invariant)


def expect_present[T](value: T | None, broken_invariant: str) -> T:
    """Return the value, or raise ``RuntimeError`` naming the broken invariant when it is None."""
    if value is None:
        raise RuntimeError(broken_invariant)
    return value
