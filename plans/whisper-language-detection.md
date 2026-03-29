# Whisper Language Detection

> **Status: NOT STARTED**

## Problem

`text_accuracy.py` defaults to `language="en"` when `generation_params` has no `language` field. German (or other non-English) songs get transcribed as English, producing garbage → 0% text accuracy → hallucination detection clears transcription → `lyrical_coherence` fails with "No Whisper transcription".

## Root Cause

`score_text_accuracy()` line 50:
```python
language = meta.generation_params.get("language", "en")
```

ACE-Step doesn't set a `language` param — the field doesn't exist in generation params.

## Fix

1. **Auto-detect language with Whisper** — Whisper supports `language=None` which triggers auto-detection. Change the default from `"en"` to `None`:
   ```python
   language = meta.generation_params.get("language") or None
   ```
   This lets Whisper detect the language from the audio itself.

2. **Store detected language** — After transcription, store the detected language in the score result so it's visible in the UI (informational).

3. **Handle empty transcription gracefully** — When Whisper returns empty text (no vocals detected), `lyrical_coherence` should return a neutral score or skip, not crash with `ValueError`.

## Files to Touch

| File | Change |
|------|--------|
| `scoring/text_accuracy.py:50` | Change language default to `None` for auto-detect |
| `scoring/text_accuracy.py` | Store detected language in score result |
| `scoring/lyrical_coherence.py:75-76` | Handle empty `whisper_text` gracefully — skip instead of crash |
| `scoring/models.py` | Add `detected_language` field to `TextAccuracyScore` if needed |

## Testing

- Score a German song → should auto-detect German, transcribe correctly, get reasonable text accuracy
- Score an English song → should still work as before
- Score an instrumental (no vocals) → should not crash, should skip text-dependent scorers

## Constraints

- Don't break existing English scoring
- `faster-whisper` API: pass `language=None` to enable auto-detect
- Run existing scorer tests after changes
