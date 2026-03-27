"""Generation engine — generate, decode, master, and write MP3 output."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from acestep_engine import AceStepClient, AceStepError
from acestep_engine.models import AceStepConfig, AceStepResult
from audio_engine import MasteringError, encode_mp3, master_audio, read_wav_bytes, write_stereo_wav
from songmaker_cli.config import audio_file_path
from songmaker_cli.errors import GenerationError
from songmaker_cli.parser import AlbumMeta, SongMeta

log = logging.getLogger(__name__)


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


def generate_single(
    meta: SongMeta,
    album_meta: AlbumMeta,
    ace_config: AceStepConfig,
    audio_dir: Path,
    user_id: str,
    generation_id: str,
    client: AceStepClient | None = None,
) -> GenerationResult:
    if client is None:
        client = AceStepClient()
    if not client.is_available:
        raise GenerationError("ACE-Step server is not reachable")

    mp3_path = audio_file_path(audio_dir, user_id, generation_id, ".mp3")
    wav_path = audio_file_path(audio_dir, user_id, generation_id, ".wav")
    ace_result, elapsed = _run_generation(ace_config, client)
    audio = _decode_audio(ace_result)
    _write_output(audio, ace_result.seed, mp3_path, wav_path, meta, album_meta)

    log.info("Generated: %s (seed=%s, %.0fs)", mp3_path.name, ace_result.seed, elapsed)
    return GenerationResult(
        mp3_path=mp3_path,
        wav_path=wav_path,
        seed=ace_result.seed,
        duration=audio.duration,
    )


def _run_generation(
    ace_config: AceStepConfig, client: AceStepClient,
) -> tuple[AceStepResult, float]:
    log.info("Generating via ACE-Step...")
    start_time = time.time()
    try:
        result: AceStepResult = client.generate(ace_config)
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
