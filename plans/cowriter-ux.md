# Co-Writer UX Improvements

> **Status: PLANNING**

## Problems

1. **Desktop layout wastes space.** Detail panel is `max-width: 800px` centered — on wide screens, large margins sit empty on both sides. The chat especially suffers.

2. **Chat is single-turn.** Each message is sent to Claude independently — no conversation history. Claude can't remember what you discussed 2 messages ago. This makes "discuss before applying" impossible because Claude loses all context between messages.

3. **Chat pushes `songmaker` blocks too eagerly.** System prompt front-loads the block format, making Claude treat every response as a "suggest changes" opportunity. Users want to brainstorm first.

4. **Chat stored in localStorage.** Per-browser, lost on clear, can't be queried across songs. Violates "database is source of truth." Chat history is a creative artifact tied to a song — belongs in PostgreSQL.

5. **Auto-scroll broken on tab switch.** Container is `display: none` when hidden → `scrollHeight` is 0 → scroll-to-bottom does nothing. When tab becomes visible, the effect doesn't re-fire.

## Architecture Decision: DB-backed multi-turn chat

**Why DB over localStorage:**
- Multi-turn requires sending history to Claude API anyway — need a reliable source
- Persists across devices/browsers
- Enables the recent chats feature via SQL query instead of scanning localStorage keys
- Consistent with CLAUDE.md ("database is source of truth")
- Chat history is tied to a song, just like versions and generations

**DB model:**
- `ChatMessage` table: `id`, `song_id` (FK → Song, cascade delete), `role` (user/assistant), `content` (text), `created_at`
- One conversation per song (no separate "session" concept — song IS the session)
- Ownership enforced via `check_song_access()` — same as all song endpoints
- Song deletion cascades to chat messages via FK. `hard_delete_user` cascades through Song → ChatMessage automatically.

**API changes:**
- `POST /api/songs/{song_id}/chat` — send message, returns both stored messages
  - Request: `{ message: string, mentioned_song_ids: list[str], mentioned_version_ids: list[str] }`
  - Ownership check via `check_song_access()`
  - Rate limiting via `create_job_with_rate_limit(session, user, "chat")` — same as current endpoint
  - Loads full conversation history from DB (all messages, up to 50 limit)
  - Builds context server-side from current song state + mentioned songs/versions
  - Builds Claude `messages` array from history + new user message
  - Calls Claude API with multi-turn messages array
  - Stores both user message and assistant response in DB
  - Returns: `{ user_message: {id, role, content, created_at}, assistant_message: {id, role, content, created_at} }`
- `GET /api/songs/{song_id}/chat` — load chat history
  - Returns: `{ messages: [{ id, role, content, created_at }] }`
- `DELETE /api/songs/{song_id}/chat` — clear chat history
- Old `POST /api/chat` endpoint removed

**Context strategy — mentions are UI state, not stored:**
- @-mentions live in frontend component state only. Not stored in DB, not per-message.
- The mentions bar shows what's active. User adds/removes freely mid-conversation.
- Each `POST /songs/{song_id}/chat` sends the *current* `mentioned_song_ids` and `mentioned_version_ids` alongside the message. Backend resolves them from DB at that moment — always fresh data.
- When user navigates away and comes back: mentions reset to empty (just current song). The *effects* of previous mentions are baked into the conversation history — Claude's responses that referenced those songs are already stored. Re-add @-mentions only if you want Claude to see *updated* data from those songs.
- Context is injected as a system prompt addendum, not as a user message. This keeps the `messages` array clean for multi-turn.
- No client-side context building. Frontend sends IDs, backend resolves everything.

**Message limit:**
- Max 50 messages per song (25 turns). Enforced server-side.
- When limit reached: reject with 409 and clear error message ("Chat history full — clear to continue").
- No silent trimming — user sees what Claude sees.

**Migration from localStorage:**
- Drop old chats (Option B). Show toast: "Chat history has moved to the server. Previous local chats have been cleared."
- Migration code for disposable conversation data isn't worth the complexity.

## Changes

### Phase 1: Desktop layout + auto-scroll fix (CSS + small JS)

Quick wins that don't depend on the DB migration.

**`frontend/src/routes/+page.svelte`**
- Change `.detail-panel` max-width from `800px` to `1000px`
- When chat tab active: override to `max-width: 100%`, remove horizontal auto-margin
- Add `min-height: 400px` to `.chat-tab`
- Pass `visible={tab === 'chat'}` to ClaudeChat

**`frontend/src/lib/components/ClaudeChat.svelte`**
- Accept `visible` prop
- `$effect` on `visible` becoming true → call `scrollToBottom()` after `tick()`

**Tests:**
- Verify scrollToBottom called when visible transitions false → true

### Phase 2: System prompt rework

Independent of DB migration — improves behavior immediately.

**`src/songmaker_cli/chat_api.py`**
- Restructure `SYSTEM_PROMPT`:
  1. Lead with conversational role: creative partner, honest feedback, direct opinions
  2. Explicit default: "Discuss freely. Only include a songmaker block when the user explicitly asks you to write, rewrite, draft, or change something."
  3. Structural format instructions moved after behavioral ones, framed as "when you DO suggest changes"
  4. Keep untrusted data notice

**Tests:**
- Existing chat API tests pass (test endpoint, not Claude behavior)
- Manual verification

### Phase 3: DB-backed multi-turn chat

The big change. Replaces localStorage + single-turn with PostgreSQL + full conversation history. Atomic — can't be split without leaving the system in a broken intermediate state.

**Backend:**

**`src/songmaker_cli/db/models.py`**
- Add `ChatMessage` model: `id` (UUID), `song_id` (FK → Song, cascade delete), `role` (str), `content` (text), `created_at` (datetime)

**Alembic migration**
- Create `chat_messages` table

**`src/songmaker_cli/db/queries/chat.py`** (new)
- `list_chat_messages(session, song_id)` → list of ChatMessage ordered by created_at
- `create_chat_message(session, song_id, role, content)` → ChatMessage
- `delete_chat_messages(session, song_id)` → int (count deleted)
- `count_chat_messages(session, song_id)` → int (for limit enforcement)
- `songs_with_chat(session, user_id)` → list of (song_id, title, message_count, last_message_at) for recent chats

**`src/songmaker_cli/api_models/__init__.py`**
- `ChatMessageResponse`: id, role, content, created_at (with `from_orm()`)
- `ChatTurnResponse`: user_message (ChatMessageResponse), assistant_message (ChatMessageResponse)
- `ChatHistoryResponse`: messages (list of ChatMessageResponse)
- `SendChatRequest`: message (str), mentioned_song_ids (list[str] = []), mentioned_version_ids (list[str] = [])

**`src/songmaker_cli/chat_api.py`**
- `POST /api/songs/{song_id}/chat`:
  - `check_song_access()` for ownership
  - `create_job_with_rate_limit(session, user, "chat")` for rate limiting
  - `count_chat_messages()` → reject with 409 if >= 50
  - Validate `mentioned_song_ids` — each must pass `check_song_access()`
  - Validate `mentioned_version_ids` — each must belong to an accessible song
  - `_build_song_context(session, song_id, mentioned_song_ids, mentioned_version_ids)` → context string
  - Load history from DB → build `messages` array for Claude API
  - Extend provider to accept `messages` list (not just single prompt)
  - Store user message + assistant response in DB
  - Return `ChatTurnResponse`
- `GET /api/songs/{song_id}/chat` — load history with `check_song_access()`
- `DELETE /api/songs/{song_id}/chat` — clear with `check_song_access()`
- Remove old `POST /api/chat` endpoint
- Remove old `ChatRequest`/`ChatResponse` models

**`src/songmaker_cli/claude/provider.py`**
- Add `messages` parameter to `acall_claude()` / `_acall_api()` / `_acall_cli()`
- When `messages` is provided, send the full array instead of wrapping `prompt` in a single-message list
- CLI backend: concatenate messages into a single prompt string (CLI doesn't support multi-turn natively)
- API backend: pass `messages` directly to `client.messages.create()`

**`scripts/generate_types.py`** → regenerate types.ts

**Frontend:**

**`frontend/src/lib/api/client.ts`**
- `sendChatMessage(songId, message, mentionedSongIds, mentionedVersionIds)` → `ChatTurnResponse`
- `fetchChatHistory(songId)` → `ChatHistoryResponse`
- `clearChatHistory(songId)` → void
- Remove old `chatWithClaude()`

**`frontend/src/lib/components/ClaudeChat.svelte`**
- On mount / songId change: `fetchChatHistory(songId)` → populate messages
- On send: `sendChatMessage()` → append both user + assistant messages from response
- On clear: `clearChatHistory()` API → empty local array
- Remove all localStorage read/write logic
- Remove `buildFullContext` call — just send mention IDs
- Keep `parseApplyData()` — client-side `songmaker` block parsing stays (backend doesn't need to understand apply blocks)
- Show loading state while fetching history on song switch
- Clean up localStorage keys on first load (migration toast)

**`frontend/src/lib/utils/chat.ts`**
- Remove `loadMessages()`, `saveMessages()`, localStorage helpers
- Remove `buildFullContext()` and context-building logic
- Keep `parseApplyData()` and apply-related utilities

**Tests:**

Backend:
- `test_chat_api.py`: send message → both messages stored in DB, response contains both
- `test_chat_api.py`: send message with history → Claude receives full `messages` array
- `test_chat_api.py`: clear history → messages deleted
- `test_chat_api.py`: load history → returns messages in order
- `test_chat_api.py`: ownership check — can't access other user's song chat
- `test_chat_api.py`: mentioned song IDs validated (must own them)
- `test_chat_api.py`: message limit → 409 when at 50
- `test_chat_api.py`: rate limiting applied
- `test_queries_chat.py`: CRUD operations on ChatMessage
- `test_provider.py`: multi-turn messages passed to API correctly

Frontend:
- `client.test.ts`: new API functions call correct endpoints
- `chat.test.ts`: localStorage helpers removed, parseApplyData still works

### Phase 4: Recent chats indicator

Trivial with DB storage — just a query.

**Backend:**
- `GET /api/chat/recent` — returns songs with chat messages for current user
  - Uses `songs_with_chat()` query
  - Returns: song ID, title, message count, last message timestamp
  - Limited to 20 most recently active

**Frontend:**

**`frontend/src/lib/components/ClaudeChat.svelte`**
- Dropdown in chat header showing recent chats
- Fetched on mount, cached
- Click navigates to song + co-writer tab
- Current song highlighted

**`frontend/src/routes/+page.svelte`**
- Pass `onnavigate` callback to ClaudeChat

**Tests:**
- Backend: recent chats returns correct songs, respects ownership
- Frontend: dropdown renders, click triggers navigation

## File Ownership

| File | Phase |
|------|-------|
| `frontend/src/routes/+page.svelte` | 1, 4 |
| `frontend/src/lib/components/ClaudeChat.svelte` | 1, 3, 4 |
| `src/songmaker_cli/chat_api.py` | 2, 3 |
| `src/songmaker_cli/claude/provider.py` | 3 |
| `src/songmaker_cli/db/models.py` | 3 |
| `src/songmaker_cli/db/queries/chat.py` (new) | 3, 4 |
| `src/songmaker_cli/api_models/__init__.py` | 3 |
| `frontend/src/lib/api/client.ts` | 3 |
| `frontend/src/lib/utils/chat.ts` | 3 |
| Alembic migration | 3 |
| Tests (various) | 1, 2, 3, 4 |

## Priority

1. **Phase 1** — CSS + scroll fix. Quick wins, ship immediately.
2. **Phase 2** — Prompt rework. Biggest UX impact for least code change.
3. **Phase 3** — DB-backed multi-turn. The real fix. Makes the co-writer actually useful.
4. **Phase 4** — Recent chats. Polish. Trivial after Phase 3.

## Out of Scope

- Streaming Claude responses (SSE for chat — separate improvement)
- Chat message editing/deletion (individual messages)
- Chat branching (fork conversation from a point)
- Sharing chats between users
- Chat-aware generation (auto-apply suggestions)
