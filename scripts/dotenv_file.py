"""The one reader of the project's ``.env``, read the way Docker Compose reads it.

Compose's dotenv accepts ``KEY=value`` and ``KEY: value``, an optional
``export`` prefix, single quotes (literal), double quotes (with escapes and
interpolation), and — for UNQUOTED values only — a trailing ``#`` comment that
must be preceded by whitespace. ``/srv/creds#blue`` is therefore a value, not a
truncation.

This reads a deliberate SUBSET of that: no escapes, no interpolation. Anything
outside the subset is refused by key name rather than guessed at, because
guessing differently from Compose is precisely how a script acts on a value the
stack never sees. Refusals name the file and the key, never the value: some of
these keys are secrets.

Stdlib only, imported as a sibling module by the scripts beside it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


class DotenvError(ValueError):
    """A key's assignment lies outside the subset this reader understands."""


@dataclass(frozen=True)
class Assignment:
    """The effective assignment of one key: where it stands and what it holds."""

    line_index: int
    value: str


def effective_assignment(text: str, key: str, source: Path) -> Assignment | None:
    """The key's last assignment in ``text`` (Compose's last-wins), or ``None``.

    ``line_index`` counts lines as ``text.splitlines(keepends=True)`` does, so a
    caller can replace exactly that line and leave every other byte alone.
    """
    effective = None
    for index, line in enumerate(text.splitlines(keepends=True)):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        assigned_key, separator, raw = _split_assignment(stripped)
        if separator and assigned_key == key:
            effective = Assignment(index, _dotenv_value(raw, key, source))
    return effective


def _split_assignment(line: str) -> tuple[str, str, str]:
    """``KEY=v``, ``KEY: v`` and an optional ``export`` prefix, as Compose does."""
    if line.startswith("export "):
        line = line[len("export "):].lstrip()
    equals, colon = line.find("="), line.find(":")
    if equals == -1 and colon == -1:
        return "", "", ""
    if equals != -1 and (colon == -1 or equals < colon):
        key, separator, raw = line.partition("=")
    else:
        key, separator, raw = line.partition(":")
    return key.strip(), separator, raw


def _dotenv_value(raw: str, key: str, source: Path) -> str:
    """One assignment's value: quotes honoured, comments only where Compose has them."""
    raw = raw.strip()
    for quote in ('"', "'"):
        if raw.startswith(quote):
            closing = raw.find(quote, 1)
            if closing == -1:
                raise DotenvError(f"{source}: {key} has an unclosed quote")
            inner = raw[1:closing]
            if quote == '"' and "\\" in inner:
                raise DotenvError(
                    f"{source}: {key} uses a backslash escape. This reader does "
                    f"not process escapes, and guessing differently from Compose "
                    f"would act on a value the stack never sees — write it "
                    f"without escapes",
                )
            if "$" in inner:
                raise DotenvError(
                    f"{source}: {key} uses interpolation. This reader does not "
                    f"interpolate — write the value out in full",
                )
            trailing = raw[closing + 1:].strip()
            if trailing and not trailing.startswith("#"):
                raise DotenvError(f"{source}: {key} has text after its closing quote")
            return inner
    # Unquoted: a '#' only starts a comment when whitespace precedes it, which
    # is what keeps '/srv/creds#blue' a value.
    comment = re.search(r"\s#", raw)
    if comment:
        raw = raw[: comment.start()]
    if "$" in raw:
        raise DotenvError(
            f"{source}: {key} uses interpolation. This reader does not "
            f"interpolate — write the value out in full",
        )
    return raw.strip()
