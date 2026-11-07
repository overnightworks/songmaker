# Co-Writer

For anyone building or reviewing the Co-Writer conversation and its tools: the ruled product sentences, each under the ID its test cites.

### REQ-COWRITER-01: A signed-in musician has at most one active Co-Writer conversation; Songmaker does not require one conversation per song.

### REQ-COWRITER-02: Starting a new Co-Writer conversation does not delete user memory, song memory, or album notes.

### REQ-COWRITER-03: Switching the open song does not start or archive a Co-Writer conversation.

### REQ-COWRITER-04: Switching the open song does not include the previous song's memory in the next Co-Writer turn.

### REQ-COWRITER-05: When conversation history fits the configured token-bounded tail, the Co-Writer turn receives that history verbatim.

### REQ-COWRITER-06: When conversation history exceeds the configured token-bounded tail and rolling-summary creation succeeds, the Co-Writer turn receives a rolling summary plus that tail that together cover every historical message once.

### REQ-COWRITER-07: When rolling-summary creation fails, the Co-Writer turn continues with a limited tail and does not receive the full history as a fallback.

### REQ-COWRITER-08: When a Co-Writer turn uses a rolling summary, that summary preserves at least the album concept, locked versus open lyric decisions, names and characters, and open questions.

### REQ-COWRITER-09: A Co-Writer turn runs through the LiteLLM gateway, and the agent file alone names its model.

### REQ-COWRITER-11: When the gateway refuses or fails the turn, it ends with a named error; Songmaker never answers through a local provider or another model.

### REQ-COWRITER-12: Every model the Co-Writer runs on gets the same tools under the same ownership and persistence rules.

### REQ-COWRITER-13: Changing the Co-Writer's model does not change the active conversation, its history, memory, mentions, or take context.

### REQ-COWRITER-14: User memory and song memory are separate; album notes are optional.

### REQ-COWRITER-15: User memory and song memory are visible and musician-editable; when album notes are present, they are visible and musician-editable.

### REQ-COWRITER-16: Co-Writer memory is not a second lyrics source.

### REQ-COWRITER-17: A model-proposed Co-Writer memory change is persisted only after the musician accepts it; rejecting or ignoring the proposal leaves stored memory unchanged.

### REQ-COWRITER-18: When a song is open, the Co-Writer turn includes that song's current lyrics and style prompt, separate from memory.

### REQ-COWRITER-19: Mentioned songs, albums, and versions are resolved by Songmaker from authorized identifiers; the client does not supply lyrics as mention truth.

### REQ-COWRITER-20: Unknown, foreign, or unrelated mention identifiers refuse the whole Co-Writer turn.

### REQ-COWRITER-21: Only musician-confirmed mention identifiers become mention context; unmatched @-text remains ordinary message text.

### REQ-COWRITER-22: An album mention is expanded by Songmaker to that album's authorized tracks.

### REQ-COWRITER-23: A version mention is the chosen version of the open song and is not silently replaced by the latest version.

### REQ-COWRITER-24: When the musician is playing a take of the open song, that take is the relevant Co-Writer take even if another take is the Pick.

### REQ-COWRITER-25: When no matching playing take exists, the relevant Co-Writer take is the playable Pick, else the newest playable take, else a named no-take state.

### REQ-COWRITER-26: The relevant Co-Writer take includes its sung transcription, Pick, Keep, and persisted scores when those values exist; missing transcription or scores stay empty and are not estimated.

### REQ-COWRITER-27: A Co-Writer turn does not start transcription or scoring.

### REQ-COWRITER-28: A Co-Writer turn does not send take audio to the provider.

### REQ-COWRITER-29: An explicit take that is unknown, foreign, for another song, or not playable refuses the Co-Writer turn; Songmaker does not silently substitute a different take.

### REQ-COWRITER-30: A Co-Writer turn can create a new song in an album the musician owns.

### REQ-COWRITER-31: A Co-Writer turn can persist lyrics, style prompt, title, BPM, key, or duration of an owned song without a separate Accept step.

### REQ-COWRITER-32: A Co-Writer turn does not start audio generation and does not select or change a song's Pick or Keep.

### REQ-COWRITER-33: A Co-Writer turn includes the musician's user memory; when a song is open, the turn also includes that song's memory and, when present, that album's notes.

### REQ-COWRITER-34: When the musician asks, the Co-Writer stores its coherence verdict, a whole number from 1 to 10 and one sentence, on one of their takes that has a sung transcription; only a later Co-Writer verdict replaces it.
