# Chat System Prompt Refactor

**Status**: Planned
**Motivation**: W5 from security audit — user-controlled `system` field in `/api/chat` allows arbitrary system prompt override. Low risk (no tool use, authenticated only), but poor separation of concerns.

## Problem

The system prompt currently lives in the frontend (`ClaudeChat.svelte`) and is passed to the backend via `ChatRequest.system`. This means:

1. Any authenticated user can override the system prompt via curl/API
2. The structural contract (songmaker JSON block format) can be accidentally broken by a user override
3. The prompt mixes two concerns: structural format instructions + creative direction

## Design

Split the system prompt into two parts:

### Backend-owned (not user-modifiable)
The structural contract — songmaker block format, section tags, field names. This ensures the frontend parser always gets valid output regardless of user input.

```
When suggesting lyrics or song parameters, ALWAYS include a ```songmaker block
at the end of your response with the applicable fields as JSON:
```songmaker
{"lyrics": "[verse]\n...", "prompt": "style...", "bpm": 120, "key": "Am"}
```

Only include fields you are suggesting changes for. The lyrics field should use
section tags like [verse], [chorus], [bridge]. Use \n for newlines in lyrics.
If the user just asks a question without needing changes, skip the songmaker block.
```

### User-controlled (optional creative direction)
A `style` field (max 500 chars) prepended to the system prompt. Defaults to the current creative preamble ("You are a songwriting assistant...") but the user can customize it per-chat or in settings.

Examples: "Write like a punk poet", "Focus on jazz harmonies", "You are a metal lyricist"

## API Change

```python
# Before
class ChatRequest(BaseModel):
    message: str = Field(max_length=10_000)
    system: str = Field("", max_length=5_000)    # raw system prompt override
    context: str = Field("", max_length=20_000)

# After
class ChatRequest(BaseModel):
    message: str = Field(max_length=10_000)
    style: str = Field("", max_length=500)        # creative direction only
    context: str = Field("", max_length=20_000)
```

Server builds the full system prompt:
```python
STRUCTURAL_PROMPT = "When suggesting lyrics..."  # hardcoded
DEFAULT_STYLE = "You are a songwriting assistant. Help write, improve, and refine song lyrics. Be creative but respect the style and theme."

style = req.style or DEFAULT_STYLE
system = f"{style}\n\n{STRUCTURAL_PROMPT}"
```

## Frontend Change

- Remove `SYSTEM_PROMPT` constant from `ClaudeChat.svelte`
- Add optional "style" input (textarea or preset dropdown) to chat UI
- Pass `style` instead of `system` in API calls
- Direct browser API calls also use the same split (style + structural prompt)

## Migration

- `system` field removed from API — breaking change for any direct API users
- Frontend update required simultaneously
- No DB migration needed
