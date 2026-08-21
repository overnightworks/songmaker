# Co-Writer

## Intent

Co-Writer is a multi-turn studio partner on one active conversation per
musician, not one conversation per song. Durable user and song memory,
musician-confirmed mentions, the open song's current lyrics and style prompt,
and the relevant take's sung transcription travel with each turn. Claude, Grok,
and Codex share the same song read and write capabilities with no silent
provider fallback. The model may persist owned-song lyric, prompt, title, BPM,
key, and duration writes and may create songs; memory changes persist only after
Accept; Co-Writer does not generate audio or choose the Pick or Keep. When
conversation history fits the token-bounded tail it is sent verbatim; when over
budget, a rolling summary plus that tail — full history is not a fallback.

## Rules

### REQ-COWRITER-01: A signed-in musician has at most one active Co-Writer conversation; Songmaker does not require one conversation per song.
Quelle: DESK — Issue #35, “Locked-in” (global conversation remains allowed; no conversation per song); corroborated by the user-scoped Conversation model.

### REQ-COWRITER-02: Starting a new Co-Writer conversation does not delete user memory, song memory, or album notes.
Quelle: OPERATOR — Issue #35, “Verhalten”.

### REQ-COWRITER-03: Switching the open song does not start or archive a Co-Writer conversation.
Quelle: OPERATOR — Issue #35, “Verhalten”.

### REQ-COWRITER-04: Switching the open song does not include the previous song's memory in the next Co-Writer turn.
Quelle: OPERATOR — Issue #35, “Verhalten” and Acceptance.

### REQ-COWRITER-05: When conversation history fits the configured token-bounded tail, the Co-Writer turn receives that history verbatim.
Quelle: OPERATOR — Issue #26, “Verhalten”.

### REQ-COWRITER-06: When conversation history exceeds the configured token-bounded tail and rolling-summary creation succeeds, the Co-Writer turn receives a rolling summary plus that tail that together cover every historical message once.
Quelle: OPERATOR — Issue #26, “Locked-in” and “Verhalten”.

### REQ-COWRITER-07: When rolling-summary creation fails, the Co-Writer turn continues with a limited tail and does not receive the full history as a fallback.
Quelle: OPERATOR — Issue #26, “Verhalten”.

### REQ-COWRITER-08: When a Co-Writer turn uses a rolling summary, that summary preserves at least the album concept, locked versus open lyric decisions, names and characters, and open questions.
Quelle: OPERATOR — Issue #26, “Locked-in”.

### REQ-COWRITER-09: A Co-Writer turn uses exactly one of Claude, Grok, or Codex.
Quelle: OPERATOR — Issue #34, “Locked-in”.

### REQ-COWRITER-10: When no Co-Writer provider has been chosen, the provider is Claude.
Quelle: OPERATOR — Issue #34, “Verhalten”.

### REQ-COWRITER-11: When the chosen Co-Writer provider is unknown, not configured, or unavailable, the turn ends with a named error for that provider; Songmaker does not silently use a different provider.
Quelle: OPERATOR — Issue #34, “Locked-in”.

### REQ-COWRITER-12: Claude, Grok, and Codex have the same Co-Writer read and write capabilities under the same ownership and persistence rules.
Quelle: OPERATOR — Issue #34, “Locked-in”.

### REQ-COWRITER-13: Changing Co-Writer provider does not change the active conversation, its history, memory, mentions, or take context.
Quelle: OPERATOR — Issue #34, “Verhalten”.

### REQ-COWRITER-14: User memory and song memory are separate; album notes are optional.
Quelle: OPERATOR — Issue #35, “Locked-in”.

### REQ-COWRITER-15: User memory and song memory are visible and musician-editable; when album notes are present, they are visible and musician-editable.
Quelle: OPERATOR — Issue #35, “Locked-in”.

### REQ-COWRITER-16: Co-Writer memory is not a second lyrics source.
Quelle: OPERATOR — Issue #35, “Locked-in”.

### REQ-COWRITER-17: A model-proposed Co-Writer memory change is persisted only after the musician accepts it; rejecting or ignoring the proposal leaves stored memory unchanged.
Quelle: OPERATOR — Issue #35, “Locked-in”.

### REQ-COWRITER-18: When a song is open, the Co-Writer turn includes that song's current lyrics and style prompt, separate from memory.
Quelle: DESK — Issue #35, Herkunft (open-song snapshot) and “Verhalten” envelope; corroborated by the current turn context.

### REQ-COWRITER-19: Mentioned songs, albums, and versions are resolved by Songmaker from authorized identifiers; the client does not supply lyrics as mention truth.
Quelle: OPERATOR — Issue #36, “Locked-in”.

### REQ-COWRITER-20: Unknown, foreign, or unrelated mention identifiers refuse the whole Co-Writer turn.
Quelle: OPERATOR — Issue #36, “Verhalten”.

### REQ-COWRITER-21: Only musician-confirmed mention identifiers become mention context; unmatched @-text remains ordinary message text.
Quelle: OPERATOR — Issue #36, “Verhalten”.

### REQ-COWRITER-22: An album mention is expanded by Songmaker to that album's authorized tracks.
Quelle: OPERATOR — Issue #36, “Verhalten” and Acceptance.

### REQ-COWRITER-23: A version mention is the chosen version of the open song and is not silently replaced by the latest version.
Quelle: OPERATOR — Issue #36, “Verhalten” and Acceptance.

### REQ-COWRITER-24: When the musician is playing a take of the open song, that take is the relevant Co-Writer take even if another take is the Pick.
Quelle: OPERATOR — Issue #37, “Verhalten”.

### REQ-COWRITER-25: When no matching playing take exists, the relevant Co-Writer take is the playable Pick, else the newest playable take, else a named no-take state.
Quelle: OPERATOR — Issue #37, “Verhalten”.

### REQ-COWRITER-26: The relevant Co-Writer take includes its sung transcription, Pick, Keep, and persisted scores when those values exist; missing transcription or scores stay empty and are not estimated.
Quelle: OPERATOR — Issue #37, “Locked-in” and “Verhalten”.

### REQ-COWRITER-27: A Co-Writer turn does not start transcription or scoring.
Quelle: OPERATOR — Issue #37, “Locked-in”.

### REQ-COWRITER-28: A Co-Writer turn does not send take audio to the provider.
Quelle: OPERATOR — Issue #37, “Grenzen”.

### REQ-COWRITER-29: An explicit take that is unknown, foreign, for another song, or not playable refuses the Co-Writer turn; Songmaker does not silently substitute a different take.
Quelle: OPERATOR — Issue #37, “Verhalten”.

### REQ-COWRITER-30: A Co-Writer turn can create a new song in an album the musician owns.
Quelle: OPERATOR — Issue #34, “Locked-in” write tools; corroborated by the current create-song tool that persists.

### REQ-COWRITER-31: A Co-Writer turn can persist lyrics, style prompt, title, BPM, key, or duration of an owned song without a separate Accept step.
Quelle: OPERATOR — Issue #34, “Locked-in” write tools; corroborated by the current update, rename, and style tools that persist.

### REQ-COWRITER-32: A Co-Writer turn does not start audio generation and does not select or change a song's Pick or Keep.
Quelle: DESK — Issue #34 locked-in Songmaker tool catalog (song read/write, not generate, Pick, or Keep) and Issue #37 “Grenzen”; corroborated by the current Co-Writer tool list.

### REQ-COWRITER-33: A Co-Writer turn includes the musician's user memory; when a song is open, the turn also includes that song's memory and, when present, that album's notes.
Quelle: OPERATOR — Issue #35, “Verhalten” and Acceptance.

## Non-goals

- Pick and Keep meanings belong to `0001-creative-catalog-and-takes.md`;
  this document only uses them as take facts and forbids Co-Writer from changing
  them.
- Sung transcription as information versus lyrics remains REQ-SCORE-02; this
  document only requires the relevant take's transcription in the Co-Writer
  turn.
- Library pools, player surfaces except forwarding the matching playing take,
  generation-start, ACE-Step, and seed/model/param rules belong to 0002 and
  0003.
- Sharing/Administration, including which role may change Co-Writer provider,
  model, or tail budget.
- Exact tail-budget numbers, token-count algorithm, SSE event types, MCP/CLI
  transport, argv secrecy, and process-group reaping.
- Scoring provider and scoring model (remain Claude per Issue #34; out of
  Co-Writer).
- Legacy per-song chat endpoints and user-applied songmaker blocks.
- Vector RAG and automatic copying of take facts into memory.
- This document does not prescribe database, API, or provider-adapter mechanisms.
