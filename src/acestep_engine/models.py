"""Domain models for the ACE-Step music engine."""

from __future__ import annotations

import json
from dataclasses import dataclass

from pydantic import BaseModel, Field


@dataclass(frozen=True)
class AceStepConfig:
    """Configuration for an ACE-Step music generation request.

    Field names match the canonical names on ACE-Step's
    GenerateMusicRequest Pydantic model so the wire payload is the
    dataclass dump with no translation step.
    """

    prompt: str
    lyrics: str
    bpm: int | None = None
    audio_duration: int = 60
    key_scale: str = ""
    time_signature: str = ""
    vocal_language: str = "en"
    seed: int = -1
    inference_steps: int = 8
    guidance_scale: float = 0.0
    shift: float = 3.0
    thinking: bool = True
    lm_temperature: float = 0.85
    lm_top_k: int = 0
    lm_top_p: float = 0.9
    lm_cfg_scale: float = 2.0
    lm_negative_prompt: str = ""
    infer_method: str = "ode"
    batch_size: int = 1
    task_type: str = "text2music"
    src_audio_path: str = ""
    repainting_start: float = 0.0
    repainting_end: float = -1.0
    audio_cover_strength: float = 1.0
    reference_audio_path: str = ""
    repaint_mode: str = ""
    repaint_strength: float = 0.5
    repaint_latent_crossfade_frames: int = 0
    repaint_wav_crossfade_sec: float = 0.0
    cover_noise_strength: float = 0.0
    timesteps: str = ""
    use_cot_caption: bool = True
    use_cot_language: bool = True
    # upstream ACE-Step hardcodes True everywhere; False causes noise on xl-sft
    constrained_decoding: bool = True
    lm_repetition_penalty: float = 1.0
    use_adg: bool = False
    cfg_interval_start: float = 0.0
    cfg_interval_end: float = 1.0
    sampler_mode: str = "euler"
    velocity_norm_threshold: float = 0.0
    velocity_ema_factor: float = 0.0
    latent_shift: float = 0.0
    latent_rescale: float = 1.0
    model: str = ""
    lora_path: str = ""


@dataclass(frozen=True)
class LoraTrainingConfig:
    """Parameters for a single LoKR training run.

    Mirrors the subset of ``StartLoKRTrainingRequest`` fields exposed by
    the ACE-Step training HTTP API that songmaker cares about. Defaults
    match the upstream Gradio UI so the server behaviour is unchanged.
    """

    tensor_dir: str
    output_dir: str
    lokr_linear_dim: int = 64
    lokr_linear_alpha: int = 128
    lokr_factor: int = -1
    lokr_decompose_both: bool = False
    lokr_use_tucker: bool = False
    lokr_use_scalar: bool = False
    lokr_weight_decompose: bool = True
    learning_rate: float = 0.03
    train_epochs: int = 500
    train_batch_size: int = 1
    gradient_accumulation: int = 4
    save_every_n_epochs: int = 5
    training_shift: float = 3.0
    training_seed: int = 42
    gradient_checkpointing: bool = False


@dataclass(frozen=True)
class LoraTrainingResult:
    """Outcome of a LoKR training run + export.

    ``adapter_dir`` is the exported adapter directory the client can pass
    straight to ``/v1/lora/load``.
    """

    adapter_dir: str


@dataclass(frozen=True)
class AceStepResult:
    """Result from an ACE-Step generation.

    Contains raw WAV bytes from the server. The caller is responsible
    for decoding to numpy arrays via audio_engine.read_wav_bytes().
    """

    wav_bytes: bytes
    seed: int
    cot_caption: str = ""
    cot_lyrics: str = ""
    requested_batch_size: int | None = None
    delivered_batch_size: int | None = None


@dataclass(frozen=True)
class ServerInfo:
    """ACE-Step server identity returned by /health."""

    model: str
    lm_model: str
    version: str


class TaskSubmitData(BaseModel):
    """Inner data from a /release_task response."""

    task_id: str = ""
    status: str = ""


class TaskSubmitResponse(BaseModel):
    """Top-level /release_task response envelope."""

    data: TaskSubmitData = Field(default_factory=TaskSubmitData)
    code: int = 200


class ResultItem(BaseModel):
    """A single generation result entry from the server."""

    file: str = ""
    seed_value: str = ""
    cot_caption: str = ""
    cot_lyrics: str = ""
    error: str | None = None
    status_message: str | None = None
    requested_batch_size: int | None = None
    delivered_batch_size: int | None = None

    @property
    def seed(self) -> int:
        """Parse seed from server's seed_value string (e.g. '12345' or '')."""
        try:
            return int(self.seed_value)
        except (ValueError, TypeError):
            return -1


class TaskQueryEntry(BaseModel):
    """One entry in the /query_result data list."""

    task_id: str = ""
    status: int = 0
    result: str | list = "[]"
    progress_text: str = ""

    def parse_result_items(self) -> list[ResultItem]:
        raw = self.result
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return []
        if isinstance(raw, list):
            return [ResultItem.model_validate(item) for item in raw if isinstance(item, dict)]
        return []


class TaskQueryResponse(BaseModel):
    """Top-level /query_result response envelope."""

    data: list[TaskQueryEntry] = Field(default_factory=list)
