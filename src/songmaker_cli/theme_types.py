"""The person's theme choice, shared by the database model and the API models."""

from __future__ import annotations

from enum import StrEnum


class ThemeChoice(StrEnum):
    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"
