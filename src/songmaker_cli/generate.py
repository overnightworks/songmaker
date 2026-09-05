"""Audio post-processing — decode, splice, master, encode.

Used by ``songmaker_cli.jobs.post_process_generation`` after the
acestep-worker hands back a raw WAV via the scheduler. This module
no longer drives ACE-Step itself; the worker pool does.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from scipy.io import wavfile as scipy_wavfile

from acestep_engine.models import AceStepConfig
from audio_engine import MasteringError, encode_mp3, master_audio, read_wav_bytes, write_stereo_wav
from songmaker_cli.errors import GenerationError
from songmaker_cli.parser import AlbumMeta, SongMeta

log = logging.getLogger(__name__)

CROSSFADE_SECONDS = 0.05


@dataclass(frozen=True)
class DecodedAudio:
    left: NDArray[np.float64]
    right: NDArray[np.float64]
    sample_rate: int
    duration: float


def _decode_audio(ace_result) -> DecodedAudio:
    from audio_engine.errors import AudioDecodeError

    try:
        left, right, sample_rate = read_wav_bytes(ace_result.wav_bytes)
    except AudioDecodeError as exc:
        raise GenerationError(f"ACE-Step audio decode failed: {exc}") from exc
    duration = len(left) / sample_rate
    log.info("Audio decoded: %.1fs at %d Hz", duration, sample_rate)
    return DecodedAudio(left=left, right=right, sample_rate=sample_rate, duration=duration)


def _write_output(
    audio: DecodedAudio,
    seed: int,
    mp3_path: Path,
    wav_path: Path,
    meta: SongMeta,
    album_meta: AlbumMeta,
) -> None:
    try:
        mastered_left, mastered_right = master_audio(
            audio.left, audio.right, sample_rate=audio.sample_rate,
        )
    except MasteringError as exc:
        raise GenerationError(str(exc)) from exc

    write_stereo_wav(str(wav_path), mastered_left, mastered_right, audio.sample_rate)

    id3_metadata = {
        "title": meta.title,
        "artist": album_meta.artist,
        "album": album_meta.title,
        "track": meta.track,
        "genre": meta.genre,
        "lyrics": meta.lyrics,
        "comment": f"seed={seed}",
    }
    try:
        encode_mp3(
            mastered_left, mastered_right, str(mp3_path),
            sample_rate=audio.sample_rate, metadata=id3_metadata,
        )
    except MasteringError as exc:
        raise GenerationError(str(exc)) from exc


def _read_source_wav(path: str) -> DecodedAudio:
    sr, raw = scipy_wavfile.read(path)
    from audio_engine.audio_io import _normalize_dtype
    samples = _normalize_dtype(raw)
    if samples is None:
        raise GenerationError(f"Unsupported source WAV dtype: {raw.dtype}")
    if samples.ndim == 2 and samples.shape[1] >= 2:
        left, right = samples[:, 0], samples[:, 1]
    else:
        if samples.ndim == 2:
            samples = samples[:, 0]
        left, right = samples, samples.copy()
    return DecodedAudio(left=left, right=right, sample_rate=sr, duration=len(left) / sr)


def _splice_repaint_raw(
    repainted: DecodedAudio, ace_config: AceStepConfig, src_path: str,
) -> DecodedAudio:
    source = _read_source_wav(src_path)
    sr = repainted.sample_rate

    start = int(ace_config.repainting_start * sr)
    end = int(ace_config.repainting_end * sr)
    fade_len = int(CROSSFADE_SECONDS * sr)

    n = min(len(source.left), len(repainted.left))
    start = min(start, n)
    end = min(end, n)

    left = source.left[:n].copy()
    right = source.right[:n].copy()

    has_fade_in = start > 0
    has_fade_out = end < n
    fade_in_len, fade_out_len = _repaint_fade_lengths(
        end - start, fade_len, has_fade_in, has_fade_out,
    )

    if has_fade_in and fade_in_len > 0:
        ramp = np.linspace(0.0, 1.0, fade_in_len)
        for ch_src, ch_rep in ((left, repainted.left), (right, repainted.right)):
            ch_src[start:start + fade_in_len] = (
                ch_src[start:start + fade_in_len] * (1.0 - ramp)
                + ch_rep[start:start + fade_in_len] * ramp
            )
        splice_start = start + fade_in_len
    else:
        splice_start = start

    if has_fade_out and fade_out_len > 0:
        ramp = np.linspace(1.0, 0.0, fade_out_len)
        for ch_src, ch_rep in ((left, repainted.left), (right, repainted.right)):
            ch_src[end - fade_out_len:end] = (
                ch_rep[end - fade_out_len:end] * ramp
                + ch_src[end - fade_out_len:end] * (1.0 - ramp)
            )
        splice_end = end - fade_out_len
    else:
        splice_end = end

    if splice_start < splice_end:
        left[splice_start:splice_end] = repainted.left[splice_start:splice_end]
        right[splice_start:splice_end] = repainted.right[splice_start:splice_end]

    log.info(
        "Spliced repaint: %.2fs-%.2fs into source (%.0fms crossfade)",
        ace_config.repainting_start, ace_config.repainting_end, CROSSFADE_SECONDS * 1000,
    )
    return DecodedAudio(left=left, right=right, sample_rate=sr, duration=n / sr)


def _repaint_fade_lengths(
    region_length: int,
    fade_length: int,
    has_fade_in: bool,
    has_fade_out: bool,
) -> tuple[int, int]:
    if has_fade_in and has_fade_out:
        fade_in = min(fade_length, region_length // 2)
        return fade_in, min(fade_length, region_length - fade_in)
    if has_fade_in:
        return min(fade_length, region_length), 0
    if has_fade_out:
        return 0, min(fade_length, region_length)
    return 0, 0

