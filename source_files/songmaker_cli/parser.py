"""Parse song markdown files with YAML frontmatter into generation configs."""

from __future__ import annotations

import re
from pathlib import Path


def _parse_simple_yaml(text: str) -> dict:
    """Parse simple YAML key-value pairs (no nested structures, no PyYAML needed).

    Supports:
    - ``key: value`` (simple scalars)
    - ``key: >`` followed by indented continuation lines (multi-line block)
    - Numeric coercion for int-like values
    """
    result: dict = {}
    lines = text.strip().splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        # Skip blank lines and comments
        if not line.strip() or line.strip().startswith("#"):
            i += 1
            continue

        match = re.match(r"^(\w[\w_-]*)\s*:\s*(.*)", line)
        if not match:
            i += 1
            continue

        key = match.group(1).strip()
        value = match.group(2).strip()

        if value == ">" or value == "|":
            # Multi-line block scalar — collect indented continuation lines
            parts: list[str] = []
            i += 1
            while i < len(lines):
                cont = lines[i]
                if cont and not cont[0].isspace():
                    break
                parts.append(cont.strip())
                i += 1
            result[key] = " ".join(p for p in parts if p)
            continue

        # Strip surrounding quotes if present
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]

        # Numeric coercion
        if value.lstrip("-").isdigit():
            result[key] = int(value)
        elif _is_float(value):
            result[key] = float(value)
        elif value.lower() in ("true", "false"):
            result[key] = value.lower() == "true"
        else:
            result[key] = value

        i += 1

    return result


def _is_float(s: str) -> bool:
    try:
        float(s)
        return "." in s
    except ValueError:
        return False


def parse_song_md(path: Path) -> dict:
    """Parse a song .md file with YAML frontmatter into metadata + lyrics.

    Returns a dict with all frontmatter fields plus a ``lyrics`` key containing
    the raw lyrics text (everything between ``## Lyrics`` and the next ``##``
    heading or end of file).
    """
    text = path.read_text(encoding="utf-8")

    # Split on --- delimiters
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError(f"No YAML frontmatter found in {path}")

    meta = _parse_simple_yaml(parts[1])

    # Extract lyrics section from the body
    body = parts[2]
    lyrics_match = re.search(r"## Lyrics\s*\n(.*?)(?=\n## |\Z)", body, re.DOTALL)
    if not lyrics_match:
        raise ValueError(f"No '## Lyrics' section found in {path}")

    meta["lyrics"] = lyrics_match.group(1).strip()
    meta["_source"] = str(path)
    return meta
