# Token Cost Budget & Model Configuration

**Status**: Planned
**Motivation**: API key as optional upgrade from CLI for Docker deployment. Admin needs model control and cost visibility. Rate limits are request-based, not token-based.

**Current baseline**: CLI backend (Max subscription) is the default. No per-token cost, but limited by subscription. The CLI path remains the fallback when no `ANTHROPIC_API_KEY` is set — all Phase 1 model/caching config only applies to the API backend.

## Cost Comparison (per request, with prompt caching)

### Scoring — lyrical coherence (cached prompt ~800 tok, input ~500 tok, output ~100 tok)

| Model | Per score | Songs for $20 |
|---|---|---|
| Opus 4.6 | $0.017 | ~1,170 |
| Sonnet 4.6 | $0.003 | ~6,600 |
| Haiku 4.5 | $0.0009 | ~22,000 |

### Chat — per message (cached prompt ~350 tok, input ~600 tok, output ~300 tok)

| Model | Per message | Messages for $20 |
|---|---|---|
| Opus 4.6 | $0.032 | ~625 |
| Sonnet 4.6 | $0.006 | ~3,300 |
| Haiku 4.5 | $0.002 | ~10,000 |

### Combined — generate + score + N chat messages

| Scenario | Opus | Sonnet | Haiku |
|---|---|---|---|
| Score only (no chat) | $0.017 | $0.003 | $0.0009 |
| + 3 chat messages | $0.113 | $0.021 | $0.007 |
| + 10 chat messages | $0.337 | $0.063 | $0.021 |
| + 30 chat messages | $0.977 | $0.183 | $0.061 |

**$20 budget at "score + 5 chat msgs per song":**
Opus ~120 songs | Sonnet ~660 songs | Haiku ~2,200 songs

### Pricing reference (per 1M tokens)

| Model | Input | Cached input | Output |
|---|---|---|---|
| Opus 4.6 | $15.00 | $1.875 | $75.00 |
| Sonnet 4.6 | $3.00 | $0.375 | $15.00 |
| Haiku 4.5 | $0.80 | $0.10 | $4.00 |

## Design

### Phase 1: Admin model configuration + prompt caching

Admin can set which model to use for chat and scoring independently. Works with both backends — API uses the SDK `model` param, CLI uses `--model`.

**New settings** (env vars with admin UI override):
- `CLAUDE_CHAT_MODEL` — model for chat co-writing (default: `claude-opus-4-6`)
- `CLAUDE_SCORING_MODEL` — model for lyrical coherence (default: `claude-opus-4-6`)

Opus is the default for maximum quality. Admin can downgrade to Sonnet or Haiku to reduce API costs.

**Prompt caching**: Add `cache_control` to the system prompt in the API backend. The system prompts are identical across requests — caching saves 87.5% on those tokens. Not applicable to CLI backend (Max subscription has no per-token cost).

**Files to change:**

| File | Change |
|---|---|
| `constants.py` | `CLAUDE_CHAT_MODEL`, `CLAUDE_SCORING_MODEL` defaults |
| `claude/provider.py` | Pass `model` to `_call_cli` via `--model` flag; add prompt caching via `cache_control` on system message (API path only) |
| `chat_api.py` | Read model from config, pass to `call_claude` |
| `scoring/lyrical_coherence.py` | Read scoring model from config, pass to `call_claude` |
| `api_models/settings.py` | Add model fields to admin settings response |
| `docker-compose.yml` | Pass `ANTHROPIC_API_KEY` to web + worker (done) |

### Phase 2: Input budget enforcement

Track cumulative input characters per user per hour. Prevents cost runaway from large context submissions.

```python
CHAT_INPUT_BUDGET_USER = 200_000   # chars per hour (~50k tokens)
CHAT_INPUT_BUDGET_ADMIN = 2_000_000
```

Store per-request `input_chars` in the `jobs` table. Sum within the rate window before allowing new requests.

### Phase 3: Reduce field limits (quick hardening)

Lower `max_length` on `ChatRequest.context` from 100k → 10k chars. 100k chars of context is excessive for a songwriting assistant. One-line change.

## Recommendation

**Start with Phase 1.** Model selection + prompt caching gives the most impact:
- Switching from Opus to Sonnet = 5x cost reduction
- Prompt caching = additional 30% reduction
- Combined: ~7x cheaper than current Opus-without-caching baseline
- Admin retains control to use Opus where quality justifies cost

Phase 2 + 3 are hardening — implement when opening to other users.

## Scope

Phase 1: ~60 lines production + tests. Phase 2: ~80 lines. Phase 3: 1 line.

## Dependencies

Optional `ANTHROPIC_API_KEY` in environment (docker-compose.yml change already done). Without it, CLI backend is used and model/budget config is ignored.
