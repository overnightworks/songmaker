"""RVC voice conversion — direct import, no subprocess.

Runs RVC inference in-process using rvc-python. Communicates
through WAV files for the file-based API, or directly via
samples for the convenience API.

GPU auto-detection: CUDA when available, CPU fallback.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

RVC_MODELS_DIR: Final[str] = "rvc_models"


def is_rvc_available() -> bool:
    """Check if RVC is installed and ready to use."""
    try:
        from rvc_python.infer import RVCInference  # noqa: F401

        return True
    except ImportError:
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
    """Voice conversion using RVC (in-process).

    Converts input audio through a trained RVC voice model to
    produce natural-sounding vocals.

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
                f"   Warning: RVC model '{model_name}' not found. "
                f"Place .pth file in {RVC_MODELS_DIR}/"
            )

        # Lazy-loaded RVC instance (heavy — loads torch + model)
        self._rvc = None

    @staticmethod
    def _detect_model_version(model_path: Path) -> str:
        """Auto-detect RVC model version (v1 or v2) from checkpoint."""
        import torch

        try:
            ckpt = torch.load(str(model_path), map_location="cpu", weights_only=False)
            return ckpt.get("version", "v2")
        except Exception:
            return "v2"

    def _get_rvc(self):
        """Lazy-load the RVC inference engine."""
        if self._rvc is None:
            import torch
            from rvc_python.infer import RVCInference

            device = "cuda:0" if torch.cuda.is_available() else "cpu"
            version = self._detect_model_version(self._model_path)

            self._rvc = RVCInference(device=device)
            self._rvc.load_model(
                str(self._model_path),
                version=version,
                index_path=str(self._index_path) if self._index_path else "",
            )
            # Set inference parameters via set_params (infer_file only takes 2 args)
            self._rvc.set_params(
                f0method=self.f0_method,
                f0up_key=self.pitch_shift,
                index_rate=self.index_rate,
                filter_radius=self.filter_radius,
                rms_mix_rate=self.rms_mix_rate,
                protect=self.protect,
            )
        return self._rvc

    @property
    def is_ready(self) -> bool:
        """Whether the converter has a valid model and RVC is installed."""
        return (
            self._model_path is not None
            and self._model_path.exists()
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
            print(f"   Warning: RVC not ready, skipping voice conversion")
            return False

        try:
            print(
                f"   RVC converting: {self.model_name} "
                f"(pitch={self.pitch_shift:+d}, f0={self.f0_method})..."
            )

            rvc = self._get_rvc()
            rvc.infer_file(
                str(Path(input_path).resolve()),
                str(Path(output_path).resolve()),
            )

            if Path(output_path).exists():
                print(f"   RVC conversion complete")
                return True
            else:
                print(f"   RVC output file not created")
                return False

        except Exception as exc:
            print(f"   RVC failed: {exc}")
            return False

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
            Path(input_path).unlink(missing_ok=True)
            Path(output_path).unlink(missing_ok=True)
            return result_samples

        Path(input_path).unlink(missing_ok=True)
        Path(output_path).unlink(missing_ok=True)
        return None
