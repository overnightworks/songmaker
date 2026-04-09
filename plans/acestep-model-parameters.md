# ACE-Step model parameters — implementation plan

## Decisions needed before starting

1. **Change 1** (ship `use_adg` for sft variants) — approve as a separate small PR? **Recommended yes.**
2. **Change 2** (Pydantic profile refactor) — approve as a follow-up PR? **Recommended yes.**
3. **Change 3** (expose `use_cot_metas`) — do you actually want this control? **Default no unless you say.**
4. **UI tooltips** — implement as Option C (native `title` now, popover later)? **Recommended yes.**

Everything else is research and rationale that lives elsewhere (memory + this matrix).

## Authoritative parameter × model matrix

Verified against vendored code in `_models/acestep/acestep/`. Where the upstream docs disagree with the code, the code wins. Common bounds (e.g. `lm_temperature` 0.0–2.0) are not duplicated here — see [GenerationParams](src/songmaker_cli/api_models/songs.py) for the global Pydantic-enforced range.

### DiT (diffusion) parameters

| Parameter | turbo / xl-turbo | sft / xl-sft | base / xl-base | Source |
|---|---|---|---|---|
| `inference_steps` | max 20, default 8 | max 200, default 50 | max 200, default 50 | docs (Tutorial L272), confirmed in code |
| `guidance_scale` | **forced to 1.0** by engine | honored when > 1.0 | honored when > 1.0 | [generate_music.py:262](_models/acestep/acestep/core/generation/handler/generate_music.py#L262) |
| `shift` | honored | honored | honored | code, all variants |
| `infer_method` (`ode`/`sde`) | honored | honored | honored | code, all variants |
| `use_adg` | no-op (CFG forced off) | honored when CFG > 1.0 | honored when CFG > 1.0 | [service_generate_execute.py:108](_models/acestep/acestep/core/generation/handler/service_generate_execute.py#L108) |
| `cfg_interval_start` | no-op | honored when CFG > 1.0 | honored when CFG > 1.0 | same |
| `cfg_interval_end` | no-op | honored when CFG > 1.0 | honored when CFG > 1.0 | same |
| `timesteps` (advanced override) | honored | honored | honored | code |

### LM (chain-of-thought) parameters

All DiT variants honor these uniformly. The mode-level opt-outs (Cover, Extract, Repaint-with-codes skip the LM entirely) are independent of which DiT variant you pick.

| Parameter | All variants | Note |
|---|---|---|
| `thinking` | ✅ | Force-disabled in cover/extract/repaint-with-codes mode regardless. |
| `lm_temperature` | ✅ | |
| `lm_top_k` | ✅ | |
| `lm_top_p` | ✅ | |
| `lm_cfg_scale` | ✅ | LM-side CFG, distinct from DiT `guidance_scale`. |
| `lm_negative_prompt` | ✅ | |
| `lm_repetition_penalty` | ✅ | |
| `use_cot_caption` | ✅ | |
| `use_cot_language` | ✅ | |
| `batch_size` | ✅ | Engine clamps to MAX_BATCH_SIZE. |

### Comparison vs current `_MODEL_CAPABILITIES`

Looking at [config.py:119–135](src/songmaker_cli/config.py#L119-L135), the only **wrong** entries are:
- `sft.hidden_params: ["use_adg"]` — `use_adg` is honored on sft, should not be hidden
- `xl-sft.hidden_params: ["use_adg"]` — same

Everything else (turbo hides guidance + CFG-related, sft/base/xl-* show steps up to 200, turbo max 20) is correct.

## Change 1 — Show `use_adg` for sft / xl-sft

**Diff**: two lines in [config.py](src/songmaker_cli/config.py).

```python
"sft":    {"max_inference_steps": 200, "hidden_params": []},
"xl-sft": {"max_inference_steps": 200, "hidden_params": []},
```

**Risk**: low. Existing presets/versions that don't set `use_adg` are unaffected. New users get a control that previously wasn't reachable.

**Test**: extend `tests/test_config.py` to assert `use_adg not in get_model_capabilities()["sft"]["hidden_params"]`.

**Ship as its own PR**, do not bundle into Change 2 — it's a one-line user-facing fix and shouldn't be blocked on the structural cleanup.

## Change 2 — Pydantic profile refactor

Replace the dict-of-dict `_MODEL_CAPABILITIES` with a typed `AceStepProfile` Pydantic model in a new module. Backwards-compatible: the existing `get_model_capabilities()` becomes a derived adapter, frontend wire format unchanged.

### Shape (sketch — not full implementation)

```python
# src/songmaker_cli/acestep_capabilities.py

class ParamSupport(BaseModel):
    model_config = {"frozen": True}
    supported: bool = True
    min: float | None = None
    max: float | None = None
    note: str = ""

class AceStepProfile(BaseModel):
    model_config = {"frozen": True}
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

    def hidden_param_names(self) -> list[str]: ...
    def max_inference_steps(self) -> int: ...

ACESTEP_PROFILES: Final[dict[str, AceStepProfile]] = { ... }
```

Each `ParamSupport` carries an accurate per-field `note` (do **not** reuse a single shared `_TURBO_OVERRIDES` constant — each turbo override needs its own note explaining what about that specific parameter is overridden, not a copy-paste of the guidance_scale story).

### Adapter to keep current API stable

`get_model_capabilities()` in [config.py](src/songmaker_cli/config.py) becomes:

```python
def get_model_capabilities() -> dict[str, dict[str, object]]:
    return {
        mode: {
            "max_inference_steps": p.max_inference_steps(),
            "hidden_params": p.hidden_param_names(),
        }
        for mode, p in ACESTEP_PROFILES.items()
    }
```

Frontend, types.ts, and `ModelCapabilities` API model all stay as-is until we want to expose richer info.

### Implementation order

1. Add `acestep_capabilities.py` with profiles. Land Change 1's behavior here (sft/xl-sft `use_adg` supported).
2. Make `get_model_capabilities()` derive from profiles. Delete the dict.
3. Tests:
   - Every profile loads cleanly
   - Adapter output matches the previous shape for unchanged variants
   - `use_adg` no longer hidden for sft/xl-sft
   - `guidance_scale` still hidden for turbo/xl-turbo
4. Run full backend suite + lint. No frontend changes.

**Risk**: medium. Pure refactor with adapter shim, but it touches a config consumed by `settings_api.py`. Suite must stay green.

## Change 3 — Expose `use_cot_metas` (optional)

Upstream exposes a `use_cot_metas` flag (default true) that controls whether the LM auto-infers BPM/key/time-signature. Our [GenerationParams](src/songmaker_cli/api_models/songs.py) doesn't have it.

If we add it:
- One field in `GenerationParams` (`use_cot_metas: bool | None = None`)
- One field in `AceStepConfig` (already exists in upstream's request schema — verify before adding)
- One row in the `ParamSupport` profile
- One row in `ParamControls.svelte` toggles

**Decision needed**: do you want this exposed? Skip if no.

## UI tooltips — descriptions where users see them

### Where the descriptions live

A new file: `frontend/src/lib/constants/acestep-params.ts`. Keyed by the same names as `GenerationParams`. Three fields per parameter:

```ts
export interface ParamDescription {
    label: string;     // existing field label, kept here for single-source
    short: string;     // 1-sentence tooltip, ~80 chars
    long: string;      // 2–4 sentences for an expanded help drawer
}

export const ACESTEP_PARAM_DESCRIPTIONS: Record<string, ParamDescription> = { ... };
```

User-facing copy. Separate from the backend Pydantic profile (which is engineering truth, not user UX). Different audiences, different files. Future i18n is a key swap.

### Description content (research-verified)

Drafts are below. Felix should review/edit before they ship — these are first drafts, not final UX copy. Each one cites the source so it can be re-verified later.

The "Source" lines are for a reviewer who needs to check my claims, not for the final shipped tooltip.

#### `inference_steps`
- short: "Diffusion denoising steps. More = slower but more refined."
- long: "The diffusion model refines random noise into audio over this many steps. Turbo is distilled to ~8 steps; SFT and Base need ~50 for full quality. Below the recommended count produces underbaked output; above wastes compute."
- source: Tutorial.md L843

#### `guidance_scale`
- short: "How strongly to follow your style prompt. Ignored on turbo models."
- long: "Classifier-Free Guidance — runs the diffusion model twice per step (with and without your prompt) and amplifies the difference. Higher = closer to prompt but can over-saturate. Turbo bakes guidance into training and forces this to 1.0."
- source: [CFG paper, Ho & Salimans 2022](https://arxiv.org/abs/2207.12598), [generate_music.py:262](_models/acestep/acestep/core/generation/handler/generate_music.py#L262)

#### `shift`
- short: "Biases denoising toward early structure or late detail. 3.0 is balanced."
- long: "Rebalances how denoising steps are distributed. Larger shift (3–5) spends more on early high-noise stages where large-scale structure forms — stronger semantics, clearer framework. Smaller shift (1–2) emphasizes detail but details may include noise."
- source: Tutorial.md L195–203

#### `infer_method`
- short: "ODE = deterministic, reproducible. SDE = adds randomness, sometimes more natural."
- long: "ODE follows a deterministic trajectory — same seed → same output. SDE injects noise at each step, breaking exact reproducibility but sometimes yielding more natural texture on sustained sounds. ODE is the default."
- source: Tutorial.md L848

#### `use_adg`
- short: "Smarter CFG that prevents over-saturation. Only matters when guidance_scale > 1."
- long: "At high CFG values plain guidance over-saturates the output. Adaptive Projected Guidance (called ADG in ACE-Step's UI but actually APG from Sadat et al. 2024) decomposes the CFG update and down-weights the part that causes saturation. Useful when you want guidance_scale=7+ without harshness."
- source: [APG paper, arxiv 2410.02416](https://arxiv.org/abs/2410.02416)

#### `cfg_interval_start` / `cfg_interval_end`
- short: "Apply CFG only during part of the denoising trajectory (0.0=start, 1.0=end)."
- long: "Karras et al. 2024 showed CFG is harmful at the start of denoising and unnecessary at the end — only the middle benefits. Setting start=0.1, end=0.8 restricts CFG to the middle 70%, often improving quality and speed. Defaults (0.0, 1.0) apply CFG for the whole run."
- source: [Karras et al. 2024](https://arxiv.org/abs/2404.07724)

#### `thinking`
- short: "Let the LM plan musical structure before audio generation."
- long: "When enabled, the 5Hz Language Model uses chain-of-thought to infer BPM, key, time signature, and structure from your caption and lyrics, then passes that plan to the diffusion model. Auto-disabled in Cover, Extract, and Repaint-with-codes modes."
- source: Tutorial.md L856

#### `lm_temperature`
- short: "How creative the LM is when planning. Higher = more varied, lower = more predictable."
- long: "Standard sampling temperature. 0.0 is fully deterministic, 2.0 is chaotic. The default 0.85 balances creativity and coherence. 1.0–1.5 = surprising structures (and sometimes nonsense); 0.3–0.6 = conservative on-prompt planning."
- source: Tutorial.md L857

#### `lm_top_k`
- short: "Limit LM sampling to the K most-likely tokens. 0 = disabled (use the full vocab)."
- long: "Caps the LM's sampling pool to the top K candidates. K=50 avoids implausible tokens but cuts off creative ones. Default 0 lets `top_p` and `temperature` do the filtering instead."
- source: Tutorial.md L859

#### `lm_top_p`
- short: "Nucleus sampling — sample only from tokens covering P of the probability mass."
- long: "At each step, the LM ranks possible next tokens by probability and considers only the smallest set whose cumulative probability adds up to P. Default 0.9 is the standard recommendation. Adapts to context: small nucleus when confident, large when uncertain."
- source: Tutorial.md L860

#### `lm_cfg_scale`
- short: "CFG strength for the LM's plan (separate from the DiT `guidance_scale`)."
- long: "Higher values make the LM stick more closely to your caption and lyrics when generating its musical plan. Default 2.0 is balanced; 2.5–3.0 = stricter adherence at the cost of creativity."
- source: Tutorial.md L858

#### `lm_negative_prompt`
- short: "Tell the LM what NOT to include in its musical plan."
- long: "Negative prompt for the LM's CoT step — the LM tries to avoid concepts mentioned here. Useful for steering away from defaults you don't want (e.g. 'drums, electronic' if you want a slow acoustic piece). Has no effect when `thinking=false`."
- source: Tutorial.md L861

#### `lm_repetition_penalty`
- short: "Discourages the LM from repeating itself. 1.0 = off."
- long: "Penalizes already-generated tokens, reducing degenerate loops where the same lyric or musical idea repeats. Default 1.0 is fine for normal use; 1.05–1.15 helps if you see stuck outputs. Above 1.3 starts damaging coherence."
- source: standard transformer sampling parameter; vendored code passes through

#### `use_cot_caption`
- short: "Let the LM rewrite your style caption to be more model-friendly."
- long: "Takes your style caption and expands it into a richer prompt the diffusion model can use more effectively. Often improves output on short or vague captions. Disable for verbatim caption use (e.g. reproducibility tests)."
- source: Tutorial.md L863

#### `use_cot_language`
- short: "Let the LM auto-detect the language of your lyrics."
- long: "Analyzes lyrics to infer vocal language so the diffusion model pronounces correctly. Disable to force a specific `vocal_language` manually or to control which one wins on intentionally mixed-language lyrics."
- source: Tutorial.md L864

#### `batch_size`
- short: "Number of audio variations to generate from one request (1–8)."
- long: "Each candidate uses a different seed, giving you N variations of the same prompt. Larger batches use linearly more VRAM but are more efficient than running N separate generations. Hard maximum is 8."
- source: vendored `service_generate_request.py`

Self-explanatory fields (`bpm`, `key_scale`, `time_signature`, `audio_duration`, `vocal_language`, `seed`) get a short tooltip if any, no long-form.

### Surfacing in the UI — Option C (chosen)

**Now**: native HTML `title` attribute on the field's `<span>` and `<input>` in [ParamControls.svelte](frontend/src/lib/components/ParamControls.svelte). Hover on desktop, long-press on mobile. Free, accessible, ~10 lines of diff.

```svelte
<label class="setting">
    <span title={desc.short}>{f.label}</span>
    <input ... title={desc.short} />
</label>
```

**Later (deferred)**: inline `(?)` button with custom popover for richer mobile UX and long-form descriptions. Add when there's actual demand.

## Out of scope

- Changing any value in `_BUILTIN_DEFAULTS`. Felix's defaults are intentional, see auto-memory.
- Hiding `thinking` for any model variant.
- Adding the small (2B) `base` variant. Not in `_BUILTIN_DEFAULTS`, leave alone unless requested.
