"""Reimport MP3/WAV files into the new ID-based audio structure."""

from __future__ import annotations

import logging
import re
import shutil
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from songmaker_cli.config import audio_file_path
from songmaker_cli.constants import MODEL_DEFAULT_MODE
from songmaker_cli.db.queries import create_generation, create_generation_created_event

log = logging.getLogger(__name__)

_SEED_PATTERN = re.compile(r"seed=(\d+)")


def cleanup_reimported_files(
    audio_dir: Path, user_id: str, generation_id: str,
) -> None:
    for suffix in (".mp3", ".wav"):
        path = audio_file_path(audio_dir, user_id, generation_id, suffix)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            log.warning("Failed to clean reimport file: %s", path)


def _extract_seed(mp3_path: Path) -> int | None:
    try:
        from mutagen.id3 import ID3
        tags = ID3(str(mp3_path))
        for frame in tags.getall("COMM"):
            match = _SEED_PATTERN.search(str(frame))
            if match:
                return int(match.group(1))
    except Exception:
        pass
    return None


def reimport_files(
    session: Session,
    audio_dir: Path,
    user_id: str,
    song_id: str,
    mp3_file: Path | None = None,
    wav_file: Path | None = None,
) -> str:
    if not mp3_file and not wav_file:
        raise ValueError("At least one of mp3_file or wav_file is required")

    generation_id = str(uuid.uuid4())
    seed = _extract_seed(mp3_file) if mp3_file else None

    mp3_rel: str | None = None
    wav_rel: str | None = None

    try:
        if mp3_file:
            dst = audio_file_path(audio_dir, user_id, generation_id, ".mp3")
            shutil.copy2(str(mp3_file), str(dst))
            mp3_rel = f"{user_id}/{generation_id}.mp3"

        if wav_file:
            dst = audio_file_path(audio_dir, user_id, generation_id, ".wav")
            shutil.copy2(str(wav_file), str(dst))
            wav_rel = f"{user_id}/{generation_id}.wav"

        gen = create_generation(
            session,
            song_id=song_id,
            version_id=None,
            mp3_path=mp3_rel or "",
            model_mode=MODEL_DEFAULT_MODE,
            seed=seed,
            wav_path=wav_rel,
            generation_id=generation_id,
            audio_dir=audio_dir,
        )
        create_generation_created_event(
            session,
            user_id=user_id,
            song_id=song_id,
            generation_id=gen.id,
        )
    except Exception:
        cleanup_reimported_files(audio_dir, user_id, generation_id)
        raise

    log.info("Reimported %s as generation %s for song %s", mp3_file or wav_file, gen.id, song_id)
    return gen.id
