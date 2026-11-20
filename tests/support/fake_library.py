"""A fake of an optional model library, installed so the lazy loaders import it."""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest


def install_fake_library(
    monkeypatch: pytest.MonkeyPatch, module_name: str, class_name: str,
) -> MagicMock:
    """Install `module_name` (and its parent packages) with a mock `class_name`; return the mock."""
    library_class = MagicMock(name=class_name)
    parent: ModuleType | None = None
    parts = module_name.split(".")
    for depth in range(1, len(parts) + 1):
        name = ".".join(parts[:depth])
        module = ModuleType(name)
        monkeypatch.setitem(sys.modules, name, module)
        if parent is not None:
            setattr(parent, parts[depth - 1], module)
        parent = module
    assert parent is not None
    setattr(parent, class_name, library_class)
    return library_class
