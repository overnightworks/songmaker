"""WAV files on disk, stdlib only."""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np


def write_wav(path: Path, audio: np.ndarray, sr: int) -> None:
    """Write a float32/float64 numpy array to a 16-bit WAV file (stdlib only)."""
    int16 = np.clip(audio * 32768.0, -32768.0, 32767.0).astype(np.int16)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(int16.tobytes())


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    """Read a WAV file into a float32 numpy array + sample rate (stdlib only)."""
    with wave.open(str(path), "r") as wf:
        sr = wf.getframerate()
        frames = wf.readframes(wf.getnframes())
        int16 = np.frombuffer(frames, dtype=np.int16)
        return int16.astype(np.float32) / 32768.0, sr
