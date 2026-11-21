"""Audio engine exceptions."""

from __future__ import annotations


class MasteringError(Exception):
    """Audio mastering or encoding failed."""


class AudioDecodeError(Exception):
    """WAV/audio decoding failed."""
