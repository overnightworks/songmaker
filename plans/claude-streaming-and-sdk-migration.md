# Claude Streaming + Drop the CLI Backend (Migrate to SDK Only)

**Status:** Proposed
**Date:** 2026-04-09

> Multi-day initiative. Two changes are coupled because both rewrite the same surface (`claude/provider.py` + `chat_api.py` + `ClaudeChat.svelte`) and shipping them together avoids touching it twice.
>
> **Triggers to start:**
> - Co-writer becomes a daily-driver feature (you actually use it for real lyric work, not just experiments).
> - Frontend reports a chat timeout in the wild (the 120s wall is hit by a real response).
> - You go from Max-subscription / CLI to a paid `ANTHROPIC_API_KEY` deployment.
> - Public-facing launch (CLI backend's tool denylist is fail-open and unsuitable for untrusted users).

## Problem

Two pain points, one surface:

### 1. No streaming (D4)

[`provider.py:_acall_api`](../src/songmaker_cli/claude/provider.py) calls `client.messages.create()` and waits for the full response. Frontend `ClaudeChat.svelte` waits with `CHAT_TIMEOUT_MS = 120_000`. A long Claude response races a hard wall and the user sees nothing happening for up to two minutes.

There's also no exponential backoff on 429/503 from Anthropic, no circuit breaker. A user clicking "Retry" hammers the API.

### 2. CLI backend exists for the Max subscription workaround (D7)

[`provider.py:33-40`](../src/songmaker_cli/claude/provider.py#L33-L40) maintains `_DISALLOWED_TOOLS` — a hand-maintained denylist for tools the CLI binary might offer. **It fails open**: any new tool that ships in a future Claude Code version is allowed by default. The list already includes things like `Skill` that didn't exist a few months ago, so the maintenance cadence is real.

The CLI also exists at runtime via three bind mounts in `docker-compose.yml` (per CLAUDE.md "Known Technical Debt"): `~/.local/bin/claude`, `~/.claude`, `~/.claude.json`. Each is a privilege surface and a deployment fragility.

Both problems disappear when we use `ANTHROPIC_API_KEY` + the SDK exclusively. Streaming is `client.messages.stream()`. The denylist is gone because the SDK has no tools surface. The bind mounts get deleted.

## Goal

1. **Streaming Claude responses end-to-end** — token-by-token from Anthropic SDK → backend SSE → frontend incremental render.
2. **Delete the CLI backend.** `provider.py` has one path. `_DISALLOWED_TOOLS` is gone. Bind mounts are gone from `docker-compose.yml`.
3. **Retry/backoff** on transient Anthropic errors.
4. **Partial-message persistence** — if the user disconnects mid-stream, the partial assistant message is saved so they can see what they got.

## Out of scope

- Tool use via the SDK (Claude proposing structured tool calls). Co-writer's `songmaker` block format stays as text-in-response, parsed client-side.
- Replacing the lyrical_coherence scorer's Claude usage (it's a one-shot non-streaming call; the same SDK migration applies but the changes are trivial — bundle as a small extra commit).
- Changing the system prompt or chat memory model. Pure infrastructure rewrite.
- Frontend god-component split for `ClaudeChat.svelte` (covered by `frontend-component-split.md` Phase 2 — but this plan should land *first* so the split has a stable backend to test against).

## Phase 1: Streaming the SDK call (~1 day)

**Backend changes:**

### `provider.py`

Replace `_acall_api` (full-response) with an async generator:

```python
async def astream_claude(
    prompt: str,
    api_key: str,
    system: str | None,
    model: str,
    max_tokens: int,
    messages: list[dict[str, str]] | None,
) -> AsyncIterator[str]:
    client = _get_async_client(api_key)
    kwargs = _build_api_kwargs(prompt, system, model, max_tokens, messages)
    async with client.messages.stream(**kwargs) as stream:
        async for text in stream.text_stream:
            yield text
```

Keep `acall_claude` as a thin wrapper that exhausts the stream into a `ClaudeResponse` for non-chat callers (the scorer). One code path, two consumers.

### `chat_api.py`

Replace the existing `POST /songs/{song_id}/chat` JSON endpoint with an SSE endpoint:

```python
@router.post("/songs/{song_id}/chat/stream")
async def api_chat_stream(...) -> StreamingResponse:
    ...
    async def event_source():
        full_text = []
        try:
            async for chunk in astream_claude(...):
                full_text.append(chunk)
                yield f"data: {json.dumps({'type': 'token', 'text': chunk})}\n\n"
            assistant_msg = create_chat_message(
                session, song_id, "assistant", "".join(full_text),
            )
            session.commit()
            yield f"data: {json.dumps({'type': 'done', 'message_id': assistant_msg.id})}\n\n"
        except Exception as exc:
            partial = "".join(full_text)
            if partial:
                msg = create_chat_message(
                    session, song_id, "assistant", partial, is_partial=True,
                )
                session.commit()
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(event_source(), media_type="text/event-stream")
```

**Critical decisions baked in above (don't change without thinking):**

- **Persist partial on error.** Add `is_partial: bool` column to `chat_messages` (Alembic migration). The frontend renders partial messages with a visual marker.
- **Persist on `done`, not on every chunk.** One commit per message, not per token. Otherwise transaction churn under load.
- **SSE, not WebSocket.** One-way server→client is enough; WebSocket adds connection state and authentication overhead. SSE rides on top of the existing cookie auth.
- **New endpoint, don't repurpose the existing one.** Keep `POST /songs/{id}/chat` as the non-streaming fallback for one release while the frontend migrates. Delete after.

### Frontend (`ClaudeChat.svelte`)

Use `EventSource` for the streaming endpoint. The existing job-progress SSE plumbing in `lib/stores/jobs.ts` is the blueprint — copy the pattern.

Render incremental text into a "currently streaming" message bubble. On `done`, replace with the persisted message. On `error` with a partial, render the partial with a "(interrupted)" marker.

Remove `CHAT_TIMEOUT_MS` — streaming gives backpressure naturally. The browser will surface a real network error if the connection actually drops.

## Phase 2: Retry + backoff (~half day)

In `provider.py`, wrap the SDK call with retry logic for the documented retryable Anthropic error types: `RateLimitError`, `APIStatusError` (5xx), `APIConnectionError`. Use exponential backoff (e.g., 1s, 2s, 4s, then give up).

**Anthropic SDK already has built-in retries** (`max_retries` constructor arg, default 2). Verify the defaults before adding application-level retry — you don't want to compound retries (SDK retries × app retries = 4 attempts per backoff step). The right answer is probably:

- Set `max_retries=3` on the SDK client.
- Don't add an extra application-level retry loop.
- Add a circuit breaker (in-memory, per-process) that opens for 30s after 3 consecutive failures and short-circuits new requests with a 503. This stops users from hammering during a real Anthropic outage.

The circuit breaker is the only new code. The rest is configuration.

## Phase 3: Delete the CLI backend (~half day)

Once Phase 1 is shipped and validated:

### Code deletions

- `provider.py`: remove `_call_cli`, `_acall_cli`, `_find_claude_binary`, `_DISALLOWED_TOOLS`, `_ENV_SECRETS` scrubbing for the CLI subprocess (still needed for ACE-Step subprocess — verify before deleting blindly).
- `provider.py`: simplify `call_claude` / `acall_claude` to require an API key and raise `UnavailableError` otherwise.
- `provider.py`: remove the `_sync_clients` cache complexity if it only existed for CLI fallback.
- `is_available()`: returns `bool(api_key)`.

### Tests

- `tests/test_claude_provider.py`: delete CLI-backend tests, keep API-backend tests, add streaming tests against a mocked async iterator.

### Deployment

- `docker-compose.yml`: remove the three Claude CLI bind mounts (`~/.local/bin/claude`, `~/.claude`, `~/.claude.json`).
- `.env.docker.example`: document `ANTHROPIC_API_KEY` as required for chat (it may already be).
- CLAUDE.md "Known Technical Debt": delete the "Claude CLI bind mounts" entry and the "`_DISALLOWED_TOOLS`" entry. They are no longer accurate.

### Migration cutover

This is the only sensitive operation:

1. Deploy with both backends present (Phase 1+2 shipped, CLI still works).
2. Set `ANTHROPIC_API_KEY` in `.server.env`. Verify chat works. Verify scorer works.
3. Once validated, deploy the deletion PR (Phase 3).
4. Remove the bind mounts and delete the host CLI install if you want to.

**Do not delete the CLI backend in the same PR that adds streaming.** Two failure modes that would otherwise be tangled.

## Database changes (Alembic)

One migration:

```python
op.add_column(
    "chat_messages",
    sa.Column("is_partial", sa.Boolean, nullable=False, server_default="false"),
)
```

Backfill is automatic (`server_default`). No data migration. Drop the `server_default` in a follow-up migration once all rows have explicit values, per existing project conventions.

## Verification

After Phase 1:

```bash
ruff check src/ tests/
pytest tests/test_chat_api.py tests/test_claude_provider.py -q
cd frontend && pnpm check && pnpm test
```

Manual: send a long-prompt chat message, verify tokens stream into the UI, verify the message persists after `done`. Kill the connection mid-stream (devtools), verify the partial message is saved.

After Phase 2:

Manual: temporarily set `ANTHROPIC_API_KEY` to garbage, verify the circuit breaker opens after 3 attempts and the next request short-circuits with 503 within 30s.

After Phase 3:

```bash
pytest tests/ -n auto -q --cov=songmaker_cli --cov-report=term-missing
# Run docker compose up in the background — never wrap in `timeout`.
# Cold-cache rebuilds are 8-15 min; any timeout < ~20 min will SIGTERM
# mid-build and leave a partial deploy. See CLAUDE.md "Docker" section.
docker compose up -d --build --wait
```

Smoke-test chat in the browser against the new container.

## Risks

- **SSE through middleware.** Verify `BodySizeLimitMiddleware`, `IpRateLimitMiddleware`, and any reverse proxy in front (nginx/traefik) don't buffer SSE streams. Common gotcha: nginx default `proxy_buffering on` breaks SSE. Document the required reverse-proxy config.
- **Long-held DB session.** The existing `chat_api.py` request handler holds a `Session` for the duration of the request. With streaming, that's now Anthropic-response-time long. Two options: (a) hold it (simple, blocks one connection slot per active chat — fine for invite-only), (b) close the session, hold only the IDs, reopen on `done` to commit. Pick (a) and document it.
- **Partial messages and chat history.** When the user re-opens the chat, the partial message must render correctly (with the marker) and not be sent back as part of the conversation history on the next turn — Anthropic will be confused by an incomplete assistant turn. Filter out `is_partial=True` messages when building the messages array for the next call.
- **`ClaudeChat.svelte` is 687 lines and has zero tests.** Adding streaming logic to it without component tests is dangerous. Strongly consider doing `frontend-component-split.md` Phase 2 (split ClaudeChat) *before or alongside* this plan. They share the same code surface.
- **Circuit breaker scope.** In-process means a multi-worker deployment has N independent breakers. That's fine for the user-protection use case (each worker stops hammering independently), but if you ever want a global breaker, it goes in Redis.
- **SDK version pinning.** The Anthropic SDK API has been stable but is not at 1.0 yet. Pin the version in `pyproject.toml` and bump deliberately.
- **Scorer regression.** The lyrical_coherence scorer also calls Claude. After Phase 3, it must use the SDK path. Verify its tests still pass; the call shape is the same (`acall_claude` returning a `ClaudeResponse`).

## Success criteria

- Chat tokens visibly stream into the UI in real time
- A 3-minute Claude response works without hitting any timeout
- Killing the connection mid-stream saves a partial message that's visible on reconnect
- `provider.py` has no `subprocess` import
- `_DISALLOWED_TOOLS` does not exist anywhere in the codebase
- `docker-compose.yml` has zero references to `~/.claude` or `~/.local/bin/claude`
- CLAUDE.md "Known Technical Debt" is shorter by two entries
- Anthropic outage simulation (garbage API key) opens the breaker within 3 requests and short-circuits the next request within milliseconds

## Why bundle these (D4 + D7) instead of doing them separately

Both rewrite `provider.py`, both rewrite `chat_api.py`, both touch `ClaudeChat.svelte`. Doing them in two PRs means the second PR re-opens the same files, re-tests the same paths, and has to hold a half-finished mental model of what the first PR left behind. One coordinated change is shorter overall and the test surface only has to be exercised once. Bundle them.
