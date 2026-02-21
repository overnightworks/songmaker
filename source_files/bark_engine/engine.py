"""Core Bark vocal generation engine.

Generates singing vocals using Bark AI with multi-take selection.
Each VocalSection generates N takes (default 3), scores them on
quality metrics, and auto-selects the best one.

Vocal caching: processed vocals are saved to a ``_vocal_cache/``
directory so that re-runs skip sections whose config has not changed.
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import subprocess
from pathlib import Path

import torch
import torch.serialization

from bark_engine.audio_io import normalize_audio, read_wav_file, write_wav_file
from bark_engine.audio_utils import crossfade, resample, trim_silence
from bark_engine.constants import BARK_SAMPLE_RATE, TARGET_SAMPLE_RATE, TEMP_DIR_NAME
from bark_engine.models import GeneratedVocal, VocalSection, VocalStyle
from bark_engine.pitch_correction import apply_pitch_correction
from bark_engine.take_selection import (
    TakeScore,
    save_take_metadata,
    score_vocal_take,
    select_best_take,
)
from bark_engine.text_processing import (
    add_singing_markers,
    build_speaker_preset,
    split_text_into_chunks,
)
from bark_engine.vocal_filters import VOCAL_FILTERS

VOCAL_CACHE_DIR_NAME: str = "_vocal_cache"

os.environ["SUNO_USE_SMALL_MODELS"] = "True"
if not torch.cuda.is_available():
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
    resampling (24kHz -> 44.1kHz), multi-take selection, and vocal
    post-processing via ffmpeg.

    Each VocalSection generates num_takes candidates (default 3),
    scores them on energy consistency, silence ratio, clipping, and
    duration match, then auto-selects the highest-scoring take.

    Usage:
        engine = BarkVocalEngine(temp_dir=Path("_temp"))
        engine.preload_models()
        vocals = engine.generate_vocals([section1, section2])
        engine.cleanup()
    """

    def __init__(
        self,
        temp_dir: Path | None = None,
        cache_dir: Path | None = None,
        use_cache: bool = True,
    ) -> None:
        """Initialize the Bark vocal engine.

        Args:
            temp_dir: Directory for temporary audio files.
            cache_dir: Directory for vocal cache files. Defaults to
                ``_vocal_cache/`` in the current working directory.
            use_cache: Whether to use vocal caching (default True).
        """
        self._temp_dir = temp_dir or Path(TEMP_DIR_NAME)
        self._cache_dir = cache_dir or Path(VOCAL_CACHE_DIR_NAME)
        self._use_cache = use_cache
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

        device = "GPU (CUDA)" if torch.cuda.is_available() else "CPU"
        print(f"   🔄 Loading Bark models ({device}, small)...")
        preload_models()
        self._models_loaded = True
        print("   ✅ Bark models loaded")

    def generate_vocals(self, sections: list[VocalSection]) -> list[GeneratedVocal]:
        """Generate singing vocals for all sections with multi-take selection.

        Cached vocals are reused when the section config has not changed.
        For each uncached section, generates num_takes candidates, scores each
        on quality metrics, and auto-selects the best take. Take metadata
        is saved as JSON in the temp directory for debugging.

        Args:
            sections: List of vocal section configurations.

        Returns:
            List of generated vocals with audio samples at 44.1kHz.
        """
        self._temp_dir.mkdir(parents=True, exist_ok=True)
        if self._use_cache:
            self._cache_dir.mkdir(parents=True, exist_ok=True)

        results: list[GeneratedVocal] = []

        for section in sections:
            cached = self._load_from_cache(section)
            if cached is not None:
                results.append(cached)
                continue

            backend = self._resolve_backend(section)

            if backend == "xtts":
                best_samples = self._generate_with_xtts(section)
            else:
                # Bark backend — ensure models are loaded
                self.preload_models()
                best_samples = self._generate_with_take_selection(section)

            pitch_corrected = self._apply_pitch_correction(best_samples, section)
            processed = self._apply_vocal_processing(
                pitch_corrected, section.section_id, section.style
            )
            final = self._apply_rvc(processed, section)

            vocal = GeneratedVocal(
                section_id=section.section_id,
                samples=final,
                volume=section.volume,
                gap_after_seconds=section.gap_after_seconds,
            )
            self._save_to_cache(section, vocal)
            results.append(vocal)

        return results

    # ------------------------------------------------------------------
    # Vocal cache
    # ------------------------------------------------------------------

    @staticmethod
    def _section_cache_key(section: VocalSection) -> str:
        """Compute a deterministic hash for a VocalSection config.

        The hash covers all fields that affect the generated audio so the
        cache is automatically invalidated when any parameter changes.
        """
        key_data = {
            "text": section.text,
            "language": str(section.language),
            "speaker_index": section.speaker_index,
            "style": str(section.style),
            "singing": section.singing,
            "num_takes": section.num_takes,
            "pitch_correction_intensity": section.pitch_correction_intensity,
            "pitch_correction_key": section.pitch_correction_key,
            "pitch_correction_scale": section.pitch_correction_scale,
            "backend": section.backend,
            "voice_ref": section.voice_ref,
            "rvc_model": section.rvc_model,
            "rvc_pitch_shift": section.rvc_pitch_shift,
            "rvc_index_rate": section.rvc_index_rate,
        }
        blob = json.dumps(key_data, sort_keys=True).encode()
        return hashlib.sha256(blob).hexdigest()[:16]

    def _cache_path(self, section: VocalSection) -> Path:
        """Return the cache WAV path for a section."""
        h = self._section_cache_key(section)
        return self._cache_dir / f"{section.section_id}_{h}.wav"

    def _cache_meta_path(self, section: VocalSection) -> Path:
        """Return the cache metadata JSON path for a section."""
        h = self._section_cache_key(section)
        return self._cache_dir / f"{section.section_id}_{h}.json"

    def _load_from_cache(self, section: VocalSection) -> GeneratedVocal | None:
        """Try to load a previously cached vocal for this section."""
        if not self._use_cache:
            return None

        wav_path = self._cache_path(section)
        if not wav_path.exists():
            return None

        try:
            samples, _ = read_wav_file(str(wav_path))
            if not samples:
                return None
            print(f"   ⚡ Cache hit: {section.section_id} (skipping generation)")
            return GeneratedVocal(
                section_id=section.section_id,
                samples=samples,
                volume=section.volume,
                gap_after_seconds=section.gap_after_seconds,
            )
        except Exception:
            return None

    def _save_to_cache(self, section: VocalSection, vocal: GeneratedVocal) -> None:
        """Save generated vocal to the cache directory."""
        if not self._use_cache:
            return

        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            write_wav_file(
                str(self._cache_path(section)),
                vocal.samples,
                TARGET_SAMPLE_RATE,
            )
            # Save metadata so users can inspect what config produced this
            meta = {
                "section_id": section.section_id,
                "cache_key": self._section_cache_key(section),
                "text": section.text,
                "style": str(section.style),
                "language": str(section.language),
                "speaker_index": section.speaker_index,
                "num_takes": section.num_takes,
            }
            self._cache_meta_path(section).write_text(
                json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            print(f"   💾 Cached: {section.section_id}")
        except Exception as exc:
            print(f"   ⚠️  Cache write failed for {section.section_id}: {exc}")

    def _generate_with_take_selection(self, section: VocalSection) -> list[float]:
        """Generate multiple takes and select the best one.

        Args:
            section: Vocal section configuration with num_takes.

        Returns:
            Audio samples from the highest-scoring take.
        """
        num_takes = max(1, section.num_takes)
        expected_duration = self._estimate_section_duration(section)

        takes: list[tuple[list[float], TakeScore]] = []

        for take_idx in range(num_takes):
            take_number = take_idx + 1
            print(
                f"   🎤 Generating: {section.section_id} "
                f"(take {take_number}/{num_takes})..."
            )

            raw_samples = self._generate_section_audio(section)

            score = score_vocal_take(
                raw_samples,
                take_number=take_number,
                expected_duration_seconds=expected_duration,
                sample_rate=TARGET_SAMPLE_RATE,
            )

            takes.append((raw_samples, score))

        best_samples, best_score = select_best_take(takes, verbose=True)

        all_scores = [score for _, score in takes]
        save_take_metadata(
            section.section_id,
            all_scores,
            best_score.take_number,
            self._temp_dir,
        )

        return best_samples

    @staticmethod
    def _apply_pitch_correction(
        samples: list[float], section: VocalSection
    ) -> list[float]:
        """Apply pitch correction to vocal audio if enabled.

        Corrects pitch drift by quantizing detected frequencies to the
        nearest note in the target scale. Intensity controls the blend
        between original and corrected pitch.

        Args:
            samples: Raw audio samples at TARGET_SAMPLE_RATE.
            section: Vocal section with pitch correction configuration.

        Returns:
            Pitch-corrected audio (or original if intensity is 0.0).
        """
        if section.pitch_correction_intensity <= 0.0:
            return samples

        print(
            f"      🎵 Pitch correction "
            f"({section.pitch_correction_key} "
            f"{section.pitch_correction_scale}, "
            f"intensity={section.pitch_correction_intensity:.1f})..."
        )

        return apply_pitch_correction(
            samples,
            intensity=section.pitch_correction_intensity,
            key=section.pitch_correction_key,
            scale=section.pitch_correction_scale,
            sample_rate=TARGET_SAMPLE_RATE,
        )

    @staticmethod
    def _estimate_section_duration(section: VocalSection) -> float:
        """Estimate expected vocal duration from text length.

        Uses a heuristic of ~0.3 seconds per word for singing,
        ~0.2 seconds per word for spoken/rap styles.

        Args:
            section: Vocal section configuration.

        Returns:
            Estimated duration in seconds.
        """
        word_count = len(section.text.split())
        seconds_per_word = (
            0.2 if section.style in (VocalStyle.RAP, VocalStyle.SPOKEN) else 0.3
        )

        return word_count * seconds_per_word

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

    def _apply_rvc(
        self, samples: list[float], section: VocalSection
    ) -> list[float]:
        """Apply RVC voice conversion if configured.

        Converts vocals through a trained RVC voice model to produce
        more natural-sounding output. Runs in an isolated Python 3.12
        venv via subprocess.

        Args:
            samples: Processed audio samples at TARGET_SAMPLE_RATE.
            section: Vocal section with RVC configuration.

        Returns:
            Voice-converted audio (or original if RVC is not configured).
        """
        if section.rvc_model is None:
            return samples

        try:
            from rvc_engine import RVCConverter, is_rvc_available
        except ImportError:
            print(f"   ⚠️  rvc_engine not found, skipping RVC")
            return samples

        if not is_rvc_available():
            print(
                f"   ⚠️  RVC not available for {section.section_id} "
                f"(run setup_rvc_venv.py to install)"
            )
            return samples

        converter = RVCConverter(
            model_name=section.rvc_model,
            pitch_shift=section.rvc_pitch_shift,
            index_rate=section.rvc_index_rate,
        )

        result = converter.convert_samples(
            samples,
            sample_rate=TARGET_SAMPLE_RATE,
            temp_dir=self._temp_dir,
        )

        if result is not None:
            return result

        print(f"   ⚠️  RVC conversion failed, using original audio")
        return samples

    @staticmethod
    def _resolve_backend(section: VocalSection) -> str:
        """Resolve the vocal backend for a section.

        When backend="auto", uses XTTS for spoken/whispered/rap styles
        and Bark for singing/epic/shout styles.

        Args:
            section: Vocal section configuration.

        Returns:
            Resolved backend name ("bark" or "xtts").
        """
        if section.backend == "auto":
            xtts_styles = {VocalStyle.SPOKEN, VocalStyle.WHISPER, VocalStyle.RAP}
            if section.style in xtts_styles:
                # Check if XTTS is actually available
                try:
                    from xtts_engine import is_xtts_available
                    if is_xtts_available():
                        return "xtts"
                except ImportError:
                    pass
            return "bark"
        return section.backend

    def _generate_with_xtts(self, section: VocalSection) -> list[float]:
        """Generate vocals using XTTS v2 backend.

        Falls back to Bark if XTTS is not available.

        Args:
            section: Vocal section configuration.

        Returns:
            Audio samples at TARGET_SAMPLE_RATE (44.1kHz).
        """
        try:
            from xtts_engine import XTTSConverter, is_xtts_available
        except ImportError:
            print(f"   xtts_engine not found, falling back to Bark")
            self.preload_models()
            return self._generate_with_take_selection(section)

        if not is_xtts_available():
            print(f"   XTTS not available, falling back to Bark")
            self.preload_models()
            return self._generate_with_take_selection(section)

        language = "en" if section.language.value == "en" else "de"
        converter = XTTSConverter(
            voice_ref=section.voice_ref,
            language=language,
        )

        result = converter.synthesize_samples(
            text=section.text,
            language=language,
            sample_rate=TARGET_SAMPLE_RATE,
            temp_dir=self._temp_dir,
        )

        if result is not None:
            return result

        print(f"   XTTS synthesis failed, falling back to Bark")
        self.preload_models()
        return self._generate_with_take_selection(section)

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
