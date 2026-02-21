"""Demucs stem separation — direct import, no subprocess.

Splits any audio file into 4 stems: vocals, drums, bass, other.
VRAM: ~3 GB minimum. Use segment=7 for 6 GB GPUs.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

STEM_NAMES: Final[tuple[str, ...]] = ("drums", "bass", "other", "vocals")


def is_demucs_available() -> bool:
    """Check if Demucs is installed and ready to use."""
    try:
        from demucs.pretrained import get_model  # noqa: F401

        return True
    except ImportError:
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
    """Audio stem separation using Meta's Demucs (in-process).

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

        # Lazy-loaded model (heavy — loads torch + model weights)
        self._model = None

    def _get_model(self):
        """Lazy-load the Demucs model."""
        if self._model is None:
            import torch
            from demucs.pretrained import get_model

            self._model = get_model(self.model_name)
            device = "cuda" if torch.cuda.is_available() else "cpu"
            self._model.to(device)
        return self._model

    @property
    def is_ready(self) -> bool:
        """Whether Demucs is available."""
        return is_demucs_available()

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
            print("   Demucs not ready, skipping separation")
            return None

        try:
            import torch
            import torchaudio
            from demucs.apply import apply_model

            print(f"   Demucs separating: {self.model_name}...")

            model = self._get_model()
            device = next(model.parameters()).device

            # Load audio
            wav, sr = torchaudio.load(input_path)
            if wav.shape[0] == 1:
                wav = wav.repeat(2, 1)
            wav = wav.unsqueeze(0).to(device)

            # Separate
            with torch.no_grad():
                sources = apply_model(
                    model, wav, segment=self.segment, device=device,
                )

            # sources shape: (batch, stems, channels, samples)
            source_names = model.sources  # e.g., ['drums', 'bass', 'other', 'vocals']

            # Optionally write stem WAV files
            if output_dir is not None:
                Path(output_dir).mkdir(parents=True, exist_ok=True)
                for i, name in enumerate(source_names):
                    stem = sources[0, i]
                    stem_path = Path(output_dir) / f"{name}.wav"
                    torchaudio.save(str(stem_path), stem.cpu(), sample_rate=sr)

            # Read stems into sample lists
            from bark_engine.audio_io import read_wav_file

            stems: dict[str, list[float]] = {}
            work_dir = temp_dir or Path("_temp_demucs")
            work_dir.mkdir(parents=True, exist_ok=True)

            for i, name in enumerate(source_names):
                stem = sources[0, i]
                stem_path = work_dir / f"_demucs_{name}.wav"
                torchaudio.save(str(stem_path), stem.cpu(), sample_rate=sr)
                samples, _ = read_wav_file(str(stem_path))
                stems[name] = samples
                stem_path.unlink(missing_ok=True)

            print("   Demucs separation complete")

            return SeparatedStems(
                vocals=stems.get("vocals", []),
                drums=stems.get("drums", []),
                bass=stems.get("bass", []),
                other=stems.get("other", []),
                sample_rate=sr,
            )

        except Exception as exc:
            print(f"   Demucs failed: {exc}")
            return None
