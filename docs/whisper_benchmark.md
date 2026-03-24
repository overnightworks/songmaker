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

## Optimal Pipeline (Updated 2026-03-23)

```
Audio preprocessing: NONE (raw MP3 — see findings below)

Whisper settings:
  - model: large-v3
  - initial_prompt: full lyrics text (not keywords — gives cleaner segmentation)
  - condition_on_previous_text: False (prevents error cascade)
  - beam_size: 5 (explores multiple hypotheses)
  - best_of: 5 (samples multiple candidates)
  - temperature: 0 (deterministic)
  - compression_ratio_threshold: 1.8 (stricter hallucination filter)
  - logprob_threshold: -0.5 (drops low-confidence segments)
  - fp16: True (faster on GPU, same quality)

Accuracy measurement:
  - clean_lyrics() strips ALL punctuation (,. ? ! ; : " — etc.)
  - Coverage-based: what % of intended words were found (order-preserving)
  - Extra sung content (ad-libs, improvised bridges) NOT penalized
```

## Key Findings

1. **Punctuation normalization** was the biggest accuracy blocker — stripping punctuation jumped 75.4% → 90.8%
2. **`condition_on_previous_text=False`** is critical for songs — prevents error cascade
3. **`beam_size=5`** significantly improves over greedy decoding
4. **Full lyrics as prompt** is better than key-word prompt and gives cleaner segmentation (no comma-separated words)
5. **Pre-emphasis + vocal boost HURTS** songs with instrumental intros — causes "I, I, I, I" hallucination loops. Raw MP3 is better.
6. **Demucs vocal separation hurts** AI-generated audio — introduces artifacts
7. **VAD filter too aggressive** for music — cuts real vocals during quiet passages
8. **16kHz WAV** does not help over MP3
9. **HPSS, spectral gating, compression** — no meaningful improvement
10. **word_timestamps=True** causes comma-separated word segments that confuse coherence scoring
11. Remaining errors are genuinely unclear ACE-Step pronunciation

### Results with current pipeline (no preprocessing, full lyrics prompt)

| Song | Version | Rating | Text Accuracy | Coherence | Notes |
|------|---------|--------|---------------|-----------|-------|
| With A Little Help | v3 | 81 | **91%** | **10** | Clean transcription, no hallucination |
| Where Is The Love | v124 | high | **92.8%** | — | Best vocal quality |
| Where Is The Love | v130 | mid | **80.1%** | — | Misses some words |
| Where Is The Love | v148 | 16.7 | **44.4%** | — | Genuinely bad vocals |

## What Doesn't Work for AI-Generated Music

- Pre-emphasis + vocal boost (causes hallucination on instrumental intros)
- Demucs/source separation (designed for real instruments, distorts AI audio)
- Silero VAD (too aggressive on sung vocals)
- HPSS harmonic extraction (destroys vocal timbre)
- Spectral gating (removes too much vocal information)
- word_timestamps (causes comma-separated segments)
- Lower no_speech_threshold (more hallucination, not less)
