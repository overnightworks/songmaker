"""Strict Pydantic models for generation parameters and ACE-Step task params.

Three roles:

* :class:`BaseGenerationParams` — the user-facing knob set for ACE-Step. Stored
  on ``Version.generation_params``. Every field is optional; ``None`` means
  "fall back to the AceStepConfig default for that field". ``extra="forbid"``
  rejects typos at the boundary.
* :class:`StoredGenerationParams` — what gets persisted on
  ``Generation.generation_params`` after a run. Inherits the knobs and adds
  resolved/output fields (model id, bpm, key_scale, task type, repaint/cover
  knobs, COT outputs).
* :class:`RepaintTaskParams` / :class:`CoverTaskParams` — strict typed
  replacement for the dict-typed ``repaint_params``/``cover_params`` arq kwargs
  that flow API → arq → worker → ``run_generation_job``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_GEN_PARAM_MAX_STRING_LENGTH = 2000

_VALID_INFER_METHODS = frozenset({"ode", "sde"})
_VALID_REPAINT_MODES = frozenset({"conservative", "balanced", "aggressive"})


class BaseGenerationParams(BaseModel):
    """Knob set for ACE-Step generation, stored on Version.generation_params.

    Every field is optional. ``None`` means "use the AceStepConfig default for
    this field". ``extra="forbid"`` rejects typos at the boundary — this is
    the line of defence that would have caught the 2026-04-08 incident.
    """

    model_config = ConfigDict(extra="forbid")

    inference_steps: int | None = Field(None, ge=1, le=200)
    guidance_scale: float | None = Field(None, ge=0, le=50)
    shift: float | None = Field(None, ge=0, le=100)
    thinking: bool | None = None
    lm_temperature: float | None = Field(None, ge=0, le=5)
    lm_top_k: int | None = Field(None, ge=0, le=1000)
    lm_top_p: float | None = Field(None, ge=0, le=1)
    lm_cfg_scale: float | None = Field(None, ge=0, le=50)
    lm_negative_prompt: str | None = Field(None, max_length=_GEN_PARAM_MAX_STRING_LENGTH)
    infer_method: Literal["ode", "sde"] | None = None
    batch_size: int | None = Field(None, ge=1, le=8)
    reference_audio_path: str | None = Field(None, max_length=500)
    repaint_mode: Literal["conservative", "balanced", "aggressive"] | None = None
    repaint_strength: float | None = Field(None, ge=0, le=1)
    lm_repetition_penalty: float | None = Field(None, ge=0.5, le=5)
    use_cot_caption: bool | None = None
    use_cot_language: bool | None = None
    use_adg: bool | None = None
    cfg_interval_start: float | None = Field(None, ge=0, le=1)
    cfg_interval_end: float | None = Field(None, ge=0, le=1)

    @field_validator("reference_audio_path")
    @classmethod
    def _validate_reference_audio_path(cls, v: str | None) -> str | None:
        if v is not None and ".." in v:
            raise ValueError("reference_audio_path must not contain '..'")
        return v


class StoredGenerationParams(BaseGenerationParams):
    """Persisted on Generation.generation_params after a run completes.

    Adds resolved/output fields that BaseGenerationParams omits because they
    are decided by the worker, not the user (model id, COT outputs, the
    actual task knobs that were applied).
    """

    seed: int | None = None
    acestep_model: str | None = None
    bpm: int | None = None
    audio_duration: int | None = None
    key_scale: str | None = None
    task_type: Literal["text2music", "repaint", "cover"] | None = None
    repainting_start: float | None = None
    repainting_end: float | None = None
    audio_cover_strength: float | None = None
    repaint_latent_crossfade_frames: int | None = None
    repaint_wav_crossfade_sec: float | None = None
    cover_noise_strength: float | None = None
    timesteps: str | None = None
    constrained_decoding: bool | None = None
    cot_caption: str | None = None
    cot_lyrics: str | None = None

    @field_validator("timesteps")
    @classmethod
    def _validate_timesteps(cls, v: str | None) -> str | None:
        if v:
            try:
                [float(t) for t in v.split(",")]
            except ValueError as exc:
                msg = f"timesteps='{v}' must be comma-separated numbers"
                raise ValueError(msg) from exc
        return v


class RepaintTaskParams(BaseModel):
    """Strict typed replacement for the dict-typed ``repaint_params`` arq kwarg.

    Constructed at the API boundary after the source generation has been
    resolved to a wav path. Flows through arq via ``model_dump()`` and is
    rehydrated in :meth:`MusicWorker.generate` via ``model_validate``.
    """

    model_config = ConfigDict(extra="forbid")

    src_wav_path: str
    src_generation_id: str
    repainting_start: float = Field(ge=0.0, le=1.0)
    repainting_end: float = Field(ge=0.0, le=1.0)
    lyrics: str
    prompt: str
    repaint_mode: Literal["conservative", "balanced", "aggressive"] | None = None
    repaint_strength: float | None = Field(None, ge=0, le=1)
    repaint_latent_crossfade_frames: int | None = Field(None, ge=0)
    repaint_wav_crossfade_sec: float | None = Field(None, ge=0)


class CoverTaskParams(BaseModel):
    """Strict typed replacement for the dict-typed ``cover_params`` arq kwarg."""

    model_config = ConfigDict(extra="forbid")

    src_wav_path: str
    src_generation_id: str
    audio_cover_strength: float = Field(ge=0.0, le=1.0)
    lyrics: str
    prompt: str
    cover_noise_strength: float | None = Field(None, ge=0, le=1)
