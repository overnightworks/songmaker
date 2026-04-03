"""Generation engine — generate, decode, master, and write MP3 output."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from scipy.io import wavfile as scipy_wavfile

from acestep_engine import AceStepClient, AceStepError
from acestep_engine.models import AceStepConfig, AceStepResult
from audio_engine import MasteringError, encode_mp3, master_audio, read_wav_bytes, write_stereo_wav
from songmaker_cli.config import audio_file_path
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


@dataclass(frozen=True)
class GenerationResult:
    mp3_path: Path
    wav_path: Path
    seed: int
    duration: float
    cot_caption: str = ""
    cot_lyrics: str = ""


def generate_single(
    meta: SongMeta,
    album_meta: AlbumMeta,
    ace_config: AceStepConfig,
    audio_dir: Path,
    user_id: str,
    generation_id: str,
    client: AceStepClient | None = None,
    on_progress: Callable[[str], None] | None = None,
    raw_src_audio: str | None = None,
) -> GenerationResult:
    if client is None:
        client = AceStepClient()
    if not client.is_available:
        raise GenerationError("ACE-Step server is not reachable")

    mp3_path = audio_file_path(audio_dir, user_id, generation_id, ".mp3")
    wav_path = audio_file_path(audio_dir, user_id, generation_id, ".wav")
    raw_wav_path = audio_file_path(audio_dir, user_id, generation_id, ".raw.wav")
    try:
        ace_result, elapsed = _run_generation(ace_config, client, on_progress=on_progress)
        audio = _decode_audio(ace_result)
        server_handles_crossfade = bool(
            ace_config.repaint_mode or ace_config.repaint_wav_crossfade_sec > 0
        )
        needs_splice = (
            ace_config.task_type == "repaint" and ace_config.src_audio
            and not server_handles_crossfade
        )
        if needs_splice:
            splice_src = raw_src_audio or ace_config.src_audio
            audio = _splice_repaint_raw(audio, ace_config, splice_src)
        write_stereo_wav(str(raw_wav_path), audio.left, audio.right, audio.sample_rate)
        _write_output(audio, ace_result.seed, mp3_path, wav_path, meta, album_meta)
    except Exception:
        _cleanup_partial_files(mp3_path, wav_path, raw_wav_path)
        raise

    log.info("Generated: %s (seed=%s, %.0fs)", mp3_path.name, ace_result.seed, elapsed)
    return GenerationResult(
        mp3_path=mp3_path,
        wav_path=wav_path,
        seed=ace_result.seed,
        duration=audio.duration,
        cot_caption=ace_result.cot_caption,
        cot_lyrics=ace_result.cot_lyrics,
    )


def _run_generation(
    ace_config: AceStepConfig, client: AceStepClient,
    on_progress: Callable[[str], None] | None = None,
) -> tuple[AceStepResult, float]:
    log.info("Generating via ACE-Step...")
    start_time = time.time()
    try:
        result: AceStepResult = client.generate(ace_config, on_progress=on_progress)
    except AceStepError as exc:
        raise GenerationError(str(exc)) from exc
    return result, time.time() - start_time


def _decode_audio(ace_result: AceStepResult) -> DecodedAudio:
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

    region_len = end - start
    has_fade_in = start > 0
    has_fade_out = end < n
    if has_fade_in and has_fade_out:
        fade_in_len = min(fade_len, region_len // 2)
        fade_out_len = min(fade_len, region_len - fade_in_len)
    elif has_fade_in:
        fade_in_len = min(fade_len, region_len)
        fade_out_len = 0
    elif has_fade_out:
        fade_in_len = 0
        fade_out_len = min(fade_len, region_len)
    else:
        fade_in_len = 0
        fade_out_len = 0

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


def _cleanup_partial_files(*paths: Path) -> None:
    for path in paths:
        try:
            if path.exists():
                path.unlink()
                log.info("Cleaned up partial file: %s", path.name)
        except OSError:
            log.warning("Failed to clean up partial file: %s", path)
