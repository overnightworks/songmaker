# ACE-Step v0.1.6 Upgrade Plan

## Goal

Upgrade ACE-Step from current (`2d14b9e`, pre-v0.1.5) to v0.1.6, adding XL (4B DiT) model support alongside existing 2B models.

## Context

- GPU: RTX 3090 24GB — sufficient for XL (needs 20GB+)
- Target models: `xl-turbo` (fast iteration), `xl-sft` (quality), `xl-base` (max quality)
- Keep existing 2B turbo/sft as fallback options
- API is backwards compatible — new features are additive
- HuggingFace account recommended for faster weight downloads (free tier avoids throttling)

## Changes

### 1. Pre-download XL weights

Download weights **before** deploying to avoid 10+ minute hang on first generation.

```bash
cd _models/acestep
# Set HF_TOKEN if available for faster downloads
huggingface-cli download ACE-Step/acestep-v15-xl-turbo
huggingface-cli download ACE-Step/acestep-v15-xl-sft
huggingface-cli download ACE-Step/acestep-v15-xl-base
```

These go into the HF cache inside `_models/acestep/` which is bind-mounted into Docker.

### 2. Update ACE-Step submodule

```bash
cd _models/acestep
git fetch origin
git checkout v0.1.6
cd ../..
git add _models/acestep
```

### 3. Add XL model config paths

**File:** `src/songmaker_cli/constants.py`

```python
MODEL_CONFIG_PATHS: dict[str, str] = {
    "turbo": "acestep-v15-turbo",
    "sft": "acestep-v15-sft",
    "xl-turbo": "acestep-v15-xl-turbo",
    "xl-sft": "acestep-v15-xl-sft",
    "xl-base": "acestep-v15-xl-base",
}
```

### 4. Fix `resolve_model_mode()` — CRITICAL

**File:** `src/songmaker_cli/config.py`

Current implementation uses substring matching:
```python
for mode in _BUILTIN_DEFAULTS:
    if mode in model_name:
        return mode
```

This breaks for XL: `"acestep-v15-xl-turbo"` contains `"turbo"` and would match the 2B turbo mode. Need explicit reverse mapping:

```python
_MODEL_NAME_TO_MODE: dict[str, str] = {
    "acestep-v15-turbo": "turbo",
    "acestep-v15-sft": "sft",
    "acestep-v15-xl-turbo": "xl-turbo",
    "acestep-v15-xl-sft": "xl-sft",
    "acestep-v15-xl-base": "xl-base",
}

def resolve_model_mode(model_name: str | None) -> str:
    if model_name:
        if model_name in _MODEL_NAME_TO_MODE:
            return _MODEL_NAME_TO_MODE[model_name]
        # Fallback: substring match for forward compat
        for mode in reversed(sorted(_BUILTIN_DEFAULTS, key=len)):
            if mode in model_name:
                return mode
    return next(iter(_BUILTIN_DEFAULTS))
```

Sort by length descending so `"xl-turbo"` matches before `"turbo"`.

### 5. Add XL builtin defaults and capabilities

**File:** `src/songmaker_cli/config.py`

XL-turbo behaves like 2B turbo (8 steps, no CFG). XL-sft and XL-base behave like 2B sft (50 steps, CFG).

```python
_BUILTIN_DEFAULTS: dict[str, dict[str, object]] = {
    "turbo": {"inference_steps": 8, "guidance_scale": 0.0, **_SHARED_LM_DEFAULTS},
    "sft": {"inference_steps": 50, "guidance_scale": 0.0, **_SHARED_LM_DEFAULTS},
    "xl-turbo": {"inference_steps": 8, "guidance_scale": 0.0, **_SHARED_LM_DEFAULTS},
    "xl-sft": {"inference_steps": 50, "guidance_scale": 0.0, **_SHARED_LM_DEFAULTS},
    "xl-base": {"inference_steps": 50, "guidance_scale": 0.0, **_SHARED_LM_DEFAULTS},
}

_MODEL_CAPABILITIES: dict[str, dict[str, object]] = {
    "turbo": {"max_inference_steps": 20, "hidden_params": ["guidance_scale"]},
    "sft": {"max_inference_steps": 200, "hidden_params": []},
    "xl-turbo": {"max_inference_steps": 20, "hidden_params": ["guidance_scale"]},
    "xl-sft": {"max_inference_steps": 200, "hidden_params": []},
    "xl-base": {"max_inference_steps": 200, "hidden_params": []},
}
```

### 6. Seed XL models in database — Alembic migration

**Problem:** `_seed_available_models()` uses `INSERT OR IGNORE`, so existing databases won't get the new rows. Need an Alembic migration.

```bash
alembic revision --autogenerate -m "add xl model variants"
```

Migration body:
```python
def upgrade():
    op.execute("INSERT INTO available_models (id, is_active) VALUES ('xl-turbo', false)")
    op.execute("INSERT INTO available_models (id, is_active) VALUES ('xl-sft', false)")
    op.execute("INSERT INTO available_models (id, is_active) VALUES ('xl-base', false)")

def downgrade():
    op.execute("DELETE FROM available_models WHERE id IN ('xl-turbo', 'xl-sft', 'xl-base')")
```

Also update `_seed_available_models()` in `db/engine.py` to include XL models for fresh installs.

### 7. Update default model env var

**File:** `docker-compose.yml`

Add `ACESTEP_CONFIG_PATH` env var to explicitly set the default model. Keep `acestep-v15-sft` as default (stable), switch to XL via settings UI once verified.

```yaml
environment:
  ACESTEP_CONFIG_PATH: "acestep-v15-xl-sft"  # or keep sft for safety
```

### 8. Verify VRAM budget

RTX 3090 = 24GB. Rough estimates:
- XL DiT weights: ~9GB
- 4B LM: ~8GB (already loaded for 2B)
- Generation working memory: ~3-5GB
- Total: ~20-22GB — tight but should fit

Verify empirically: run a generation, check `nvidia-smi` peak. If it OOMs, the LM will need to use the 1.7B variant instead of 4B when running XL DiT.

### 9. Test

- [ ] Submodule updates cleanly to v0.1.6
- [ ] Worker starts with XL model (check startup logs for model name)
- [ ] XL models appear in frontend model selector after migration
- [ ] Generation produces audio with XL turbo
- [ ] Generation produces audio with XL sft
- [ ] Model switching between 2B and XL works via API
- [ ] `resolve_model_mode()` correctly maps all 5 model names
- [ ] Repaint + splice works with XL-generated audio
- [ ] Scoring works on XL-generated audio
- [ ] Existing 2B models still work as fallback
- [ ] VRAM stays within 24GB during XL generation

## Risks

- **VRAM pressure**: XL DiT (9GB) + 4B LM (8GB) + working memory is ~21GB on a 24GB card. May need to drop to 1.7B LM for XL, or use `save_memory_mode` (new in v0.1.6, #947)
- **ACE-Step dependency bumps**: `torchao>=0.16.0` and `diffusers>=0.37.0` are ACE-Step internal deps resolved in its subprocess venv. Low conflict risk since our worker doesn't share the venv
- **Submodule jump is large**: going from pre-v0.1.5 to v0.1.6 spans many changes. If something breaks, bisecting will be harder. Mitigation: test thoroughly before committing

## Not in scope

- Multi-slot model loading (new in v0.1.6 but not needed yet)
- External LM captioning feature
- LoRA/training support for XL
- Enhanced sampler modes (free quality improvement, but investigate separately to isolate variables)
