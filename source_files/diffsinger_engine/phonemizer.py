"""English lyrics → DiffSinger ARPAbet phonemes via g2p_en."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Lazy-loaded g2p_en instance
_g2p = None


def _get_g2p():
    global _g2p
    if _g2p is None:
        from g2p_en import G2p
        _g2p = G2p()
    return _g2p


# Map CMU/g2p_en phonemes to DiffSinger ARPAbet (lowercase)
# g2p_en outputs uppercase ARPAbet with stress markers (e.g. AH0, IY1)
# DiffSinger expects lowercase without stress (e.g. ah, iy)
_STRESS_RE = re.compile(r"[0-2]$")


def _normalize_phoneme(ph: str) -> str:
    """Normalize a g2p_en phoneme to DiffSinger format."""
    # Strip stress markers (0=no stress, 1=primary, 2=secondary)
    ph = _STRESS_RE.sub("", ph)
    return ph.lower()


@dataclass
class PhonemeResult:
    """Result of phonemizing a syllable."""

    phonemes: list[str]  # e.g. ["hh", "eh", "l"]
    count: int  # Number of phonemes for this syllable


def phonemize_syllable(text: str) -> PhonemeResult:
    """Convert a single syllable/word to DiffSinger phonemes.

    Args:
        text: A syllable or word (e.g. "hel", "lo", "world")

    Returns:
        PhonemeResult with the phoneme list and count.
    """
    g2p = _get_g2p()
    raw = g2p(text)

    phonemes = []
    for ph in raw:
        # g2p_en returns a mix of phonemes and punctuation/spaces
        if ph.strip() and ph.isalpha():
            continue  # Skip literal letters that weren't converted
        normalized = _normalize_phoneme(ph)
        if normalized and normalized.strip():
            phonemes.append(normalized)

    # If g2p returned nothing useful, try the whole string as-is
    if not phonemes:
        raw = g2p(text)
        for ph in raw:
            ph_stripped = ph.strip()
            if ph_stripped and not ph_stripped in (" ", ",", ".", "!", "?", "-"):
                phonemes.append(_normalize_phoneme(ph_stripped))

    return PhonemeResult(phonemes=phonemes, count=len(phonemes))


def phonemize_word(word: str) -> PhonemeResult:
    """Convert a full word to DiffSinger phonemes.

    Args:
        word: An English word (e.g. "hello", "world")

    Returns:
        PhonemeResult with phoneme list and count.
    """
    g2p = _get_g2p()
    raw = g2p(word)

    phonemes = []
    for ph in raw:
        ph_stripped = ph.strip()
        if not ph_stripped or ph_stripped in (" ", ",", ".", "!", "?", "-"):
            continue
        phonemes.append(_normalize_phoneme(ph_stripped))

    return PhonemeResult(phonemes=phonemes, count=len(phonemes))
