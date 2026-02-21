"""XTTS v2 text-to-speech via subprocess.

Runs XTTS inference via subprocess, communicating through WAV files.

XTTS is best for spoken/whispered/rap vocals. It cannot sing —
use Bark for singing sections.

Supports 16 languages including English and German.
Zero-shot voice cloning from a ~6 second reference audio clip.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Final

XTTS_VENV_DIR: Final[str] = ".venv"
XTTS_INFERENCE_SCRIPT: Final[str] = "_xtts_infer.py"
VOICE_REFS_DIR: Final[str] = "voice_refs"


def _find_venv() -> Path | None:
    """Find the isolated virtual environment directory.

    Uses the same venv as RVC (shared Python 3.12 environment).
    """
    search_paths = [
        Path(XTTS_VENV_DIR),
        Path("source_files") / XTTS_VENV_DIR,
        Path.home() / ".songmaker" / XTTS_VENV_DIR,
    ]

    for venv_path in search_paths:
        python_path = _get_venv_python(venv_path)
        if python_path and python_path.exists():
            return venv_path

    return None


def _get_venv_python(venv_dir: Path) -> Path | None:
    """Get the Python executable path for a venv (Windows or Unix)."""
    candidates = [
        venv_dir / "Scripts" / "python.exe",  # Windows
        venv_dir / "bin" / "python",           # Unix
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def is_xtts_available() -> bool:
    """Check if XTTS is installed and ready to use.

    Returns True if the shared venv exists and has coqui-tts installed.
    """
    venv_dir = _find_venv()
    if venv_dir is None:
        return False

    python = _get_venv_python(venv_dir)
    if python is None:
        return False

    try:
        result = subprocess.run(
            [str(python), "-c", "from TTS.api import TTS; print('ok')"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode == 0 and "ok" in result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
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
    """Text-to-speech using XTTS v2 in an isolated subprocess.

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
                print(
                    f"   Warning: Voice reference '{voice_ref}' not found. "
                    f"Place a WAV file in {VOICE_REFS_DIR}/"
                )

        # Find venv
        self._venv_dir = _find_venv()
        if self._venv_dir is None:
            print(
                f"   Warning: Isolated venv not found. "
                f"Run setup_rvc_venv.py to create it."
            )

    @property
    def is_ready(self) -> bool:
        """Whether the converter has a valid venv with XTTS installed."""
        return self._venv_dir is not None and is_xtts_available()

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
            print(f"   XTTS not ready, skipping synthesis")
            return False

        python = _get_venv_python(self._venv_dir)
        if python is None:
            return False

        config = {
            "text": text,
            "output_path": str(Path(output_path).resolve()),
            "language": language or self.language,
            "model_name": self.model_name,
        }

        if self._voice_ref_path and self._voice_ref_path.exists():
            config["speaker_wav"] = str(self._voice_ref_path.resolve())

        # Write config to temp file
        config_path = Path(output_path).parent / "_xtts_config.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")

        script_path = Path(__file__).parent / XTTS_INFERENCE_SCRIPT

        try:
            lang = language or self.language
            ref_info = f", voice={self._voice_ref_path.name}" if self._voice_ref_path else ""
            print(f"   XTTS synthesizing: lang={lang}{ref_info}...")

            result = subprocess.run(
                [str(python), str(script_path), str(config_path)],
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
            )

            if result.returncode != 0:
                print(f"   XTTS failed: {result.stderr[:200]}")
                return False

            if Path(output_path).exists():
                print(f"   XTTS synthesis complete")
                return True
            else:
                print(f"   XTTS output file not created")
                return False

        except subprocess.TimeoutExpired:
            print(f"   XTTS timed out after 5 minutes")
            return False
        except FileNotFoundError:
            print(f"   XTTS venv Python not found")
            return False
        finally:
            config_path.unlink(missing_ok=True)

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

        work_dir = temp_dir or Path("_temp_bark")
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
