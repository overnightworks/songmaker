"""Songmaker CLI exceptions."""

from __future__ import annotations


class SongmakerError(Exception):
    """Base exception for songmaker CLI errors."""


class ValidationError(SongmakerError):
    """Invalid song metadata or input."""


class GenerationError(SongmakerError):
    """ACE-Step generation failed."""
