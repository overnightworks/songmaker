# Whisper Transcription Benchmark

Test songs: **Where Is the Love v130** (VQ=5) and **v124** (VQ=8)
ACE-Step SFT model, 220s duration

## Final Results

### v130 (mid quality vocals)

| # | Approach | Accuracy | Notes |
|---|----------|----------|-------|
| 1 | Defaults (greedy, condition=True, no prompt) | ~38% | Hallucination: "We'll see you next time" |
| 2 | Full lyrics as prompt, condition=True | 75.0% | Skips first verse (treats prompt as "already spoken") |
| 3 | Key words prompt, condition=False, beam=5 | 90.8% | Before punctuation fix this was 75.4% |
| 4 | Full lyrics prompt, condition=False, beam=5 | 91.7% | Baseline with all optimizations |
| 5 | + Pre-emphasis + vocal boost +6dB | **92.5%** | Best on v130 |
| 6 | + Highpass 400Hz | 92.2% | Gets "burning" right but not "Ukraine" |
| 7 | Demucs htdemucs + prompt | 73.3% | Demucs distorts AI audio |
| 8 | faster-whisper + VAD | 57.9% | VAD too aggressive |
| 9 | 16kHz WAV (no MP3) | 91.1% | No improvement over MP3 |
| 10 | HPSS (harmonic separation) | 20.8% | Destroys everything |
| 11 | Spectral gating | 90.8% | No improvement |
| 12 | Compression + vocal boost | 91.0% | Marginal |

### v124 (high quality vocals)

| # | Approach | Accuracy | Notes |
|---|----------|----------|-------|
| 1 | Full lyrics prompt, beam=5, condition=False | 94.9% | Gets "Ukraine" correct |
| 2 | + Pre-emphasis + vocal boost +6dB | **96.7%** | Best overall |

## Optimal Pipeline

```
Audio preprocessing:
  1. Pre-emphasis filter (coeff=0.97) — boosts consonant frequencies
  2. Vocal band boost +6dB (200-5000 Hz) — emphasizes speech over music
  3. Peak normalize to 0.95

Whisper settings:
  - model: large-v3
  - initial_prompt: full lyrics from markdown (we always have them)
  - condition_on_previous_text: False (prevents error cascade)
  - beam_size: 5 (explores multiple hypotheses)
  - best_of: 5 (samples multiple candidates)
  - temperature: 0 (deterministic)
  - word_timestamps: True (proper segmentation)
  - compression_ratio_threshold: 1.8 (stricter hallucination filter)
  - logprob_threshold: -0.5 (drops low-confidence segments)

Accuracy measurement:
  - clean_lyrics() strips ALL punctuation (,. ? ! ; : " — etc.)
  - Word-level comparison (max of char-level and word-level SequenceMatcher)
```

## Key Findings

1. **Punctuation normalization** was the biggest accuracy blocker — stripping punctuation jumped 75.4% → 90.8%
2. **`condition_on_previous_text=False`** is critical for songs — prevents error cascade
3. **`beam_size=5`** significantly improves over greedy decoding
4. **Full lyrics as prompt** is better than key-word prompt (92.3% vs 90.8%) and is fully automatic
5. **Pre-emphasis + vocal boost** gives consistent +1-2% improvement with no downsides
6. **Demucs vocal separation hurts** AI-generated audio — introduces artifacts
7. **VAD filter too aggressive** for music — cuts real vocals during quiet passages
8. **16kHz WAV** does not help over MP3
9. **HPSS, spectral gating, compression** — no meaningful improvement
10. Remaining errors are genuinely unclear ACE-Step pronunciation (v124 sings "Ukraine" clearly, v130 doesn't)

## What Doesn't Work for AI-Generated Music

- Demucs/source separation (designed for real instruments, distorts AI audio)
- Silero VAD (too aggressive on sung vocals)
- HPSS harmonic extraction (destroys vocal timbre)
- Spectral gating (removes too much vocal information)
- Lower no_speech_threshold (more hallucination, not less)
