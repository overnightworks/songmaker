"""XTTS v2 text-to-speech — direct import, no subprocess.

Runs XTTS inference in-process using Coqui TTS.

XTTS is best for spoken/whispered/rap vocals. It cannot sing —
use Bark for singing sections.

Supports 16 languages including English and German.
Zero-shot voice cloning from a ~6 second reference audio clip.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)

VOICE_REFS_DIR: Final[str] = "_models/voice_refs"


def is_xtts_available() -> bool:
    """Check if XTTS (Coqui TTS) is installed and ready to use."""
    try:
        from TTS.api import TTS  # noqa: F401

        return True
    except ImportError:
        return False


def find_voice_ref(name: str) -> Path | None:
    """Find a voice reference audio file by name.

    Searches in voice_refs/ directory for WAV files.

    Args:
        name: Reference name (without extension).

    Returns:
        Path to the reference audio file, or None.
    """
    search_dirs = [
        Path(VOICE_REFS_DIR),
        Path("source_files") / VOICE_REFS_DIR,
        Path.home() / ".songmaker" / VOICE_REFS_DIR,
    ]

    for refs_dir in search_dirs:
        if not refs_dir.exists():
            continue

        for ext in (".wav", ".mp3", ".flac"):
            ref_path = refs_dir / f"{name}{ext}"
            if ref_path.exists():
                return ref_path

    return None


class XTTSConverter:
    """Text-to-speech using XTTS v2 (in-process).

    Generates natural-sounding speech with optional voice cloning.
    Best for spoken, whispered, and rap vocals.

    Usage:
        converter = XTTSConverter(voice_ref="my_voice")
        converter.synthesize("Hello world", "output.wav", language="en")
    """

    def __init__(
        self,
        voice_ref: str | None = None,
        language: str = "en",
        model_name: str = "tts_models/multilingual/multi-dataset/xtts_v2",
    ) -> None:
        """Initialize the XTTS converter.

        Args:
            voice_ref: Name of a voice reference file (in voice_refs/).
                None = use default XTTS voice.
            language: Default language code (en, de, etc.).
            model_name: XTTS model identifier.
        """
        self.language = language
        self.model_name = model_name

        # Resolve voice reference
        self._voice_ref_path: Path | None = None
        if voice_ref is not None:
            self._voice_ref_path = find_voice_ref(voice_ref)
            if self._voice_ref_path is None:
                logger.warning(
                    "Voice reference '%s' not found. Place a WAV file in %s/",
                    voice_ref, VOICE_REFS_DIR,
                )

        # Lazy-loaded TTS instance (heavy — downloads model on first use)
        self._tts = None

    def _get_tts(self):
        """Lazy-load the XTTS TTS engine."""
        if self._tts is None:
            import torch
            from TTS.api import TTS

            device = "cuda" if torch.cuda.is_available() else "cpu"
            self._tts = TTS(self.model_name).to(device)
        return self._tts

    @property
    def is_ready(self) -> bool:
        """Whether XTTS is installed."""
        return is_xtts_available()

    def synthesize(
        self,
        text: str,
        output_path: str,
        language: str | None = None,
    ) -> bool:
        """Synthesize speech to a WAV file.

        Args:
            text: Text to speak.
            output_path: Path for output WAV file.
            language: Override language (None = use default).

        Returns:
            True if synthesis succeeded.
        """
        if not self.is_ready:
            logger.warning("XTTS not ready, skipping synthesis")
            return False

        try:
            lang = language or self.language
            ref_info = ", voice=%s" % self._voice_ref_path.name if self._voice_ref_path else ""
            logger.info("XTTS synthesizing: lang=%s%s...", lang, ref_info)

            tts = self._get_tts()

            kwargs = {
                "text": text,
                "language": lang,
                "file_path": str(Path(output_path).resolve()),
            }

            if self._voice_ref_path and self._voice_ref_path.exists():
                kwargs["speaker_wav"] = str(self._voice_ref_path.resolve())

            tts.tts_to_file(**kwargs)

            if Path(output_path).exists():
                logger.info("XTTS synthesis complete")
                return True
            else:
                logger.error("XTTS output file not created")
                return False

        except Exception as exc:
            logger.error("XTTS failed: %s", exc)
            return False

    def synthesize_samples(
        self,
        text: str,
        language: str | None = None,
        sample_rate: int = 44100,
        temp_dir: Path | None = None,
    ) -> list[float] | None:
        """Synthesize speech and return audio samples.

        Convenience method that handles WAV I/O internally.

        Args:
            text: Text to speak.
            language: Override language.
            sample_rate: Target sample rate for output.
            temp_dir: Directory for temporary files.

        Returns:
            Audio samples in [-1.0, 1.0], or None if synthesis failed.
        """
        from bark_engine.audio_io import read_wav_file

        work_dir = temp_dir or Path("_cache/temp")
        work_dir.mkdir(parents=True, exist_ok=True)

        output_path = str(work_dir / "_xtts_output.wav")

        success = self.synthesize(text, output_path, language)

        if success and Path(output_path).exists():
            result_samples, sr = read_wav_file(output_path)
            Path(output_path).unlink(missing_ok=True)

            # Resample if needed (XTTS outputs 24kHz)
            if sr != sample_rate:
                from bark_engine.audio_utils import resample_audio

                result_samples = resample_audio(result_samples, sr, sample_rate)

            return result_samples

        Path(output_path).unlink(missing_ok=True)
        return None
