# ACE-Step Tuning Notes

## Key Parameters

| Parameter | Default | Notes |
|-----------|---------|-------|
| `shift` | 3.0 | 1.0 = most natural/emotional, 3.0 = accurate lyrics |
| `think_mode` | true | false = more creative, true = more structured |
| `inference_steps` | 8 (turbo) / 50 (SFT) | More = slower but potentially higher quality |
| `guidance_scale` | 0.0 | Turbo ignores CFG |
| `lm_temperature` | 0.85 | Higher (1.1-1.2) = more creative |
| `infer_method` | ode | sde = more textured/alive |
| `bpm` | 120 | 0 = let model decide freely |

## LM Model Selection

| Model | Effect |
|-------|--------|
| none | Raw/chaotic, most creative |
| 0.6B | Sweet spot — creative + structure |
| 4B | Over-planned, sterile — avoid |

## Mastering Chain

```
Input (WAV from ACE-Step, typically 48kHz)
  → Stereo (duplicate if mono)
  → Multiband Compression (3 bands: 20-250, 250-4k, 4k-20k Hz)
  → Stereo Widening (1.2x, mid-side)
  → LUFS Normalization (-14 LUFS, ITU-R BS.1770-4)
  → Soft Clipping (tanh, 0.98 ceiling)
  → MP3 (320 kbps, ffmpeg)
```
