# ACE-Step Integration

Upstream: [ACE-Step 1.5](https://github.com/ace-step/ACE-Step-1.5)

## How Songmaker Uses ACE-Step

ACE-Step runs as a separate HTTP server (`localhost:8001`). The `acestep_manager.py` manages its lifecycle — starting it before the first generation job. It stays running; scoring models (faster-whisper, AudioBox) coexist on the GPU.

```
arq worker (songmaker_cli.worker.WorkerSettings)
  → on_startup: AceStepManager.start()
  → on generate job:
    → prepare_generate_mode() (clear scoring models, ensure ACE-Step)
    → POST to ACE-Step API → get WAV bytes
    → master → MP3
  → on score job:
    → load faster-whisper + AudioBox on demand (~4 GB VRAM)
    → ACE-Step stays running
```

Client: `src/acestep_engine/client.py` (HTTP client with retry, polling, model info)
Config: `src/songmaker_cli/config.py` (`build_ace_config()` merges defaults + user settings + song params)

## Model Variants

| Model | Steps | Speed | Quality | Use case |
|-------|-------|-------|---------|----------|
| `acestep-v15-turbo` | 8 | ~10s on 3090 | Very good | Default, fast iteration |
| `acestep-v15-sft` | 50 | ~60s on 3090 | Best | Final renders, critical tracks |

LM models (text planner):
- `acestep-5Hz-lm-0.6B` — creative, good structure (recommended)
- `acestep-5Hz-lm-4B` — over-planned, can sound sterile

## Generation Parameters

Parameters can be set per-song (`generation_params` in version), per-model-type (admin defaults), or globally.

Priority: song params > admin defaults > model defaults.

| Parameter | Range | Default (turbo) | Default (SFT) | Effect |
|-----------|-------|-----------------|---------------|--------|
| `inference_steps` | 1-200 | 8 | 50 | More = slower, potentially higher quality |
| `guidance_scale` | 0-50 | 0.0 | 0.0 | CFG strength (turbo ignores this) |
| `shift` | 0-100 | 3.0 | 3.0 | 1.0 = natural/emotional, 3.0 = accurate lyrics |
| `lm_temperature` | 0-5 | 0.85 | 0.85 | Higher = more creative (try 1.1-1.2) |
| `lm_top_k` | 0-1000 | — | — | LM sampling top-k |
| `lm_top_p` | 0-1 | — | — | LM sampling nucleus |
| `lm_cfg_scale` | 0-50 | — | — | LM classifier-free guidance |
| `lm_negative_prompt` | string | — | — | What to avoid |
| `infer_method` | ode/sde | ode | ode | sde = more textured/alive |
| `think_mode` | string | true | true | false = more creative, true = more structured |
| `batch_size` | 1-8 | 1 | 1 | Parallel generations per request |
| `duration` | 1-600 | 180 | 180 | Output length in seconds |
| `bpm` | 0-999 | 120 | 120 | 0 = let model decide |

## Modes

All modes use the same `/release_task` endpoint with different `task_type` + audio inputs. The worker auto-switches models if the requested model differs from the loaded one.

| Mode | task_type | Trigger | What It Does |
|------|-----------|---------|--------------|
| Text2Music | `text2music` | Generate button | Generate from scratch (default) |
| Repaint | `repaint` | Repaint button on generation | Edit a time section — fix wrong lyrics, redo a chorus |
| Cover | `cover` | Cover button on generation | Re-interpret with different style/lyrics, keep melody |
| Reference | `text2music` + `reference_audio` | Upload in generation settings | Guide timbre/style from an external audio track |

**Repaint** sends `src_audio` (the original WAV), `repainting_start` and `repainting_end` (0.0-1.0 fractions). `think_mode` is auto-disabled. The result is a new generation — non-destructive.

**Cover** sends `src_audio` and `audio_cover_strength` (0.0 = free reinterpretation, 1.0 = strict structure). `think_mode` is auto-disabled.

**Reference audio** uploads via `POST /api/audio/upload` (max 50MB, .mp3/.wav/.flac/.ogg). The path is stored in version `generation_params.reference_audio` and resolved to an absolute path before sending to ACE-Step. Path traversal is blocked at both API validation and job execution levels.

**Not yet integrated**: Lego, Extract, Complete (require Base model — see `plans/base-model-tasks.md`). Infinite duration (exploratory — see `plans/acestep-modes.md` Phase 5).

## Environment Variables

| Var | Default | Purpose |
|-----|---------|---------|
| `ACESTEP_API_PORT` | 8001 | ACE-Step server port |
| `ACESTEP_CONFIG_PATH` | acestep-v15-sft | DiT model to load |
| `ACESTEP_INIT_LLM` | 1 | Load LM on startup |
| `ACESTEP_LM_MODEL_PATH` | acestep-5Hz-lm-4B | LM model |
| `ACESTEP_LM_BACKEND` | vllm | LM inference backend |
| `MAX_CUDA_VRAM` | 18 | VRAM budget in GB |
| `ACESTEP_COMPILE_MODEL` | 0 | torch.compile (slower startup, faster inference) |
