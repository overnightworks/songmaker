"""Demucs stem separation via subprocess.

Splits any audio file into 4 stems: vocals, drums, bass, other.
VRAM: ~3 GB minimum. Use segment=7 for 6 GB GPUs.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Final

VENV_DIR: Final[str] = ".venv"
INFERENCE_SCRIPT: Final[str] = "_demucs_infer.py"
STEM_NAMES: Final[tuple[str, ...]] = ("drums", "bass", "other", "vocals")


def _find_venv() -> Path | None:
    """Find the isolated virtual environment directory."""
    search_paths = [
        Path(VENV_DIR),
        Path("source_files") / VENV_DIR,
        Path.home() / ".songmaker" / VENV_DIR,
    ]
    for venv_path in search_paths:
        python_path = _get_venv_python(venv_path)
        if python_path and python_path.exists():
            return venv_path
    return None


def _get_venv_python(venv_dir: Path) -> Path | None:
    """Get the Python executable path for a venv."""
    candidates = [
        venv_dir / "Scripts" / "python.exe",
        venv_dir / "bin" / "python",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def is_demucs_available() -> bool:
    """Check if Demucs is installed and ready to use."""
    venv_dir = _find_venv()
    if venv_dir is None:
        return False

    python = _get_venv_python(venv_dir)
    if python is None:
        return False

    try:
        result = subprocess.run(
            [str(python), "-c",
             "from demucs.pretrained import get_model; print('ok')"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode == 0 and "ok" in result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


@dataclass(frozen=True)
class SeparatedStems:
    """Result of stem separation.

    Each field contains audio samples at the original sample rate.
    """

    vocals: list[float]
    drums: list[float]
    bass: list[float]
    other: list[float]
    sample_rate: int


class DemucsSeparator:
    """Audio stem separation using Meta's Demucs.

    Splits any audio into 4 stems: vocals, drums, bass, other.
    Useful for remixing, isolating instruments, or creating
    karaoke tracks.

    Usage:
        separator = DemucsSeparator()
        stems = separator.separate("song.wav")
        # stems.vocals, stems.drums, stems.bass, stems.other
    """

    def __init__(
        self,
        model_name: str = "htdemucs",
        segment: int = 7,
    ) -> None:
        """Initialize the Demucs separator.

        Args:
            model_name: Demucs model identifier.
                "htdemucs" = Hybrid Transformer (best quality).
            segment: Processing segment length in seconds.
                Lower = less VRAM. Use 7 for 6GB GPUs.
        """
        self.model_name = model_name
        self.segment = segment

        self._venv_dir = _find_venv()
        if self._venv_dir is None:
            print(
                f"   Warning: Isolated venv not found. "
                f"Run setup_rvc_venv.py to create it."
            )

    @property
    def is_ready(self) -> bool:
        """Whether Demucs is available."""
        return self._venv_dir is not None and is_demucs_available()

    def separate(
        self,
        input_path: str,
        output_dir: str | None = None,
        temp_dir: Path | None = None,
    ) -> SeparatedStems | None:
        """Separate an audio file into stems.

        Args:
            input_path: Path to input audio file (WAV, MP3, FLAC).
            output_dir: Optional directory for output stem WAV files.
                If None, uses a temp directory (cleaned up after).
            temp_dir: Directory for temporary files.

        Returns:
            SeparatedStems with audio for each stem, or None on failure.
        """
        if not self.is_ready:
            print(f"   Demucs not ready, skipping separation")
            return None

        python = _get_venv_python(self._venv_dir)
        if python is None:
            return None

        work_dir = temp_dir or Path("_temp_demucs")
        work_dir.mkdir(parents=True, exist_ok=True)

        stem_dir = output_dir or str(work_dir / "stems")
        Path(stem_dir).mkdir(parents=True, exist_ok=True)

        config = {
            "input_path": str(Path(input_path).resolve()),
            "output_dir": str(Path(stem_dir).resolve()),
            "model_name": self.model_name,
            "segment": self.segment,
        }

        config_path = work_dir / "_demucs_config.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")

        script_path = Path(__file__).parent / INFERENCE_SCRIPT

        try:
            print(f"   Demucs separating: {self.model_name}...")

            result = subprocess.run(
                [str(python), str(script_path), str(config_path)],
                capture_output=True,
                text=True,
                timeout=600,  # 10 minute timeout
            )

            if result.returncode != 0:
                print(f"   Demucs failed: {result.stderr[:200]}")
                return None

            # Read stem files
            from bark_engine.audio_io import read_wav_file

            stems: dict[str, list[float]] = {}
            sample_rate = 44100

            for stem_name in STEM_NAMES:
                stem_path = Path(stem_dir) / f"{stem_name}.wav"
                if stem_path.exists():
                    samples, sr = read_wav_file(str(stem_path))
                    stems[stem_name] = samples
                    sample_rate = sr
                    # Clean up if using temp dir
                    if output_dir is None:
                        stem_path.unlink(missing_ok=True)
                else:
                    print(f"   Warning: stem '{stem_name}' not found")
                    stems[stem_name] = []

            print(f"   Demucs separation complete")

            return SeparatedStems(
                vocals=stems.get("vocals", []),
                drums=stems.get("drums", []),
                bass=stems.get("bass", []),
                other=stems.get("other", []),
                sample_rate=sample_rate,
            )

        except subprocess.TimeoutExpired:
            print(f"   Demucs timed out after 10 minutes")
            return None
        except FileNotFoundError:
            print(f"   Demucs venv Python not found")
            return None
        finally:
            config_path.unlink(missing_ok=True)
