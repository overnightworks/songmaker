# Infinite Duration Generation

> **Status: IDEA** — Needs design exploration before implementation.

## Goal

Generate songs longer than the ACE-Step model limit (~4 min) by chaining repaint operations. The user writes lyrics for a 6-minute song, hits generate, and gets a seamless result.

## Prerequisites

- Repaint mode must work (done — acestep-modes Phase 2)

## Open Questions (must answer before implementation)

1. **Lyrics alignment**: How do we split lyrics by time? ACE-Step doesn't return timing info for lyrics. Do we split by section tags ([verse], [chorus])? By character count proportional to duration? Do we need Whisper transcription of the first segment to know where lyrics ended up?

2. **Overlap strategy**: How much overlap between segments? Too little = audible seams. Too much = wasted generation time. ACE-Step repaint uses fractional start/end — what overlap fraction produces seamless transitions?

3. **Crossfade vs hard cut**: Can we just crossfade the overlap region, or does repaint already handle seamless continuation? Need to test with real ACE-Step output.

4. **Seed consistency**: Should all segments use the same seed for tonal consistency, or does repaint with the same seed on different sections produce coherent results regardless?

5. **BPM drift**: Over multiple segments, can BPM drift? Does each repaint segment re-infer BPM or respect the original?

6. **Error propagation**: If segment 3 of 5 fails, what do we show the user? The first 2 segments as partial result? Or fail the whole job?

## Rough Architecture

```
User: "Generate 6-minute song"
  → Job created with count=1, duration=360s
  → Worker detects duration > model limit (240s)
  → Generates first segment (0:00-4:00)
  → Repaint-extends: segment 2 covers 3:30-7:30 (30s overlap with segment 1)
  → Crossfade overlap regions
  → Concatenate → single WAV/MP3
  → Save as one generation
```

## Implementation Sketch

- [ ] Detect long-duration requests in `run_generation_job` (duration > threshold)
- [ ] Split lyrics into segments (heuristic: by section tags or proportional)
- [ ] Generate first segment with full duration up to model limit
- [ ] For each subsequent segment: repaint from overlap point to end
- [ ] Crossfade overlap regions in `audio_engine`
- [ ] Concatenate segments into final output
- [ ] Progress tracking: report segment N/M to frontend
- [ ] Frontend: "Extend" button on generations (manual chaining)

## Why This Is Hard

The core challenge isn't the chaining — it's getting seamless transitions. ACE-Step repaint replaces a section while keeping surrounding audio intact, but "surrounding audio" at the end of a track is silence. We'd need to test whether repaint can actually extend from the last few seconds of a track.

An alternative approach: generate the full song at once but at lower quality (fewer steps), then repaint individual sections at full quality. This avoids the seaming problem entirely but requires ACE-Step to handle long durations at the cost of more VRAM.
