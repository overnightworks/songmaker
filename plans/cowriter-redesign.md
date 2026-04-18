**Status:** Proposed
**Date:** 2026-04-18

# Co-Writer Redesign: Claude Code Model + MCP Tools

## Goal

Rebuild the co-writer to feel like Claude Code. One conversation, always visible, Claude retrieves context on demand via tools instead of pre-loaded @-mentions. The user keeps switching to the Claude Code CLI because it feels better — the co-writer should feel the same.

## Locked-in decisions

- **One conversation, not scoped to song or album.** Like opening a terminal. Claude can reach any song the user owns. "New conversation" archives the old one. Songs and versions are the persistent record, not the chat.
- **MCP server for song access.** Claude gets tools (search, read, update, create) instead of @-mention context injection. Works with the existing CLI subprocess + Max subscription. No SDK migration. *Verified 2026-04-18:* CLI supports custom stdio MCP servers in `-p` mode via `--mcp-config` (inline JSON or file path). Tool restriction via `--allowedTools` / `--disallowedTools`. Streaming + tool events via `--output-format stream-json`. `--bare` skips auto-discovery for faster startup. Max-subscription credentials via existing bind mounts work unchanged.
- **MCP lifecycle: per-request, tied to the CLI subprocess.** Spawn together, die together. `user_id` passed via env var. No persistent processes.
- **Tools write to the editor draft, not new Versions.** Same as if the user typed it. Versions are only created when the user generates audio or explicitly saves. Claude does not pollute version history.
- **Live editor updates flow through the chat response stream.** SSE carries `tool_call_completed` events with new song state. Frontend chat handler updates both chat UI and editor store from the same stream. No separate WebSocket.
- **Execute immediately, strong undo.** No "Claude asks first" round-trips. System prompt instructs Claude to verbalize intent before each write ("I'm rewriting the chorus to..."). Every Claude-driven change is one-click revert in the editor. Exception: destructive operations (delete song/album) require explicit user confirmation.
- **Currently open song injected into system prompt every request.** Frontend sends `current_song_id` with each message. Backend reads fresh from DB and injects as `<current_song>` block. Switching songs mid-conversation just changes the next message's context.
- **No hard message cap.** All messages stored in DB, full history in UI. Token-based summarization: when conversation exceeds ~80% of context window, a separate Claude call summarizes oldest messages, result stored in `ConversationSummary` and cached. Manual "compact" button also available.
- **One Job per chat turn.** Tool calls inside a turn are implementation detail. Same rate-limiting model as today.
- **Streaming via CLI.** Verify `--output-format stream-json` works through the subprocess wrapper. If yes, ship streaming V1. If wrapping is hard, ship non-streaming V1, add streaming V2.
- **Always-visible side panel on desktop.** Not a tab. Editor and chat side-by-side, resizable, collapsible.
- **Mobile: chat stays a tab, but proposed changes render as inline diff cards in the chat itself.** Review and apply without switching to the editor tab.
- **Remove @-mention system entirely.** Claude fetches context via tools. User just talks naturally.
- **Inline song cards in chat.** When Claude reads/creates/modifies a song, show a card with title + preview + "switch to it" link. Switching changes the editor pane, not full navigation.
- **MCP server exposes only songmaker tools.** File system, bash, and other dangerous CLI tools stay blocked via `_DISALLOWED_TOOLS`. Ownership checks on every tool call via existing `check_*_access()` helpers.
- **Old `songmaker` blocks in archived messages render as plain text.** No apply buttons back-ported. They're history.

## Hard constraints

- MCP server must not expose any non-songmaker tools
- Ownership checks on every tool call — Claude cannot reach other users' data
- Existing chat history survives migration (grouped into per-album conversations as a starting point)
- Mobile must remain fully functional
- Claude-driven writes must always be revertible from the editor

## What we skip

| Feature | Why |
|---|---|
| Per-song or per-album chat scoping | Overcomplicates what should be simple |
| Thread system | Management overhead for a solo user |
| Creative journal / decision log | Songs + versions ARE the record |
| SDK migration | MCP + CLI works with Max subscription |

## First step

Read the live code: `claude/provider.py` (CLI subprocess + tool denylist), `chat_api.py` (current chat flow), `ClaudeChat.svelte` + `SongDetailView.svelte` (UI). Then design + execute. Suggested sequencing: MCP server first (tools + DB access, testable in isolation), then conversation data model migration, then the streaming + tool-call handling in the backend, then the UI.
