"""Core Bark vocal generation engine."""

from __future__ import annotations

import functools
import os
import subprocess
from pathlib import Path

import torch
import torch.serialization

from bark_engine.audio_io import normalize_audio, read_wav_file, write_wav_file
from bark_engine.audio_utils import crossfade, resample, trim_silence
from bark_engine.constants import BARK_SAMPLE_RATE, TARGET_SAMPLE_RATE, TEMP_DIR_NAME
from bark_engine.models import GeneratedVocal, VocalSection, VocalStyle
from bark_engine.text_processing import (
    add_singing_markers,
    build_speaker_preset,
    split_text_into_chunks,
)
from bark_engine.vocal_filters import VOCAL_FILTERS

os.environ["SUNO_USE_SMALL_MODELS"] = "True"
os.environ["SUNO_OFFLOAD_CPU"] = "True"


def _patch_torch_load() -> None:
    """Patch torch.load to use weights_only=False for Bark compatibility.

    PyTorch 2.6+ defaults weights_only=True which breaks Bark's
    checkpoint loading since they contain numpy scalars. This patch
    forces weights_only=False for Bark model files only.
    """
    _original_load = torch.load

    @functools.wraps(_original_load)
    def _patched_load(*args: object, **kwargs: object) -> object:
        if "weights_only" not in kwargs:
            kwargs["weights_only"] = False
        return _original_load(*args, **kwargs)

    torch.load = _patched_load  # type: ignore[assignment]


class BarkVocalEngine:
    """Engine for generating singing vocals using Bark AI on CPU.

    Manages Bark model lifecycle, text chunking, audio generation,
    resampling (24kHz -> 44.1kHz), and vocal post-processing via ffmpeg.

    Usage:
        engine = BarkVocalEngine(temp_dir=Path("_temp"))
        engine.preload_models()
        vocals = engine.generate_vocals([section1, section2])
        engine.cleanup()
    """

    def __init__(self, temp_dir: Path | None = None) -> None:
        """Initialize the Bark vocal engine.

        Args:
            temp_dir: Directory for temporary audio files.
        """
        self._temp_dir = temp_dir or Path(TEMP_DIR_NAME)
        self._models_loaded = False

    @property
    def temp_dir(self) -> Path:
        """Temporary directory path."""
        return self._temp_dir

    def preload_models(self) -> None:
        """Pre-download and cache Bark models.

        Models are ~1.5GB total and cached in HuggingFace cache dir.
        """
        if self._models_loaded:
            return

        _patch_torch_load()

        from bark import preload_models

        print("   🔄 Loading Bark models (CPU, small)...")
        preload_models()
        self._models_loaded = True
        print("   ✅ Bark models loaded")

    def generate_vocals(self, sections: list[VocalSection]) -> list[GeneratedVocal]:
        """Generate singing vocals for all sections.

        Args:
            sections: List of vocal section configurations.

        Returns:
            List of generated vocals with audio samples at 44.1kHz.
        """
        self._temp_dir.mkdir(parents=True, exist_ok=True)
        self.preload_models()

        results: list[GeneratedVocal] = []

        for section in sections:
            print(f"   🎤 Generating: {section.section_id}...")
            raw_samples = self._generate_section_audio(section)
            processed = self._apply_vocal_processing(
                raw_samples, section.section_id, section.style
            )

            results.append(
                GeneratedVocal(
                    section_id=section.section_id,
                    samples=processed,
                    volume=section.volume,
                    gap_after_seconds=section.gap_after_seconds,
                )
            )

        return results

    def _generate_section_audio(self, section: VocalSection) -> list[float]:
        """Generate raw Bark audio for a section with chunking.

        Args:
            section: Vocal section configuration.

        Returns:
            Audio samples at TARGET_SAMPLE_RATE (44.1kHz).
        """
        from bark import generate_audio

        text = section.text
        if section.singing:
            text = add_singing_markers(text)

        chunks = split_text_into_chunks(text)
        speaker = build_speaker_preset(section.language, section.speaker_index)

        all_samples_24k: list[float] = []
        crossfade_samples = int(BARK_SAMPLE_RATE * 0.05)

        for chunk_idx, chunk_text in enumerate(chunks):
            print(
                f"      📝 Chunk {chunk_idx + 1}/{len(chunks)}: "
                f"{chunk_text[:50]}..."
            )

            if section.singing and not chunk_text.startswith("♪"):
                chunk_text = add_singing_markers(chunk_text)

            audio_array = generate_audio(
                chunk_text,
                history_prompt=speaker,
            )

            chunk_samples: list[float] = audio_array.tolist()
            chunk_samples = trim_silence(chunk_samples, threshold=0.01)

            if all_samples_24k and crossfade_samples > 0:
                all_samples_24k = crossfade(
                    all_samples_24k, chunk_samples, crossfade_samples
                )
            else:
                all_samples_24k.extend(chunk_samples)

        resampled = resample(all_samples_24k, BARK_SAMPLE_RATE, TARGET_SAMPLE_RATE)
        return normalize_audio(resampled)

    def _apply_vocal_processing(
        self, samples: list[float], section_id: str, style: VocalStyle
    ) -> list[float]:
        """Apply ffmpeg vocal processing (EQ, compression, reverb).

        Args:
            samples: Raw audio samples at TARGET_SAMPLE_RATE.
            section_id: Section identifier for temp file naming.
            style: Vocal processing style.

        Returns:
            Processed audio samples.
        """
        input_path = str(self._temp_dir / f"{section_id}_raw.wav")
        output_path = str(self._temp_dir / f"{section_id}_proc.wav")

        write_wav_file(input_path, samples, TARGET_SAMPLE_RATE)

        filters = VOCAL_FILTERS.get(style, VOCAL_FILTERS[VocalStyle.SINGING])
        filter_chain = ",".join(filters)

        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                input_path,
                "-af",
                filter_chain,
                "-ar",
                str(TARGET_SAMPLE_RATE),
                "-ac",
                "1",
                output_path,
            ],
            check=True,
            capture_output=True,
        )

        processed, _ = read_wav_file(output_path)
        return processed

    def cleanup(self) -> None:
        """Remove temporary files and directory."""
        if self._temp_dir.exists():
            for f in self._temp_dir.iterdir():
                if f.is_file():
                    f.unlink(missing_ok=True)
            try:
                self._temp_dir.rmdir()
            except OSError:
                pass
