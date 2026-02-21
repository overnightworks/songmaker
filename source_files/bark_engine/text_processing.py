"""Text processing utilities for Bark vocal generation."""

from __future__ import annotations

from bark_engine.constants import MAX_CHUNK_LENGTH, SENTENCE_DELIMITERS
from bark_engine.models import VocalLanguage


def split_text_into_chunks(text: str, max_length: int = MAX_CHUNK_LENGTH) -> list[str]:
    """Split text into Bark-friendly chunks at sentence boundaries.

    Bark generates best with short text segments. This function splits
    at natural boundaries (periods, commas, exclamation marks) to keep
    each chunk under max_length characters.

    Args:
        text: Full lyrics text to split.
        max_length: Maximum characters per chunk.

    Returns:
        List of text chunks, each suitable for one Bark generation call.
    """
    text = text.strip()
    if len(text) <= max_length:
        return [text]

    chunks: list[str] = []
    remaining = text

    while remaining:
        remaining = remaining.strip()
        if not remaining:
            break

        if len(remaining) <= max_length:
            chunks.append(remaining)
            break

        split_pos = -1
        for delimiter in SENTENCE_DELIMITERS:
            pos = remaining.rfind(delimiter, 0, max_length)
            if pos > split_pos:
                split_pos = pos

        if split_pos <= 0:
            split_pos = remaining.rfind(" ", 0, max_length)

        if split_pos <= 0:
            split_pos = max_length

        chunk = remaining[: split_pos + 1].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[split_pos + 1 :]

    return [c for c in chunks if c.strip()]


def add_singing_markers(text: str) -> str:
    """Wrap text with ♪ markers to trigger Bark's singing mode.

    Args:
        text: Plain lyrics text.

    Returns:
        Text wrapped with musical note markers.
    """
    text = text.strip()
    if not text.startswith("♪"):
        text = f"♪ {text}"
    if not text.endswith("♪"):
        text = f"{text} ♪"
    return text


def build_speaker_preset(language: VocalLanguage, speaker_index: int) -> str:
    """Build Bark speaker preset string.

    Args:
        language: Voice language.
        speaker_index: Speaker index (0-9).

    Returns:
        Bark speaker preset identifier like 'v2/de_speaker_3'.
    """
    clamped_index = max(0, min(9, speaker_index))
    return f"v2/{language.value}_speaker_{clamped_index}"
