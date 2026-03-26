# Token Cost Budget

**Status**: Planned
**Motivation**: Security audit finding — rate limits are request-based, not token-based. A user can submit 30 chat requests/hour × (10k message + 20k context) = ~900k input tokens/hour.

## Problem

The chat endpoint enforces per-user request counts (`CHAT_RATE_LIMIT_USER = 30/hr`) but not token consumption. A malicious or careless user can maximize cost by sending maximum-length messages with maximum-length context on every request.

Server-side API calls use `max_tokens=1024` for output, but input tokens are bounded only by field `max_length` (10k message + 20k context = 30k chars ≈ 7.5k tokens per request, worst case ~225k input tokens/hour).

The frontend direct-to-Anthropic path (BYOK) is not affected — users pay their own costs there.

## Design

### Option A: Input character budget (recommended)

Track cumulative input characters per user per hour. Simple, no external API calls needed.

```python
CHAT_INPUT_BUDGET_USER = 200_000   # chars per hour (≈50k tokens)
CHAT_INPUT_BUDGET_ADMIN = 2_000_000
```

Store per-request input length in the `jobs` table (add `input_chars` column) or a new `chat_usage` table. Sum within the rate window before allowing new requests.

**Pros**: Simple, no token counting API needed, correlates well enough with cost.
**Cons**: Chars ≠ tokens (varies by language), slightly over-conservative.

### Option B: Token tracking via API response

Use `response.usage.input_tokens` from the Anthropic API response to track actual token consumption. More accurate but requires storing usage after the fact (post-hoc enforcement — current request succeeds, budget checked on next request).

**Pros**: Accurate.
**Cons**: Lag — the expensive request already happened before the budget updates. Requires API response parsing changes.

### Option C: Reduce field limits

Simply lower `max_length` on `ChatRequest.context` (20k → 5k) and `ChatRequest.message` (10k → 3k). Reduces worst-case cost per request without tracking.

**Pros**: Zero complexity, immediate effect.
**Cons**: Limits legitimate use cases (long lyrics + context).

## Recommendation

Option A for tracking, combined with Option C as a quick hardening step (context 20k → 10k is reasonable — 20k chars of context is excessive for a songwriting assistant).

## Files to change

| File | Change |
|------|--------|
| `api_models.py` | Reduce `context` max_length (Option C, immediate) |
| `db/models.py` | Add `input_chars` to Job or new ChatUsage model (Option A) |
| `chat_api.py` | Track input length, check budget before calling Claude |
| `api_helpers.py` | Add `check_chat_budget()` helper |
| `constants.py` | New budget constants |
| `tests/` | Budget enforcement tests |

## Scope

Small for Option C (1 line). Medium for Option A (~80 lines production + tests).

## Dependencies

None. Independent of other plans.
