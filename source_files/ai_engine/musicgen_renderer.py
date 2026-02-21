"""MusicGen AI instrumental generation via isolated subprocess.

Meta's MusicGen generates music from text descriptions. This module
runs MusicGen in a separate Python 3.12 venv via subprocess to avoid
dependency conflicts with Python 3.14.

Architecture:
    Main process (Python 3.14)
        -> writes config JSON with prompt + duration
        -> calls venv Python with inference script
        -> reads output WAV back
        -> resamples to 44.1kHz stereo

Model selection is VRAM-aware:
    - musicgen-small  (300M):  ~4-5 GB VRAM  (GTX 1660 Ti)
    - musicgen-medium (1.5B):  ~10-12 GB     (RTX 3090)
    - musicgen-large  (3.3B):  ~16-20 GB     (RTX 3090)

Output: 32 kHz mono audio, resampled to 44.1 kHz stereo for mixing.
Max ~30 seconds per generation. Full songs need segmented generation
with crossfading.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Final

VENV_DIR: Final[str] = "_rvc_venv"  # Shared venv with RVC/XTTS
INFERENCE_SCRIPT: Final[str] = "_musicgen_infer.py"
MUSICGEN_SAMPLE_RATE: Final[int] = 32000
TARGET_SAMPLE_RATE: Final[int] = 44100

# VRAM thresholds for model auto-selection (in GB)
VRAM_THRESHOLDS: Final[dict[str, float]] = {
    "facebook/musicgen-large": 16.0,
    "facebook/musicgen-medium": 10.0,
    "facebook/musicgen-small": 4.0,
}


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


def is_musicgen_available() -> bool:
    """Check if MusicGen is installed and ready to use."""
    venv_dir = _find_venv()
    if venv_dir is None:
        return False

    python = _get_venv_python(venv_dir)
    if python is None:
        return False

    try:
        result = subprocess.run(
            [str(python), "-c", "from audiocraft.models import MusicGen; print('ok')"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode == 0 and "ok" in result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _detect_best_model() -> str:
    """Auto-detect the best MusicGen model based on available VRAM.

    Returns the largest model that fits in available GPU memory.
    Falls back to musicgen-small for CPU-only systems.
    """
    venv_dir = _find_venv()
    if venv_dir is None:
        return "facebook/musicgen-small"

    python = _get_venv_python(venv_dir)
    if python is None:
        return "facebook/musicgen-small"

    try:
        result = subprocess.run(
            [str(python), "-c",
             "import torch; "
             "print(torch.cuda.get_device_properties(0).total_mem / 1e9 "
             "if torch.cuda.is_available() else 0)"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            vram_gb = float(result.stdout.strip())
            for model, threshold in VRAM_THRESHOLDS.items():
                if vram_gb >= threshold:
                    return model
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        pass

    return "facebook/musicgen-small"


class MusicGenRenderer:
    """AI instrumental generator using Meta's MusicGen.

    Generates backing tracks from text prompts like
    "melodic house, deep bass, 124 BPM, E minor".

    Usage:
        renderer = MusicGenRenderer()
        samples = renderer.generate(
            prompt="melodic house, deep bass, 124 BPM",
            duration_seconds=15,
        )
    """

    def __init__(
        self,
        model_name: str = "auto",
    ) -> None:
        """Initialize the MusicGen renderer.

        Args:
            model_name: Model identifier. "auto" picks the best model
                for available VRAM.
        """
        if model_name == "auto":
            self._model_name = _detect_best_model()
        else:
            self._model_name = model_name

        self._venv_dir = _find_venv()
        if self._venv_dir is None:
            print(
                f"   Warning: Isolated venv not found. "
                f"Run setup_rvc_venv.py to create it."
            )

    @property
    def model_name(self) -> str:
        """The resolved model name."""
        return self._model_name

    @property
    def is_ready(self) -> bool:
        """Whether MusicGen is available."""
        return self._venv_dir is not None and is_musicgen_available()

    def generate(
        self,
        prompt: str,
        duration_seconds: float = 10.0,
        output_path: str | None = None,
        temp_dir: Path | None = None,
    ) -> list[float] | None:
        """Generate instrumental audio from a text prompt.

        Args:
            prompt: Text description of the music to generate.
            duration_seconds: Duration in seconds (max ~30).
            output_path: Optional output WAV path. If None, returns samples.
            temp_dir: Directory for temporary files.

        Returns:
            Audio samples at 44.1 kHz (mono), or None if generation failed.
            If output_path is provided, also saves to that path.
        """
        if not self.is_ready:
            print(f"   MusicGen not ready, skipping generation")
            return None

        python = _get_venv_python(self._venv_dir)
        if python is None:
            return None

        work_dir = temp_dir or Path("_temp_musicgen")
        work_dir.mkdir(parents=True, exist_ok=True)

        raw_output = str(work_dir / "_musicgen_raw.wav")

        config = {
            "prompt": prompt,
            "output_path": str(Path(raw_output).resolve()),
            "duration_seconds": min(duration_seconds, 30.0),
            "model_name": self._model_name,
            "sample_rate": MUSICGEN_SAMPLE_RATE,
        }

        config_path = work_dir / "_musicgen_config.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")

        script_path = Path(__file__).parent / INFERENCE_SCRIPT

        try:
            print(
                f"   MusicGen generating: {self._model_name} "
                f"({duration_seconds:.0f}s)..."
            )
            print(f"   Prompt: {prompt[:80]}...")

            result = subprocess.run(
                [str(python), str(script_path), str(config_path)],
                capture_output=True,
                text=True,
                timeout=600,  # 10 minute timeout for large models
            )

            if result.returncode != 0:
                print(f"   MusicGen failed: {result.stderr[:200]}")
                return None

            if not Path(raw_output).exists():
                print(f"   MusicGen output file not created")
                return None

            # Read and resample to target sample rate
            from bark_engine.audio_io import read_wav_file
            from bark_engine.audio_utils import resample_audio

            samples, sr = read_wav_file(raw_output)
            Path(raw_output).unlink(missing_ok=True)

            if sr != TARGET_SAMPLE_RATE:
                samples = resample_audio(samples, sr, TARGET_SAMPLE_RATE)

            # Save to output path if requested
            if output_path is not None:
                from bark_engine.audio_io import write_wav_file
                write_wav_file(output_path, samples, TARGET_SAMPLE_RATE)

            print(f"   MusicGen generation complete ({len(samples)/TARGET_SAMPLE_RATE:.1f}s)")
            return samples

        except subprocess.TimeoutExpired:
            print(f"   MusicGen timed out after 10 minutes")
            return None
        except FileNotFoundError:
            print(f"   MusicGen venv Python not found")
            return None
        finally:
            config_path.unlink(missing_ok=True)

    def generate_sections(
        self,
        prompts: list[tuple[str, float]],
        crossfade_seconds: float = 2.0,
        temp_dir: Path | None = None,
    ) -> list[float] | None:
        """Generate a longer piece by concatenating multiple segments.

        MusicGen has a ~30 second limit per generation. This method
        generates multiple segments and crossfades them together.

        Args:
            prompts: List of (prompt, duration_seconds) tuples.
            crossfade_seconds: Crossfade duration between segments.
            temp_dir: Directory for temporary files.

        Returns:
            Combined audio samples at 44.1 kHz, or None if all failed.
        """
        from bark_engine.audio_utils import crossfade

        combined: list[float] | None = None
        crossfade_samples = int(crossfade_seconds * TARGET_SAMPLE_RATE)

        for i, (prompt, duration) in enumerate(prompts):
            print(f"   Segment {i+1}/{len(prompts)}:")
            segment = self.generate(prompt, duration, temp_dir=temp_dir)
            if segment is None:
                continue

            if combined is None:
                combined = segment
            else:
                combined = crossfade(combined, segment, crossfade_samples)

        return combined
