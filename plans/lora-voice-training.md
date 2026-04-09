# LoRA Voice Training

**Status:** Proposed
**Date:** 2026-04-09

> Requires ACE-Step LoRA support verification and training pipeline.

## Goal

Let users train custom voice models (LoRA) from their own vocal recordings and use them in generation.

---

## User Workflow

1. Upload 5-10 min of clean vocal audio (no background music)
2. Server preprocesses: silence removal, normalization, segmentation
3. Training runs on RTX 3090 (20-60 min, 100% GPU utilization)
4. LoRA weights saved to user profile (~50-200 MB per voice)
5. User selects custom voice in generation settings
6. All subsequent generations can use the trained voice

## Data Model

```python
class UserVoice(Base):
    __tablename__ = "user_voices"

    id: str              # uuid
    user_id: str         # FK → User
    name: str            # display name ("My Singing Voice")
    file_path: str       # path to LoRA weights
    status: str          # uploading | preprocessing | training | ready | error
    error: str | None    # error message if training failed
    created_at: datetime
```

Storage: `_models/voices/{user_id}/{voice_id}/`

## API Endpoints

```
POST   /api/voices/upload          multipart → upload raw audio
POST   /api/voices/{id}/train      start training job
GET    /api/voices                  list user's voices
GET    /api/voices/{id}            voice status + details
DELETE /api/voices/{id}            delete voice + weights
```

## Implementation Steps

### Phase 1: Upload + Storage
- [ ] File upload endpoint with size limit (100 MB max)
- [ ] Audio validation (WAV/MP3/FLAC, min 3 min, max 15 min)
- [ ] Store raw uploads in `_output/voices/{user_id}/raw/`
- [ ] Frontend: upload UI in settings or generation panel

### Phase 2: Preprocessing
- [ ] Silence removal (librosa)
- [ ] Loudness normalization (pyloudnorm)
- [ ] Segment into 10-15s chunks for training
- [ ] Background job in GPU queue (type: "preprocess")

### Phase 3: Training
- [ ] New GPU queue job type: "train_voice"
- [ ] Integration with ACE-Step LoRA training (or RVC/Applio)
- [ ] Progress tracking (epoch/loss updates via job status)
- [ ] Save LoRA weights on completion
- [ ] Error handling: VRAM exhaustion, training divergence

### Phase 4: Generation Integration
- [ ] Add `voice_id` to generation params
- [ ] Pass LoRA weights path to ACE-Step config
- [ ] Frontend: voice dropdown in GenerationSettings
- [ ] Preview: short test generation with selected voice

## Constraints

| Constraint | Impact | Mitigation |
|-----------|--------|------------|
| GPU exclusive during training | Blocks generation for 20-60 min | Dedicated training window or night-mode queue |
| VRAM (24 GB on 3090) | Training uses more than inference | One training job at a time, clear all caches |
| Storage (~200 MB/voice) | 10 users × 3 voices = 6 GB | Limit to 3-5 voices per user |
| Training time | 20-60 min per voice | Async with progress updates |
| Legal (deepfakes) | Users could clone others' voices | ToS: own voice only, audit trail via login |

## Dependencies

- Verify ACE-Step LoRA training pipeline works on RTX 3090
- Preprocessing pipeline (librosa + pyloudnorm — already in project)
- GPU queue already supports job types — add "preprocess" and "train_voice"

## Open Questions

- Does ACE-Step 1.5 support LoRA inference natively, or is a custom adapter needed?
- What training framework? ACE-Step's own, RVC, or Applio?
- What's the minimum audio quality/length for usable results?
