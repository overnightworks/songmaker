"""DiffSinger ONNX inference engine."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import yaml

from .ds_builder import build_tensors
from .models import (
    DiffSingerResult,
    VocalPhrase,
    VoicebankConfig,
    VocoderConfig,
)

# Default diffusion steps for reflow models
DEFAULT_STEPS = 20


class DiffSingerEngine:
    """Orchestrates DiffSinger ONNX inference for singing voice synthesis.

    Usage:
        engine = DiffSingerEngine(voicebank_dir="path/to/tiger")
        result = engine.generate(phrase)
    """

    def __init__(
        self,
        voicebank_dir: str | Path,
        vocoder_dir: str | Path | None = None,
        device: str = "cuda",
        steps: int = DEFAULT_STEPS,
    ):
        self.voicebank_dir = Path(voicebank_dir)
        self.device = device
        self.steps = steps

        # Load voicebank config
        self.config = self._load_voicebank_config()

        # Resolve vocoder directory
        if vocoder_dir is not None:
            self.vocoder_dir = Path(vocoder_dir)
        elif self.config.vocoder_dir is not None:
            self.vocoder_dir = self.config.vocoder_dir
        else:
            raise ValueError("No vocoder directory specified")

        self.vocoder_config = self._load_vocoder_config()

        # Load speaker embeddings
        self.speaker_embeds: dict[str, np.ndarray] = {}
        for spk_name in self.config.speakers:
            emb_path = self.voicebank_dir / f"{spk_name}.emb"
            if emb_path.exists():
                with open(emb_path, "rb") as f:
                    embed = np.frombuffer(f.read(), dtype=np.float32).copy()
                self.speaker_embeds[spk_name] = embed

        # Lazy-loaded ONNX sessions
        self._acoustic_session = None
        self._vocoder_session = None
        self._linguistic_session = None
        self._pitch_session = None
        self._variance_session = None

    def _load_voicebank_config(self) -> VoicebankConfig:
        """Parse dsconfig.yaml from the voicebank directory."""
        config_path = self.voicebank_dir / "dsconfig.yaml"
        if not config_path.exists():
            raise FileNotFoundError(f"dsconfig.yaml not found in {self.voicebank_dir}")

        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        config = VoicebankConfig(base_dir=self.voicebank_dir)

        # Load phoneme map
        phonemes_file = raw.get("phonemes", "phonemes.txt")
        ph_path = self.voicebank_dir / phonemes_file
        if ph_path.exists():
            if ph_path.suffix == ".json":
                with open(ph_path, "r", encoding="utf-8") as f:
                    config.phoneme_map = json.load(f)
            else:
                # Line-indexed text file
                with open(ph_path, "r", encoding="utf-8") as f:
                    for idx, line in enumerate(f):
                        ph = line.strip()
                        if ph:
                            config.phoneme_map[ph] = idx

        # Model paths
        if raw.get("acoustic"):
            config.acoustic_path = self.voicebank_dir / raw["acoustic"]
        if raw.get("linguistic"):
            config.linguistic_path = self.voicebank_dir / raw["linguistic"]
        if raw.get("dur"):
            config.dur_path = self.voicebank_dir / raw["dur"]
        if raw.get("pitch"):
            config.pitch_path = self.voicebank_dir / raw["pitch"]
        if raw.get("variance"):
            config.variance_path = self.voicebank_dir / raw["variance"]

        # Vocoder — first check as subdirectory of voicebank, then parent
        vocoder_name = raw.get("vocoder", "")
        if vocoder_name:
            # Check if vocoder is a subdirectory of the voicebank
            vocoder_subdir = self.voicebank_dir / vocoder_name
            if vocoder_subdir.is_dir():
                config.vocoder_dir = vocoder_subdir
            else:
                # Try to find vocoder in parent checkpoints dir
                checkpoints_dir = self.voicebank_dir.parent
                for subdir in checkpoints_dir.iterdir():
                    if subdir.is_dir() and vocoder_name.replace("-", "_") in subdir.name.replace("-", "_"):
                        config.vocoder_dir = subdir
                        break

        # Speakers
        config.speakers = raw.get("speakers", [])
        config.hidden_size = raw.get("hidden_size", 256)

        # Feature flags
        config.use_lang_id = raw.get("use_lang_id", False)
        config.use_key_shift_embed = raw.get("use_key_shift_embed", False)
        config.use_speed_embed = raw.get("use_speed_embed", False)
        config.use_energy_embed = raw.get("use_energy_embed", False)
        config.use_breathiness_embed = raw.get("use_breathiness_embed", False)
        config.use_voicing_embed = raw.get("use_voicing_embed", False)
        config.use_tension_embed = raw.get("use_tension_embed", False)
        config.use_expr = raw.get("use_expr", False)
        config.use_note_rest = raw.get("use_note_rest", False)
        config.use_continuous_acceleration = raw.get("use_continuous_acceleration", True)
        config.use_variable_depth = raw.get("use_variable_depth", False)
        config.max_depth = raw.get("max_depth", 0.0)

        # Variance prediction
        config.predict_dur = raw.get("predict_dur", False)
        config.predict_energy = raw.get("predict_energy", False)
        config.predict_breathiness = raw.get("predict_breathiness", False)
        config.predict_voicing = raw.get("predict_voicing", False)
        config.predict_tension = raw.get("predict_tension", False)

        # Audio
        config.sample_rate = raw.get("sample_rate", 44100)
        config.hop_size = raw.get("hop_size", 512)
        config.num_mel_bins = raw.get("num_mel_bins", 128)
        config.mel_base = raw.get("mel_base", "e")
        config.mel_scale = raw.get("mel_scale", "slaney")

        # Augmentation
        aug = raw.get("augmentation_args", {})
        pitch_range = aug.get("random_pitch_shifting", {}).get("range", [-5.0, 5.0])
        config.pitch_shift_range = tuple(pitch_range)

        return config

    def _load_vocoder_config(self) -> VocoderConfig:
        """Parse vocoder.yaml from the vocoder directory."""
        vc = VocoderConfig()
        config_path = self.vocoder_dir / "vocoder.yaml"

        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f)
            model_name = raw.get("model", "model.onnx")
            vc.model_path = self.vocoder_dir / model_name
            vc.sample_rate = raw.get("sample_rate", 44100)
            vc.hop_size = raw.get("hop_size", 512)
            vc.num_mel_bins = raw.get("num_mel_bins", 128)
            # If vocoder.yaml doesn't specify mel_base, inherit from acoustic config
            vc.mel_base = raw.get("mel_base", self.config.mel_base)
            vc.mel_scale = raw.get("mel_scale", self.config.mel_scale)
        else:
            # Look for any .onnx file
            for onnx_file in self.vocoder_dir.glob("*.onnx"):
                vc.model_path = onnx_file
                break
            vc.mel_base = self.config.mel_base
            vc.mel_scale = self.config.mel_scale

        return vc

    def _get_ort_session(self, model_path: Path):
        """Create an ONNX Runtime inference session."""
        import onnxruntime as ort

        available = ort.get_available_providers()
        providers = []
        if self.device == "cuda":
            if "CUDAExecutionProvider" in available:
                providers.append("CUDAExecutionProvider")
            elif "DmlExecutionProvider" in available:
                providers.append("DmlExecutionProvider")
        providers.append("CPUExecutionProvider")

        sess_options = ort.SessionOptions()
        sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        session = ort.InferenceSession(
            str(model_path),
            sess_options=sess_options,
            providers=providers,
        )
        actual = session.get_providers()
        print(f"| ORT providers: {actual}")
        return session

    @property
    def acoustic_session(self):
        if self._acoustic_session is None:
            if self.config.acoustic_path is None or not self.config.acoustic_path.exists():
                raise FileNotFoundError(
                    f"Acoustic model not found: {self.config.acoustic_path}"
                )
            print(f"| Loading acoustic model: {self.config.acoustic_path.name}")
            self._acoustic_session = self._get_ort_session(self.config.acoustic_path)
        return self._acoustic_session

    @property
    def vocoder_session(self):
        if self._vocoder_session is None:
            if self.vocoder_config.model_path is None or not self.vocoder_config.model_path.exists():
                raise FileNotFoundError(
                    f"Vocoder model not found: {self.vocoder_config.model_path}"
                )
            print(f"| Loading vocoder: {self.vocoder_config.model_path.name}")
            self._vocoder_session = self._get_ort_session(self.vocoder_config.model_path)
        return self._vocoder_session

    def _get_speaker_embed(self, voice: str, n_frames: int) -> np.ndarray | None:
        """Get speaker embedding expanded to (1, n_frames, hidden_size)."""
        if not self.speaker_embeds:
            return None

        # Try exact match first
        embed = None
        for name, emb in self.speaker_embeds.items():
            if voice.lower() in name.lower():
                embed = emb
                break

        if embed is None:
            # Use first available speaker
            embed = next(iter(self.speaker_embeds.values()))

        return np.tile(
            embed.reshape(1, 1, -1), (1, n_frames, 1)
        ).astype(np.float32)

    def generate(self, phrase: VocalPhrase) -> DiffSingerResult:
        """Generate singing voice from a VocalPhrase.

        Args:
            phrase: The vocal phrase to synthesize.

        Returns:
            DiffSingerResult with audio samples.
        """
        # Get speaker embedding
        speaker_embed = None
        if self.speaker_embeds:
            for name, emb in self.speaker_embeds.items():
                if phrase.voice.lower() in name.lower():
                    speaker_embed = emb
                    break
            if speaker_embed is None:
                speaker_embed = next(iter(self.speaker_embeds.values()))

        # Build inference tensors
        tensors = build_tensors(phrase, self.config, speaker_embed)

        # Run acoustic model
        mel = self._run_acoustic(tensors)

        # Convert mel base if needed
        mel = self._convert_mel_base(mel)

        # Run vocoder
        waveform = self._run_vocoder(mel, tensors.f0_hz)

        # Normalize to [-1, 1]
        max_val = np.abs(waveform).max()
        if max_val > 0:
            waveform = waveform / max_val * 0.95

        duration = len(waveform) / self.config.sample_rate

        return DiffSingerResult(
            samples=waveform,
            sample_rate=self.config.sample_rate,
            duration=duration,
            phrase_id=phrase.phrase_id,
        )

    def _run_acoustic(self, tensors) -> np.ndarray:
        """Run the acoustic ONNX model."""
        session = self.acoustic_session

        # Get available input names
        input_names = {inp.name for inp in session.get_inputs()}

        inputs = {}
        inputs["tokens"] = tensors.tokens
        inputs["durations"] = tensors.durations
        inputs["f0"] = tensors.f0_hz

        # Acceleration — scalar tensors (shape [])
        if "steps" in input_names:
            inputs["steps"] = np.array(self.steps, dtype=np.int64)
        if "speedup" in input_names and "steps" not in input_names:
            inputs["speedup"] = np.array(max(1, 1000 // self.steps), dtype=np.int64)

        # Expression inputs — always provide if the model expects them
        if "energy" in input_names:
            if tensors.energy is not None:
                inputs["energy"] = tensors.energy
            else:
                inputs["energy"] = np.zeros((1, tensors.n_frames), dtype=np.float32)
        if "breathiness" in input_names:
            if tensors.breathiness is not None:
                inputs["breathiness"] = tensors.breathiness
            else:
                inputs["breathiness"] = np.zeros((1, tensors.n_frames), dtype=np.float32)
        if "tension" in input_names:
            if tensors.tension is not None:
                inputs["tension"] = tensors.tension
            else:
                inputs["tension"] = np.zeros((1, tensors.n_frames), dtype=np.float32)
        if "gender" in input_names:
            if tensors.gender is not None:
                inputs["gender"] = tensors.gender
            else:
                inputs["gender"] = np.zeros((1, tensors.n_frames), dtype=np.float32)
        if "velocity" in input_names:
            inputs["velocity"] = np.ones((1, tensors.n_frames), dtype=np.float32)

        # Speaker embedding — required if model expects it
        if "spk_embed" in input_names:
            if tensors.spk_embed is not None:
                inputs["spk_embed"] = tensors.spk_embed
            else:
                # Zero embed as fallback
                inputs["spk_embed"] = np.zeros(
                    (1, tensors.n_frames, self.config.hidden_size), dtype=np.float32
                )

        # Depth — scalar tensor (shape [])
        if "depth" in input_names:
            depth = self.config.max_depth if self.config.use_variable_depth else 1.0
            inputs["depth"] = np.array(depth, dtype=np.float32)

        print(f"| Acoustic inference: {tensors.n_frames} frames, {self.steps} steps")
        mel = session.run(["mel"], inputs)[0]
        return mel  # (1, n_frames, num_mel_bins)

    def _convert_mel_base(self, mel: np.ndarray) -> np.ndarray:
        """Convert mel spectrogram base between acoustic and vocoder if needed."""
        acoustic_base = self.config.mel_base
        vocoder_base = self.vocoder_config.mel_base

        if acoustic_base == vocoder_base:
            return mel
        if acoustic_base == "10" and vocoder_base == "e":
            return mel * 2.302585  # ln(10)
        if acoustic_base == "e" and vocoder_base == "10":
            return mel * 0.434294  # 1/ln(10)
        return mel

    def _run_vocoder(self, mel: np.ndarray, f0_hz: np.ndarray) -> np.ndarray:
        """Run the NSF-HiFiGAN vocoder."""
        session = self.vocoder_session
        input_names = {inp.name for inp in session.get_inputs()}

        inputs = {"mel": mel}
        if "f0" in input_names:
            inputs["f0"] = f0_hz

        print(f"| Vocoder inference: mel shape {mel.shape}")
        waveform = session.run(["waveform"], inputs)[0]

        # waveform shape: (1, n_samples) → flatten
        return waveform.squeeze()

    def generate_phrases(
        self, phrases: list[VocalPhrase]
    ) -> list[DiffSingerResult]:
        """Generate multiple phrases sequentially."""
        results = []
        for i, phrase in enumerate(phrases):
            print(f"\n| Generating phrase {i + 1}/{len(phrases)}: {phrase.phrase_id}")
            result = self.generate(phrase)
            results.append(result)
        return results
