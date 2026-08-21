# Creative catalog and take curation

## Intent

A musician can develop songs inside coherent albums, retain the creative context
of generated audio, choose one album take, and preserve other favourites.

## Rules

### REQ-CATALOG-01: Every song belongs to exactly one album.
Quelle: DESK — CLAUDE.md, “Product Context”, paragraph 1; corroborated by the current Album and Song domain model.

### REQ-VERSION-01: A musician can save lyrics, a style prompt, and generation settings together as a song version.
Quelle: DESK — CLAUDE.md, “Product Context”, paragraph 2; corroborated by the current Version domain model.

### REQ-GENERATION-01: Each audio take produced by Songmaker's generation workflow is initially associated with the song and song version requested for that generation.
Quelle: DESK — CLAUDE.md, “Product Context”, paragraph 2; corroborated by the current generation workflow.

### REQ-CURATION-01: A song has at most one Pick, which is its selected album take.
Quelle: OPERATOR — Issue #20, “Herkunft und Ziel”, operator decision dated 2026-08-20.

### REQ-CURATION-02: Selecting a new Pick replaces the same song's previous Pick.
Quelle: OPERATOR — Issue #20, “Herkunft und Ziel”, operator decision dated 2026-08-20.

### REQ-CURATION-03: Changing a song's Pick does not change whether any audio take is a Keep.
Quelle: OPERATOR — Issue #20, “Verhalten”, locked-in independent Pick and Keep semantics.

### REQ-CURATION-04: More than one audio take from the same song may be a Keep.
Quelle: OPERATOR — Issue #20, “Herkunft und Ziel”, operator decision dated 2026-08-20.

### REQ-CURATION-05: Changing whether an audio take is a Keep does not change the song's Pick.
Quelle: OPERATOR — Issue #20, “Verhalten”, locked-in independent Pick and Keep semantics.

### REQ-CURATION-06: Running take cleanup for a song or album preserves every Pick and Keep.
Quelle: DESK — CLAUDE.md, “Product Context”, paragraph 3; corroborated by current song and album cleanup behavior.

## Non-goals

- This revision does not decide exactly when an edit creates a new version.
- Imported audio may lack a version link, and deleting a version may detach its
  retained generations; this revision does not promise permanent provenance.
- This revision does not govern automatic retention of an already archived Pick
  or Keep.
- Library pool, shuffle, player, and user-interface behavior belong to the
  Library/Listening requirement document.
- This document does not prescribe database, API, storage, or generation-engine
  mechanisms.
