"""RVC voice conversion via subprocess.

Runs RVC inference in the project venv via subprocess, communicating
through WAV files.

This design is intentionally GPU-agnostic and hardware-independent.
Upgrading from a GTX 1660 Ti to an RTX 3090 requires zero code
changes — the RVC subprocess auto-detects CUDA.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Final

RVC_VENV_DIR: Final[str] = ".venv"
RVC_MODELS_DIR: Final[str] = "rvc_models"
RVC_INFERENCE_SCRIPT: Final[str] = "_rvc_infer.py"


def _find_rvc_venv() -> Path | None:
    """Find the RVC virtual environment directory.

    Searches in the project root and common locations.
    Returns the venv directory path or None if not found.
    """
    search_paths = [
        Path(RVC_VENV_DIR),
        Path("source_files") / RVC_VENV_DIR,
        Path.home() / ".songmaker" / RVC_VENV_DIR,
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


def is_rvc_available() -> bool:
    """Check if RVC is installed and ready to use.

    Returns True if the RVC venv exists and has rvc-python installed.
    """
    venv_dir = _find_rvc_venv()
    if venv_dir is None:
        return False

    python = _get_venv_python(venv_dir)
    if python is None:
        return False

    try:
        result = subprocess.run(
            [str(python), "-c", "from rvc_python.infer import RVCInference; print('ok')"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode == 0 and "ok" in result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _find_model(model_name: str) -> tuple[Path | None, Path | None]:
    """Find an RVC voice model by name.

    Searches for .pth and .index files in the models directory.

    Args:
        model_name: Model name (without extension).

    Returns:
        Tuple of (model_path, index_path). index_path may be None.
    """
    search_dirs = [
        Path(RVC_MODELS_DIR),
        Path("source_files") / RVC_MODELS_DIR,
        Path.home() / ".songmaker" / RVC_MODELS_DIR,
    ]

    for models_dir in search_dirs:
        if not models_dir.exists():
            continue

        # Direct match
        pth = models_dir / f"{model_name}.pth"
        if pth.exists():
            idx = models_dir / f"{model_name}.index"
            return pth, idx if idx.exists() else None

        # Search in subdirectories
        for subdir in models_dir.iterdir():
            if subdir.is_dir() and subdir.name == model_name:
                pth_files = list(subdir.glob("*.pth"))
                idx_files = list(subdir.glob("*.index"))
                if pth_files:
                    return pth_files[0], idx_files[0] if idx_files else None

    return None, None


class RVCConverter:
    """Voice conversion using RVC in an isolated subprocess.

    Converts input audio through a trained RVC voice model to
    produce natural-sounding vocals. All inference runs in a
    separate Python 3.12 venv to avoid dependency conflicts.

    Usage:
        converter = RVCConverter(model_name="male_singer_v2")
        converter.convert("input.wav", "output.wav")
    """

    def __init__(
        self,
        model_name: str,
        pitch_shift: int = 0,
        index_rate: float = 0.66,
        filter_radius: int = 3,
        rms_mix_rate: float = 0.25,
        protect: float = 0.33,
        f0_method: str = "rmvpe",
    ) -> None:
        """Initialize the RVC converter.

        Args:
            model_name: Name of the RVC voice model (in rvc_models/).
            pitch_shift: Pitch shift in semitones (-24 to +24).
            index_rate: Feature retrieval strength (0.0-1.0).
                Higher = more target voice character.
            filter_radius: Pitch median filter radius (0-7).
            rms_mix_rate: Volume envelope mixing (0.0-1.0).
                0 = use source envelope, 1 = constant volume.
            protect: Voiceless consonant protection (0.0-0.5).
            f0_method: Pitch extraction algorithm.
                Options: rmvpe (best), harvest, crepe, pm.
        """
        self.model_name = model_name
        self.pitch_shift = pitch_shift
        self.index_rate = index_rate
        self.filter_radius = filter_radius
        self.rms_mix_rate = rms_mix_rate
        self.protect = protect
        self.f0_method = f0_method

        # Validate model exists
        self._model_path, self._index_path = _find_model(model_name)
        if self._model_path is None:
            print(
                f"   ⚠️  RVC model '{model_name}' not found. "
                f"Place .pth file in {RVC_MODELS_DIR}/"
            )

        # Find venv
        self._venv_dir = _find_rvc_venv()
        if self._venv_dir is None:
            print(
                f"   ⚠️  RVC venv not found. "
                f"Run setup_rvc_venv.py to create it."
            )

    @property
    def is_ready(self) -> bool:
        """Whether the converter has a valid model and venv."""
        return (
            self._model_path is not None
            and self._model_path.exists()
            and self._venv_dir is not None
            and is_rvc_available()
        )

    def convert(self, input_path: str, output_path: str) -> bool:
        """Convert a WAV file through the RVC voice model.

        Args:
            input_path: Path to input WAV file.
            output_path: Path for output WAV file.

        Returns:
            True if conversion succeeded.
        """
        if not self.is_ready:
            print(f"   ⚠️  RVC not ready, skipping voice conversion")
            return False

        python = _get_venv_python(self._venv_dir)
        if python is None:
            return False

        # Build the inference command
        config = {
            "input_path": str(Path(input_path).resolve()),
            "output_path": str(Path(output_path).resolve()),
            "model_path": str(self._model_path.resolve()),
            "index_path": str(self._index_path.resolve()) if self._index_path else "",
            "pitch_shift": self.pitch_shift,
            "index_rate": self.index_rate,
            "filter_radius": self.filter_radius,
            "rms_mix_rate": self.rms_mix_rate,
            "protect": self.protect,
            "f0_method": self.f0_method,
        }

        # Write config to temp file (avoids shell escaping issues)
        config_path = Path(output_path).parent / "_rvc_config.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")

        # Get the inference script path
        script_path = Path(__file__).parent / RVC_INFERENCE_SCRIPT

        try:
            print(f"   🎭 RVC converting: {self.model_name} "
                  f"(pitch={self.pitch_shift:+d}, "
                  f"f0={self.f0_method})...")

            result = subprocess.run(
                [str(python), str(script_path), str(config_path)],
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
            )

            if result.returncode != 0:
                print(f"   ❌ RVC failed: {result.stderr[:200]}")
                return False

            if Path(output_path).exists():
                print(f"   ✅ RVC conversion complete")
                return True
            else:
                print(f"   ❌ RVC output file not created")
                return False

        except subprocess.TimeoutExpired:
            print(f"   ❌ RVC timed out after 5 minutes")
            return False
        except FileNotFoundError:
            print(f"   ❌ RVC venv Python not found")
            return False
        finally:
            config_path.unlink(missing_ok=True)

    def convert_samples(
        self,
        samples: list[float],
        sample_rate: int = 44100,
        temp_dir: Path | None = None,
    ) -> list[float] | None:
        """Convert audio samples through the RVC voice model.

        Convenience method that handles WAV I/O internally.

        Args:
            samples: Input audio samples in [-1.0, 1.0].
            sample_rate: Sample rate of the input audio.
            temp_dir: Directory for temporary files.

        Returns:
            Converted audio samples, or None if conversion failed.
        """
        from bark_engine.audio_io import read_wav_file, write_wav_file

        work_dir = temp_dir or Path("_temp_bark")
        work_dir.mkdir(parents=True, exist_ok=True)

        input_path = str(work_dir / "_rvc_input.wav")
        output_path = str(work_dir / "_rvc_output.wav")

        write_wav_file(input_path, samples, sample_rate)

        success = self.convert(input_path, output_path)

        if success and Path(output_path).exists():
            result_samples, _ = read_wav_file(output_path)
            # Clean up temp files
            Path(input_path).unlink(missing_ok=True)
            Path(output_path).unlink(missing_ok=True)
            return result_samples

        # Clean up on failure
        Path(input_path).unlink(missing_ok=True)
        Path(output_path).unlink(missing_ok=True)
        return None
