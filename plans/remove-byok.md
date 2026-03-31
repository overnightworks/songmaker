# Remove BYOK (Bring Your Own Key) Feature

**Status**: Done
**Motivation**: BYOK adds complexity, a known security liability (localStorage key), and contradicts the token-cost-budget plan which requires all Claude requests to flow through the server for model selection, prompt caching, and budget enforcement. No real user will paste an Anthropic API key into a music generation tool.

## What Gets Removed

The entire "user provides their own Anthropic API key" path:

- Browser-direct calls to `api.anthropic.com`
- localStorage API key storage
- Settings UI for entering/clearing the key
- "Configure API key" hint in the chat component
- CSP allowance for `api.anthropic.com`
- `chat_system_prompt` field in capabilities API (only existed for BYOK)
- BYOK references in docs, comments, docker example

## What Stays

- Server-side chat via `POST /api/chat` (unchanged)
- `ANTHROPIC_API_KEY` env var on the server (unchanged, required for API provider)
- `call_claude()` in `provider.py` still accepts `api_key` param (server reads it from env, not from users)
- `chat_model` in capabilities response (useful for frontend display)

---

## Changes

### 1. Frontend: Delete settings store

**Delete file:** `frontend/src/lib/stores/settings.ts`
**Delete file:** `frontend/src/lib/stores/settings.test.ts`

The entire store exists only for the BYOK key. No other functionality lives here.

### 2. Frontend: Delete integrations settings page

**Delete file:** `frontend/src/routes/settings/integrations/+page.svelte`

The page only contains the API key input. With it gone, remove the nav entry:

**File:** `frontend/src/routes/settings/+layout.svelte`
- Remove `{ href: '/settings/integrations', label: 'Integrations', adminOnly: false }` from `NAV_ITEMS`

### 3. Frontend: Simplify `client.ts`

**File:** `frontend/src/lib/api/client.ts`

Remove:
- `import { getClaudeKey } from '$lib/stores/settings'`
- `FALLBACK_CHAT_MODEL` constant
- `chatDirect()` function (entire function, ~25 lines)
- `_chatSystemPrompt` variable, `getChatSystemPrompt()` getter
- `_chatModel` variable, `getChatModel()` getter
- BYOK branching in `chatWithClaude()` — it always calls `/api/chat` now

`chatWithClaude()` becomes:

```typescript
export async function chatWithClaude(message: string, context: string = ''): Promise<string> {
    const data = await apiFetch<ChatResult>('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, context })
    });
    return data.response;
}
```

`fetchCapabilities()` no longer caches model/prompt (no consumers remain):

```typescript
export async function fetchCapabilities(): Promise<Capabilities> {
    return apiFetch<Capabilities>('/api/capabilities');
}
```

### 4. Frontend: Update `client.test.ts`

**File:** `frontend/src/lib/api/client.test.ts`

- Remove mock of `$lib/stores/settings`
- Remove "calls Anthropic API directly when user has key" test
- Remove `chat_system_prompt` from mock capabilities responses
- Keep "uses server endpoint when no user key" test (rename to just "calls server endpoint")
- Keep error handling tests

### 5. Frontend: Remove key hint from `ClaudeChat.svelte`

**File:** `frontend/src/lib/components/ClaudeChat.svelte`

- Remove `import { claudeApiKey } from '$lib/stores/settings'`
- Remove `const hasKey = $derived(!!$claudeApiKey)`
- Remove the `{#if !hasKey}` key-hint block (lines 300-304)
- Remove `.key-hint` and `.key-hint a` CSS rules

### 6. Frontend: Update types

**File:** `frontend/src/lib/api/types.ts`

- Remove `chat_system_prompt: string` from `Capabilities` interface

### 7. Backend: Remove `chat_system_prompt` from capabilities

**File:** `src/songmaker_cli/api_models/settings.py`

- Remove `chat_system_prompt: str` from `CapabilitiesResponse`

**File:** `src/songmaker_cli/chat_api.py`

- Remove `chat_system_prompt=SYSTEM_PROMPT` from the capabilities response construction

The system prompt no longer needs to be sent to the frontend. The server uses it internally.

### 8. Backend: Tighten CSP

**File:** `src/songmaker_cli/middleware/security_headers.py`

Change:
```python
"connect-src 'self' https://api.anthropic.com; "
```
To:
```python
"connect-src 'self'; "
```

### 9. Backend: Clean up provider docstring

**File:** `src/songmaker_cli/claude/provider.py`

- Update module docstring: remove "BYOK or env var" language
- Update `call_claude` docstring: `api_key` is "server env var", not "BYOK"
- The function signature stays the same — the server still passes `os.environ.get("ANTHROPIC_API_KEY")`

### 10. Update docs

**File:** `docs/security.md`

- Remove "Frontend API key in localStorage" bullet from Known Limitations
- Remove/update "Chat system prompt exposed via `/api/capabilities`" bullet — the prompt is no longer exposed, so the limitation no longer exists
- Update CSP line to remove `https://api.anthropic.com`

**File:** `.env.docker.example`

- Change comment from "optional, users can BYOK" to just the purpose of the key

**File:** `CLAUDE.md`

- Remove "Frontend stores Claude API key in localStorage" from Known Technical Debt

**File:** `plans/prompt-security-review.md`

- Remove BYOK-related findings

### 11. Regenerate types

```bash
python scripts/generate_types.py
```

Verify `chat_system_prompt` is gone from generated `types.ts`.

---

## Checks

```bash
# Backend
ruff check src/ tests/
pytest tests/ -n auto -q

# Frontend
cd frontend && pnpm check && pnpm lint && pnpm test
```

## Files Summary

| File | Action |
|---|---|
| `frontend/src/lib/stores/settings.ts` | Delete |
| `frontend/src/lib/stores/settings.test.ts` | Delete |
| `frontend/src/routes/settings/integrations/+page.svelte` | Delete |
| `frontend/src/routes/settings/+layout.svelte` | Remove integrations nav entry |
| `frontend/src/lib/api/client.ts` | Remove BYOK path, simplify chatWithClaude |
| `frontend/src/lib/api/client.test.ts` | Remove BYOK tests |
| `frontend/src/lib/api/types.ts` | Remove `chat_system_prompt` |
| `frontend/src/lib/components/ClaudeChat.svelte` | Remove key hint + import |
| `src/songmaker_cli/api_models/settings.py` | Remove `chat_system_prompt` field |
| `src/songmaker_cli/chat_api.py` | Remove `chat_system_prompt` from response |
| `src/songmaker_cli/middleware/security_headers.py` | Tighten CSP |
| `src/songmaker_cli/claude/provider.py` | Update docstrings only |
| `docs/security.md` | Remove 2 BYOK-related bullets, update CSP |
| `.env.docker.example` | Update comment |
| `CLAUDE.md` | Remove localStorage tech debt bullet |
| `plans/prompt-security-review.md` | Remove BYOK findings |
