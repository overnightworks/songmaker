"""Inert UTF-8 JSON wire format shared by arq producers and workers."""

from __future__ import annotations

import json
import math


def _validate_json(value: object) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("arq JSON requires finite numbers")
    elif isinstance(value, (list, tuple)):
        for item in value:
            _validate_json(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("arq JSON object keys must be strings")
            _validate_json(item)
    else:
        raise TypeError(f"Unsupported arq JSON value: {type(value).__name__}")


def serialize_arq(data: dict[str, object]) -> bytes:
    _validate_json(data)
    text = json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    return text.encode("utf-8")


def deserialize_arq(data: bytes) -> dict[str, object]:
    decoded = json.loads(data.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("arq JSON envelope must be an object")
    _validate_json(decoded)
    return decoded
