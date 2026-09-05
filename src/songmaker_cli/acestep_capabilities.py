"""Per-model truth about which ACE-Step parameters are honored, hidden, or clamped.

Single source of truth derived from reading the vendored ACE-Step source.
Adding a new ACE-Step model variant: add one ACESTEP_PROFILES entry.

The matrix this encodes is documented in plans/acestep-model-parameters.md
and verified against the vendored code in vendor/acestep/acestep/.
"""

from __future__ import annotations

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict


class ParamSupport(BaseModel):
    model_config = ConfigDict(frozen=True)

    supported: bool = True
    min: float | None = None
    max: float | None = None
    note: str = ""


class AceStepProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    mode: str
    family: Literal["turbo", "sft", "base"]
    is_xl: bool

    inference_steps: ParamSupport
    guidance_scale: ParamSupport
    shift: ParamSupport
    infer_method: ParamSupport
    use_adg: ParamSupport
    cfg_interval_start: ParamSupport
    cfg_interval_end: ParamSupport

    sampler_mode: ParamSupport
    velocity_norm_threshold: ParamSupport
    velocity_ema_factor: ParamSupport
    latent_shift: ParamSupport
    latent_rescale: ParamSupport
    audio_cover_strength: ParamSupport

    thinking: ParamSupport
    lm_temperature: ParamSupport
    lm_top_k: ParamSupport
    lm_top_p: ParamSupport
    lm_cfg_scale: ParamSupport
    lm_negative_prompt: ParamSupport
    lm_repetition_penalty: ParamSupport
    use_cot_caption: ParamSupport
    use_cot_language: ParamSupport
    batch_size: ParamSupport

    def hidden_param_names(self) -> list[str]:
        result: list[str] = []
        for name, field_info in type(self).model_fields.items():
            if field_info.annotation is not ParamSupport:
                continue
            value = getattr(self, name)
            if not value.supported:
                result.append(name)
        return result

    def max_inference_steps(self) -> int:
        upper = self.inference_steps.max
        return int(upper) if upper is not None else 200


_TURBO_GUIDANCE_OFF = ParamSupport(
    supported=False,
    note="Engine forces guidance_scale=1.0 on turbo distillation.",
)
_TURBO_USE_ADG_OFF = ParamSupport(
    supported=False,
    note="No-op on turbo: classifier-free guidance is disabled, so APG has nothing to project.",
)
_TURBO_CFG_INTERVAL_START_OFF = ParamSupport(
    supported=False,
    note="No-op on turbo: CFG is disabled, so the interval start has no effect.",
)
_TURBO_CFG_INTERVAL_END_OFF = ParamSupport(
    supported=False,
    note="No-op on turbo: CFG is disabled, so the interval end has no effect.",
)


def _shared_profile_params() -> dict[str, ParamSupport]:
    return {
        "sampler_mode": ParamSupport(supported=True),
        "velocity_norm_threshold": ParamSupport(supported=True, min=0.0),
        "velocity_ema_factor": ParamSupport(supported=True, min=0.0, max=1.0),
        "latent_shift": ParamSupport(supported=True),
        "latent_rescale": ParamSupport(supported=True, min=0.1),
        "audio_cover_strength": ParamSupport(supported=True, min=0.0, max=1.0),
        "thinking": ParamSupport(supported=True),
        "lm_temperature": ParamSupport(supported=True, min=0.0, max=2.0),
        "lm_top_k": ParamSupport(supported=True, min=0, max=200),
        "lm_top_p": ParamSupport(supported=True, min=0.0, max=1.0),
        "lm_cfg_scale": ParamSupport(supported=True, min=1.0, max=3.0),
        "lm_negative_prompt": ParamSupport(supported=True),
        "lm_repetition_penalty": ParamSupport(supported=True, min=0.5, max=5.0),
        "use_cot_caption": ParamSupport(supported=True),
        "use_cot_language": ParamSupport(supported=True),
        "batch_size": ParamSupport(supported=True, min=1, max=8),
    }


def _make_turbo(*, mode: str, is_xl: bool) -> AceStepProfile:
    return AceStepProfile(
        mode=mode,
        family="turbo",
        is_xl=is_xl,
        inference_steps=ParamSupport(supported=True, min=1, max=20),
        guidance_scale=_TURBO_GUIDANCE_OFF,
        shift=ParamSupport(supported=True, min=1.0, max=5.0),
        infer_method=ParamSupport(supported=True),
        use_adg=_TURBO_USE_ADG_OFF,
        cfg_interval_start=_TURBO_CFG_INTERVAL_START_OFF,
        cfg_interval_end=_TURBO_CFG_INTERVAL_END_OFF,
        **_shared_profile_params(),
    )


def _make_sft_or_base(
    *, mode: str, is_xl: bool, family: Literal["sft", "base"],
) -> AceStepProfile:
    return AceStepProfile(
        mode=mode,
        family=family,
        is_xl=is_xl,
        inference_steps=ParamSupport(supported=True, min=1, max=200),
        guidance_scale=ParamSupport(supported=True, min=0.0, max=20.0),
        shift=ParamSupport(supported=True, min=1.0, max=5.0),
        infer_method=ParamSupport(supported=True),
        use_adg=ParamSupport(supported=True, note="Honored when guidance_scale > 1.0."),
        cfg_interval_start=ParamSupport(
            supported=True, min=0.0, max=1.0,
            note="Honored when guidance_scale > 1.0.",
        ),
        cfg_interval_end=ParamSupport(
            supported=True, min=0.0, max=1.0,
            note="Honored when guidance_scale > 1.0.",
        ),
        **_shared_profile_params(),
    )


ACESTEP_PROFILES: Final[dict[str, AceStepProfile]] = {
    "turbo": _make_turbo(mode="turbo", is_xl=False),
    "sft": _make_sft_or_base(mode="sft", is_xl=False, family="sft"),
    "xl-turbo": _make_turbo(mode="xl-turbo", is_xl=True),
    "xl-sft": _make_sft_or_base(mode="xl-sft", is_xl=True, family="sft"),
    "xl-base": _make_sft_or_base(mode="xl-base", is_xl=True, family="base"),
}
