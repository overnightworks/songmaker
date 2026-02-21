"""MusicGen AI instrumental generation — direct import, no subprocess.

Meta's MusicGen generates music from text descriptions.

Model selection is VRAM-aware:
    - musicgen-small  (300M):  ~4-5 GB VRAM  (GTX 1660 Ti)
    - musicgen-medium (1.5B):  ~10-12 GB     (RTX 3090)
    - musicgen-large  (3.3B):  ~16-20 GB     (RTX 3090)

Output: 32 kHz mono audio, resampled to 44.1 kHz stereo for mixing.
Max ~30 seconds per generation. Full songs need segmented generation
with crossfading.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)

MUSICGEN_SAMPLE_RATE: Final[int] = 32000
TARGET_SAMPLE_RATE: Final[int] = 44100

# VRAM thresholds for model auto-selection (in GB)
VRAM_THRESHOLDS: Final[dict[str, float]] = {
    "facebook/musicgen-large": 16.0,
    "facebook/musicgen-medium": 10.0,
    "facebook/musicgen-small": 4.0,
}


def is_musicgen_available() -> bool:
    """Check if MusicGen (audiocraft) is installed and ready to use."""
    try:
        from audiocraft.models import MusicGen  # noqa: F401

        return True
    except ImportError:
        return False


def _detect_best_model() -> str:
    """Auto-detect the best MusicGen model based on available VRAM.

    Returns the largest model that fits in available GPU memory.
    Falls back to musicgen-small for CPU-only systems.
    """
    try:
        import torch

        if torch.cuda.is_available():
            vram_gb = torch.cuda.get_device_properties(0).total_mem / 1e9
            for model, threshold in VRAM_THRESHOLDS.items():
                if vram_gb >= threshold:
                    return model
    except Exception:
        pass

    return "facebook/musicgen-small"


class MusicGenRenderer:
    """AI instrumental generator using Meta's MusicGen (in-process).

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

        # Lazy-loaded MusicGen instance (heavy — downloads model on first use)
        self._model = None

    def _get_model(self):
        """Lazy-load the MusicGen model."""
        if self._model is None:
            import torch
            from audiocraft.models import MusicGen

            device = "cuda" if torch.cuda.is_available() else "cpu"
            self._model = MusicGen.get_pretrained(self._model_name, device=device)
        return self._model

    @property
    def model_name(self) -> str:
        """The resolved model name."""
        return self._model_name

    @property
    def is_ready(self) -> bool:
        """Whether MusicGen is available."""
        return is_musicgen_available()

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
            logger.warning("MusicGen not ready, skipping generation")
            return None

        try:
            import torchaudio

            logger.info(
                "MusicGen generating: %s (%.0fs)...",
                self._model_name, duration_seconds,
            )
            logger.debug("Prompt: %s...", prompt[:80])

            model = self._get_model()
            model.set_generation_params(duration=min(duration_seconds, 30.0))

            wav = model.generate([prompt])

            # wav shape: (batch, channels, samples) — take first batch item
            audio = wav[0].cpu()  # (channels, samples)

            # Save raw to temp, then read back and resample
            work_dir = temp_dir or Path("_temp_musicgen")
            work_dir.mkdir(parents=True, exist_ok=True)
            raw_path = str(work_dir / "_musicgen_raw.wav")

            torchaudio.save(raw_path, audio, sample_rate=MUSICGEN_SAMPLE_RATE)

            from bark_engine.audio_io import read_wav_file
            from bark_engine.audio_utils import resample_audio

            samples, sr = read_wav_file(raw_path)
            Path(raw_path).unlink(missing_ok=True)

            if sr != TARGET_SAMPLE_RATE:
                samples = resample_audio(samples, sr, TARGET_SAMPLE_RATE)

            if output_path is not None:
                from bark_engine.audio_io import write_wav_file

                write_wav_file(output_path, samples, TARGET_SAMPLE_RATE)

            logger.info("MusicGen generation complete (%.1fs)", len(samples) / TARGET_SAMPLE_RATE)
            return samples

        except Exception as exc:
            logger.error("MusicGen failed: %s", exc)
            return None

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
            logger.info("Segment %d/%d:", i + 1, len(prompts))
            segment = self.generate(prompt, duration, temp_dir=temp_dir)
            if segment is None:
                continue

            if combined is None:
                combined = segment
            else:
                combined = crossfade(combined, segment, crossfade_samples)

        return combined
