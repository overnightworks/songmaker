"""DiffSinger ONNX inference engine — full 4-stage pipeline.

Pipeline:
  1. Linguistic encoder → hidden states from phoneme tokens
  2. Duration predictor → phoneme durations (frames)
  3. Pitch predictor → expressive f0 curve (MIDI semitones)
  4. Acoustic model → mel spectrogram
  5. Vocoder → waveform
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import yaml

from .ds_builder import PhraseTensors, build_phrase_tensors, midi_to_hz
from .models import (
    DiffSingerResult,
    VocalPhrase,
    VoicebankConfig,
    VocoderConfig,
)

DEFAULT_STEPS = 20


class DiffSingerEngine:
    """Orchestrates DiffSinger ONNX inference for singing voice synthesis.

    Usage:
        engine = DiffSingerEngine(voicebank_dir="path/to/tiger_voice")
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

        # Load top-level voicebank config
        self.config = self._load_voicebank_config()

        # Resolve sub-model directories
        self.dur_dir = self.voicebank_dir / "dsdur"
        self.pitch_dir = self.voicebank_dir / "dspitch"
        self.acoustic_dir = self.voicebank_dir / "dsacoustic"

        # Resolve vocoder
        if vocoder_dir is not None:
            self.vocoder_dir = Path(vocoder_dir)
        elif self.config.vocoder_dir is not None:
            self.vocoder_dir = self.config.vocoder_dir
        else:
            raise ValueError("No vocoder directory specified")

        self.vocoder_config = self._load_vocoder_config()

        # Load phoneme maps for each sub-model
        self.dur_phoneme_map = self._load_phoneme_map(self.dur_dir / "files" / "phonemes.txt")
        self.pitch_phoneme_map = self._load_phoneme_map(self.pitch_dir / "files" / "phonemes.txt")
        self.acoustic_phoneme_map = self._load_phoneme_map(
            self.acoustic_dir / "phonemes.txt"
        )

        # Use the acoustic phoneme map as the primary one
        self.config.phoneme_map = self.acoustic_phoneme_map

        # Load speaker embeddings from each sub-model
        self.dur_speaker_embeds = self._load_speaker_embeds(self.dur_dir / "files")
        self.pitch_speaker_embeds = self._load_speaker_embeds(self.pitch_dir / "files")
        self.acoustic_speaker_embeds = self._load_speaker_embeds(self.acoustic_dir)

        # Lazy-loaded ONNX sessions
        self._dur_linguistic_session = None
        self._dur_session = None
        self._pitch_linguistic_session = None
        self._pitch_session = None
        self._acoustic_session = None
        self._vocoder_session = None

    def _load_phoneme_map(self, path: Path) -> dict[str, int]:
        """Load a phoneme→index map from a text file."""
        ph_map = {}
        if not path.exists():
            return ph_map
        with open(path, "r", encoding="utf-8") as f:
            for idx, line in enumerate(f):
                ph = line.strip()
                if ph:
                    ph_map[ph] = idx
        return ph_map

    def _load_speaker_embeds(self, directory: Path) -> dict[str, np.ndarray]:
        """Load .emb speaker embedding files from a directory."""
        embeds = {}
        if not directory.exists():
            return embeds
        for emb_path in directory.glob("*.emb"):
            with open(emb_path, "rb") as f:
                embed = np.frombuffer(f.read(), dtype=np.float32).copy()
            embeds[emb_path.stem] = embed
        return embeds

    def _load_voicebank_config(self) -> VoicebankConfig:
        """Parse top-level dsconfig.yaml."""
        config_path = self.voicebank_dir / "dsconfig.yaml"
        if not config_path.exists():
            raise FileNotFoundError(f"dsconfig.yaml not found in {self.voicebank_dir}")

        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        config = VoicebankConfig(base_dir=self.voicebank_dir)

        # Model paths (acoustic)
        if raw.get("acoustic"):
            config.acoustic_path = self.voicebank_dir / raw["acoustic"]

        # Vocoder
        vocoder_name = raw.get("vocoder", "")
        if vocoder_name:
            vocoder_subdir = self.voicebank_dir / vocoder_name
            if vocoder_subdir.is_dir():
                config.vocoder_dir = vocoder_subdir
            else:
                checkpoints_dir = self.voicebank_dir.parent
                for subdir in checkpoints_dir.iterdir():
                    if subdir.is_dir() and vocoder_name.replace("-", "_") in subdir.name.replace("-", "_"):
                        config.vocoder_dir = subdir
                        break

        config.speakers = raw.get("speakers", [])
        config.hidden_size = raw.get("hidden_size", 256)

        # Feature flags
        config.use_key_shift_embed = raw.get("use_key_shift_embed", False)
        config.use_speed_embed = raw.get("use_speed_embed", False)
        config.use_energy_embed = raw.get("use_energy_embed", False)
        config.use_breathiness_embed = raw.get("use_breathiness_embed", False)
        config.use_voicing_embed = raw.get("use_voicing_embed", False)
        config.use_tension_embed = raw.get("use_tension_embed", False)
        config.use_expr = raw.get("use_expr", True)
        config.use_note_rest = raw.get("use_note_rest", True)
        config.use_continuous_acceleration = raw.get("use_continuous_acceleration", True)
        config.use_variable_depth = raw.get("use_variable_depth", False)
        config.max_depth = raw.get("max_depth", 0.0)

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
        """Parse vocoder.yaml."""
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
            vc.mel_base = raw.get("mel_base", self.config.mel_base)
            vc.mel_scale = raw.get("mel_scale", self.config.mel_scale)
        else:
            for onnx_file in self.vocoder_dir.glob("*.onnx"):
                vc.model_path = onnx_file
                break
            vc.mel_base = self.config.mel_base
            vc.mel_scale = self.config.mel_scale

        return vc

    # ── ONNX session management ──────────────────────────────────

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
            str(model_path), sess_options=sess_options, providers=providers,
        )
        actual = session.get_providers()
        print(f"| ORT [{model_path.name}]: {actual}")
        return session

    @property
    def dur_linguistic_session(self):
        if self._dur_linguistic_session is None:
            path = self.dur_dir / "files" / "linguistic.onnx"
            print(f"| Loading dur linguistic: {path.name}")
            self._dur_linguistic_session = self._get_ort_session(path)
        return self._dur_linguistic_session

    @property
    def dur_session(self):
        if self._dur_session is None:
            path = self.dur_dir / "files" / "dur.onnx"
            print(f"| Loading dur predictor: {path.name}")
            self._dur_session = self._get_ort_session(path)
        return self._dur_session

    @property
    def pitch_linguistic_session(self):
        if self._pitch_linguistic_session is None:
            path = self.pitch_dir / "files" / "linguistic.onnx"
            print(f"| Loading pitch linguistic: {path.name}")
            self._pitch_linguistic_session = self._get_ort_session(path)
        return self._pitch_linguistic_session

    @property
    def pitch_session(self):
        if self._pitch_session is None:
            path = self.pitch_dir / "files" / "pitch.onnx"
            print(f"| Loading pitch predictor: {path.name}")
            self._pitch_session = self._get_ort_session(path)
        return self._pitch_session

    @property
    def acoustic_session(self):
        if self._acoustic_session is None:
            path = self.config.acoustic_path
            if path is None or not path.exists():
                raise FileNotFoundError(f"Acoustic model not found: {path}")
            print(f"| Loading acoustic: {path.name}")
            self._acoustic_session = self._get_ort_session(path)
        return self._acoustic_session

    @property
    def vocoder_session(self):
        if self._vocoder_session is None:
            path = self.vocoder_config.model_path
            if path is None or not path.exists():
                raise FileNotFoundError(f"Vocoder not found: {path}")
            print(f"| Loading vocoder: {path.name}")
            self._vocoder_session = self._get_ort_session(path)
        return self._vocoder_session

    # ── Speaker embedding helpers ────────────────────────────────

    def _get_speaker_embed(
        self, embeds: dict[str, np.ndarray], voice: str, n: int, mode: str = "token"
    ) -> np.ndarray:
        """Get speaker embedding expanded to the right shape.

        mode="token": (1, n, hidden_size) for token-level models
        mode="frame": (1, n, hidden_size) for frame-level models
        """
        embed = None
        for name, emb in embeds.items():
            if voice.lower() in name.lower():
                embed = emb
                break
        if embed is None and embeds:
            embed = next(iter(embeds.values()))
        if embed is None:
            embed = np.zeros(self.config.hidden_size, dtype=np.float32)

        return np.tile(embed.reshape(1, 1, -1), (1, n, 1)).astype(np.float32)

    # ── Pipeline stages ──────────────────────────────────────────

    def _run_dur_linguistic(self, tensors: PhraseTensors) -> tuple[np.ndarray, np.ndarray]:
        """Stage 1a: Linguistic encoder for duration prediction.

        Returns: (encoder_out, x_masks)
        """
        # Re-tokenize for the dur model's phoneme map
        tokens = self._retokenize(tensors, self.dur_phoneme_map)

        session = self.dur_linguistic_session
        input_names = {inp.name for inp in session.get_inputs()}

        inputs = {"tokens": tokens}
        if "word_div" in input_names:
            inputs["word_div"] = tensors.word_div
            inputs["word_dur"] = tensors.word_dur
        elif "ph_dur" in input_names:
            inputs["ph_dur"] = tensors.ph_dur

        encoder_out, x_masks = session.run(["encoder_out", "x_masks"], inputs)
        return encoder_out, x_masks

    def _run_dur_predictor(
        self,
        encoder_out: np.ndarray,
        x_masks: np.ndarray,
        tensors: PhraseTensors,
        voice: str,
    ) -> np.ndarray:
        """Stage 1b: Duration predictor.

        Returns: predicted phoneme durations (int64, frames)
        """
        session = self.dur_session
        input_names = {inp.name for inp in session.get_inputs()}

        spk_embed = self._get_speaker_embed(
            self.dur_speaker_embeds, voice, tensors.n_tokens, mode="token"
        )

        inputs = {
            "encoder_out": encoder_out,
            "x_masks": x_masks,
            "ph_midi": tensors.ph_midi,
            "spk_embed": spk_embed,
        }

        ph_dur_pred = session.run(["ph_dur_pred"], inputs)[0]  # float (1, n_tokens)

        # Round to integer frames, ensure >= 1 for non-padding
        dur_frames = np.maximum(np.round(ph_dur_pred).astype(np.int64), 1)
        return dur_frames  # (1, n_tokens)

    def _run_pitch_linguistic(self, tensors: PhraseTensors, ph_dur: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Stage 2a: Linguistic encoder for pitch prediction.

        Returns: (encoder_out, x_masks)
        """
        tokens = self._retokenize(tensors, self.pitch_phoneme_map)

        session = self.pitch_linguistic_session
        inputs = {
            "tokens": tokens,
            "ph_dur": ph_dur,
        }

        encoder_out, x_masks = session.run(["encoder_out", "x_masks"], inputs)
        return encoder_out, x_masks

    def _run_pitch_predictor(
        self,
        encoder_out: np.ndarray,
        ph_dur: np.ndarray,
        tensors: PhraseTensors,
        voice: str,
    ) -> np.ndarray:
        """Stage 2b: Pitch predictor — generates expressive f0 curve.

        Returns: pitch_pred in MIDI semitones (float32, (1, n_frames))
        """
        session = self.pitch_session
        input_names = {inp.name for inp in session.get_inputs()}

        n_frames = int(ph_dur.sum())

        inputs = {
            "encoder_out": encoder_out,
            "ph_dur": ph_dur,
            "note_midi": tensors.note_midi,
            "note_dur": tensors.note_dur,
        }

        # Initial pitch — 60.0 placeholder since retake=True everywhere
        inputs["pitch"] = np.full((1, n_frames), 60.0, dtype=np.float32)

        # Retake — all True (generate all frames fresh)
        inputs["retake"] = np.ones((1, n_frames), dtype=bool)

        # Expression — controls vibrato/expressiveness (0-1)
        if "expr" in input_names:
            inputs["expr"] = np.full((1, n_frames), tensors.expr, dtype=np.float32)

        # Note rest
        if "note_rest" in input_names:
            inputs["note_rest"] = tensors.note_rest

        # Speaker embedding
        if "spk_embed" in input_names:
            inputs["spk_embed"] = self._get_speaker_embed(
                self.pitch_speaker_embeds, voice, n_frames, mode="frame"
            )

        # Diffusion steps
        if "steps" in input_names:
            inputs["steps"] = np.array(self.steps, dtype=np.int64)
        if "speedup" in input_names and "steps" not in input_names:
            inputs["speedup"] = np.array(max(1, 1000 // self.steps), dtype=np.int64)

        print(f"| Pitch prediction: {n_frames} frames, {self.steps} steps")
        pitch_pred = session.run(["pitch_pred"], inputs)[0]  # (1, n_frames) MIDI semitones
        return pitch_pred

    def _run_acoustic(
        self,
        tensors: PhraseTensors,
        ph_dur: np.ndarray,
        f0_hz: np.ndarray,
        voice: str,
    ) -> np.ndarray:
        """Stage 3: Acoustic model — generates mel spectrogram.

        Returns: mel (1, n_frames, num_mel_bins)
        """
        session = self.acoustic_session
        input_names = {inp.name for inp in session.get_inputs()}

        n_frames = int(ph_dur.sum())

        # Re-tokenize for acoustic phoneme map
        tokens = self._retokenize(tensors, self.acoustic_phoneme_map)

        inputs = {
            "tokens": tokens,
            "durations": ph_dur,
            "f0": f0_hz,
        }

        # Gender
        if "gender" in input_names:
            inputs["gender"] = np.full((1, n_frames), tensors.gender, dtype=np.float32)

        # Velocity
        if "velocity" in input_names:
            inputs["velocity"] = np.full(
                (1, n_frames), tensors.velocity, dtype=np.float32
            )

        # Speaker embedding
        if "spk_embed" in input_names:
            inputs["spk_embed"] = self._get_speaker_embed(
                self.acoustic_speaker_embeds, voice, n_frames, mode="frame"
            )

        # Depth
        if "depth" in input_names:
            depth = self.config.max_depth if self.config.use_variable_depth else 1.0
            inputs["depth"] = np.array(depth, dtype=np.float32)

        # Steps
        if "steps" in input_names:
            inputs["steps"] = np.array(self.steps, dtype=np.int64)
        if "speedup" in input_names and "steps" not in input_names:
            inputs["speedup"] = np.array(max(1, 1000 // self.steps), dtype=np.int64)

        print(f"| Acoustic inference: {n_frames} frames, {self.steps} steps")
        mel = session.run(["mel"], inputs)[0]
        return mel

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
        """Stage 4: Vocoder — mel + f0 → waveform."""
        session = self.vocoder_session
        input_names = {inp.name for inp in session.get_inputs()}

        inputs = {"mel": mel}
        if "f0" in input_names:
            inputs["f0"] = f0_hz

        print(f"| Vocoder inference: mel shape {mel.shape}")
        waveform = session.run(["waveform"], inputs)[0]
        return waveform.squeeze()

    def _retokenize(self, tensors: PhraseTensors, phoneme_map: dict[str, int]) -> np.ndarray:
        """Re-map token IDs from the primary phoneme map to a sub-model's map.

        Since all sub-models may have different phoneme orderings, we need to
        map from the original phoneme strings to each model's specific IDs.
        """
        # Reverse the acoustic phoneme map to get phoneme strings
        reverse_map = {v: k for k, v in self.acoustic_phoneme_map.items()}
        original_tokens = tensors.tokens[0]

        new_tokens = []
        for tok in original_tokens:
            ph_name = reverse_map.get(int(tok), "SP")
            if ph_name in phoneme_map:
                new_tokens.append(phoneme_map[ph_name])
            elif ph_name.lower() in phoneme_map:
                new_tokens.append(phoneme_map[ph_name.lower()])
            else:
                new_tokens.append(phoneme_map.get("SP", phoneme_map.get("<PAD>", 0)))

        return np.array(new_tokens, dtype=np.int64).reshape(1, -1)

    # ── Main generation ──────────────────────────────────────────

    def generate(
        self, phrase: VocalPhrase, use_pred_dur: bool = False
    ) -> DiffSingerResult:
        """Generate singing voice from a VocalPhrase using the full pipeline.

        Args:
            phrase: The vocal phrase to synthesize.
            use_pred_dur: If True, use the neural duration predictor.
                If False (default), use hand-crafted durations computed
                directly from note durations for precise timing control.
        """
        voice = phrase.voice

        # Build input tensors
        tensors = build_phrase_tensors(phrase, self.config)

        # Stage 1: Duration
        has_dur_model = (self.dur_dir / "files" / "dur.onnx").exists()
        if use_pred_dur and has_dur_model:
            print("| Stage 1: Duration prediction (neural)")
            enc_out, x_masks = self._run_dur_linguistic(tensors)
            ph_dur = self._run_dur_predictor(enc_out, x_masks, tensors, voice)
            ph_dur = self._enforce_min_phoneme_dur(ph_dur, min_frames=8)
            ph_dur = self._constrain_total_dur(ph_dur, tensors.n_frames)
            print(f"|   Predicted durations: {ph_dur[0].tolist()}")
        else:
            # Use hand-crafted durations from note definitions
            ph_dur = tensors.ph_dur
            print(f"| Stage 1: Using score durations ({tensors.n_frames} frames)")

        n_frames = int(ph_dur.sum())

        # Stage 2: Pitch prediction
        has_pitch_model = (self.pitch_dir / "files" / "pitch.onnx").exists()
        if has_pitch_model:
            print("| Stage 2: Pitch prediction")

            # Adjust note_dur to match predicted n_frames
            note_dur_adjusted = self._adjust_note_dur(tensors.note_dur, n_frames)

            # Create adjusted tensors
            adjusted = PhraseTensors(
                tokens=tensors.tokens,
                n_tokens=tensors.n_tokens,
                word_div=tensors.word_div,
                word_dur=tensors.word_dur,
                ph_midi=tensors.ph_midi,
                note_midi=tensors.note_midi,
                note_dur=note_dur_adjusted,
                note_rest=tensors.note_rest,
                ph_dur=ph_dur,
                n_frames=n_frames,
                expr=tensors.expr,
                gender=tensors.gender,
                velocity=tensors.velocity,
            )

            enc_out_pitch, _ = self._run_pitch_linguistic(adjusted, ph_dur)
            pitch_midi = self._run_pitch_predictor(enc_out_pitch, ph_dur, adjusted, voice)

            # Convert MIDI semitones → Hz for acoustic model
            f0_hz = np.where(
                pitch_midi > 0,
                440.0 * np.power(2.0, (pitch_midi - 69.0) / 12.0),
                0.0,
            ).astype(np.float32)

            print(f"|   Pitch range: {pitch_midi.min():.1f} - {pitch_midi.max():.1f} MIDI")
        else:
            # Build f0 from note MIDI (flat, no expression)
            print("| No pitch model, using flat MIDI→Hz")
            f0_frames = []
            for i in range(tensors.n_tokens):
                midi_val = tensors._phoneme_midi[i]
                hz = midi_to_hz(midi_val) if midi_val > 0 else 0.0
                dur = int(ph_dur[0, i])
                f0_frames.extend([hz] * dur)
            f0_hz = np.array(f0_frames[:n_frames], dtype=np.float32).reshape(1, -1)

        # Stage 3: Acoustic model
        print("| Stage 3: Acoustic synthesis")
        mel = self._run_acoustic(tensors, ph_dur, f0_hz, voice)

        # Convert mel base if needed
        mel = self._convert_mel_base(mel)

        # Stage 4: Vocoder
        print("| Stage 4: Vocoder")
        waveform = self._run_vocoder(mel, f0_hz)

        # Loudness leveling — even out energy dips in sustained notes
        waveform = self._level_loudness(waveform)

        # Normalize
        max_val = np.abs(waveform).max()
        if max_val > 0:
            waveform = waveform / max_val * 0.95

        # Optional RVC
        if phrase.rvc_model is not None:
            waveform = self._apply_rvc(waveform, phrase)

        duration = len(waveform) / self.config.sample_rate

        # Validation: compare actual vs expected duration
        expected_sec = n_frames * self.config.hop_size / self.config.sample_rate
        drift_pct = abs(duration - expected_sec) / expected_sec * 100 if expected_sec > 0 else 0
        status = "OK" if drift_pct < 5 else "DRIFT"
        print(f"| [{status}] {phrase.phrase_id}: {duration:.2f}s actual vs {expected_sec:.2f}s expected ({drift_pct:.1f}% drift)")

        return DiffSingerResult(
            samples=waveform,
            sample_rate=self.config.sample_rate,
            duration=duration,
            phrase_id=phrase.phrase_id,
        )

    @staticmethod
    def _level_loudness(
        waveform: np.ndarray,
        window_sec: float = 0.3,
        target_rms: float = 0.22,
        max_gain: float = 5.0,
        sr: int = 44100,
    ) -> np.ndarray:
        """Even out volume dips using windowed RMS gain with smooth interpolation."""
        from scipy.ndimage import gaussian_filter1d

        window = int(sr * window_sec)
        hop = window // 4
        n = len(waveform)
        if n < window:
            return waveform

        # Measure RMS at each hop position
        positions = list(range(0, n - window + 1, hop))
        rms_values = np.array([
            np.sqrt(np.mean(waveform[p:p + window] ** 2)) for p in positions
        ])

        # Compute gain: boost quiet parts toward target_rms
        gains = np.where(
            rms_values > 0.005,
            np.minimum(target_rms / rms_values, max_gain),
            1.0,
        )

        # Heavy gaussian smoothing to avoid artifacts
        gains = gaussian_filter1d(gains, sigma=8)

        # Interpolate gain to sample-level
        centers = np.array(positions) + window // 2
        sample_gains = np.interp(np.arange(n), centers, gains)

        return (waveform * sample_gains).astype(np.float32)

    @staticmethod
    def _enforce_min_phoneme_dur(
        ph_dur: np.ndarray, min_frames: int = 8
    ) -> np.ndarray:
        """Enforce minimum duration per phoneme for clear articulation.

        Very short phonemes (< ~93ms at hop=512/sr=44100) produce garbled,
        unintelligible output. This stretches short phonemes to the minimum
        and borrows frames from the longest neighbor to keep total stable.
        """
        dur = ph_dur.copy()
        n = dur.shape[1]

        for i in range(n):
            if dur[0, i] < min_frames:
                deficit = min_frames - dur[0, i]
                dur[0, i] = min_frames
                # Borrow from longest phoneme to keep total roughly stable
                longest = int(np.argmax(dur[0]))
                if dur[0, longest] > min_frames + deficit:
                    dur[0, longest] -= deficit

        return dur

    @staticmethod
    def _constrain_total_dur(
        ph_dur: np.ndarray, target_frames: int
    ) -> np.ndarray:
        """Scale predicted phoneme durations so total matches intended duration.

        DiffSinger's duration predictor often outputs significantly more frames
        than the intended note durations, causing phrases to overshoot their
        beat windows and overlap. This rescales proportionally while preserving
        the minimum phoneme duration.
        """
        dur = ph_dur.copy()
        predicted_total = int(dur.sum())
        if predicted_total <= 0 or target_frames <= 0:
            return dur

        ratio = target_frames / predicted_total
        if abs(ratio - 1.0) < 0.05:
            # Close enough — just adjust the longest
            diff = target_frames - predicted_total
            if diff != 0:
                longest = int(np.argmax(dur[0]))
                dur[0, longest] += diff
            return dur

        # Scale all durations proportionally
        scaled = np.maximum(np.round(dur * ratio).astype(np.int64), 1)

        # Fix rounding error
        diff = target_frames - int(scaled.sum())
        if diff != 0:
            longest = int(np.argmax(scaled[0]))
            scaled[0, longest] += diff
            if scaled[0, longest] < 1:
                scaled[0, longest] = 1

        return scaled

    def _adjust_note_dur(self, note_dur: np.ndarray, target_frames: int) -> np.ndarray:
        """Adjust note durations to sum to target_frames."""
        adjusted = note_dur.copy()
        current_total = int(adjusted.sum())
        diff = target_frames - current_total
        if diff != 0:
            # Distribute difference across the longest note
            longest_idx = int(np.argmax(adjusted[0]))
            adjusted[0, longest_idx] += diff
            if adjusted[0, longest_idx] < 1:
                adjusted[0, longest_idx] = 1
        return adjusted

    def _apply_rvc(self, waveform: np.ndarray, phrase: VocalPhrase) -> np.ndarray:
        """Apply RVC voice conversion to the generated waveform."""
        try:
            from rvc_engine import RVCConverter, is_rvc_available

            if not is_rvc_available():
                print("| RVC not available, skipping voice conversion")
                return waveform

            print(f"| RVC voice conversion: model={phrase.rvc_model}")
            converter = RVCConverter(
                model_name=phrase.rvc_model,
                pitch_shift=phrase.rvc_pitch_shift,
                index_rate=phrase.rvc_index_rate,
            )

            if not converter.is_ready:
                print(f"| RVC model '{phrase.rvc_model}' not found, skipping")
                return waveform

            result = converter.convert_samples(
                waveform.tolist(),
                sample_rate=self.config.sample_rate,
            )

            if result is not None:
                print(f"| RVC conversion complete: {len(result)} samples")
                return np.array(result, dtype=np.float32)
            else:
                print("| RVC conversion failed, using original")
                return waveform

        except ImportError:
            print("| rvc_engine not installed, skipping voice conversion")
            return waveform

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
