"""The request lines a process wrote, read back from its captured output."""

from __future__ import annotations

import json

from logline import REQUEST_EVENT


def request_lines(output: str) -> list[dict[str, object]]:
    lines = [json.loads(line) for line in output.splitlines()]
    return [line for line in lines if line["event"] == REQUEST_EVENT]
