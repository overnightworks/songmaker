# Library listening

## Intent

A musician can choose which curated takes belong in library playback, listen in
a predictable or shuffled order, and understand truthfully what is playing and
what could not be played.

## Rules

### REQ-LIBRARY-01: A musician can choose one library listening pool: Mix, Picks, Keeps, or All.
Quelle: OPERATOR — Issue #20, “Verhalten”, operator clarification dated 2026-08-20.

### REQ-LIBRARY-02: When no prior choice exists in the browser profile, the default library listening pool is Mix.
Quelle: OPERATOR — Issue #20, “Herkunft und Ziel” and “Verhalten”, operator decision dated 2026-08-20.

### REQ-LIBRARY-03: Mix is exactly the set union of playable Picks and playable Keeps, deduplicated by take.
Quelle: OPERATOR — Issue #20, “Verhalten”, operator decision dated 2026-08-20.

### REQ-LIBRARY-04: Picks is exactly the set of playable Picks.
Quelle: OPERATOR — Issue #20, “Verhalten”, operator decision dated 2026-08-20.

### REQ-LIBRARY-05: Keeps is exactly the set of playable Keeps.
Quelle: OPERATOR — Issue #20, “Verhalten”, operator decision dated 2026-08-20.

### REQ-LIBRARY-06: All is exactly the set of playable audio takes.
Quelle: OPERATOR — Issue #20, “Verhalten”, operator decision dated 2026-08-20.

### REQ-LIBRARY-07: Archived takes and takes whose audio is missing or unreadable are excluded from library playback.
Quelle: OPERATOR — Issue #20, “Verhalten”, operator decision dated 2026-08-20.

### REQ-LIBRARY-08: A library listening pool may contain multiple takes of the same song when those takes are eligible for that pool.
Quelle: OPERATOR — Issue #20, clarification comment 5356612998 dated 2026-08-20.

### REQ-LISTENING-01: With Shuffle off, library playback is ordered by album title, track number, and then the song's takes from newest to oldest, with a stable identifier as the final tie-breaker.
Quelle: OPERATOR — Issue #20, “Verhalten”, operator decision dated 2026-08-20.

### REQ-LISTENING-02: With Shuffle on, library playback randomizes the order of the selected pool without changing its membership.
Quelle: OPERATOR — Issue #20, “Herkunft und Ziel” and “Verhalten”, operator decision dated 2026-08-20.

### REQ-LISTENING-03: After reload or reopening in the same browser profile, Songmaker restores the last selected library pool and Shuffle state.
Quelle: OPERATOR — Issue #20, “Verhalten”, operator decision dated 2026-08-20.

### REQ-LISTENING-04: Changing the library pool or Shuffle state while a take is playing does not interrupt that take, and following takes reflect the new selection.
Quelle: OPERATOR — Issue #20, “Verhalten”, operator decision dated 2026-08-20.

### REQ-LISTENING-05: A library candidate with a missing audio path, missing audio file, or unreadable audio file is identified together with the applicable reason.
Quelle: DESK — Issue #20, “Plan-Review-Klärung: Skip und Window-Ende”, independently reviewed product clarification.

### REQ-LISTENING-06: Songmaker does not select a different take as a replacement for a library candidate whose audio is unavailable.
Quelle: DESK — Issue #20, “Verhalten” and “Plan-Review-Klärung: Skip und Window-Ende”, independently reviewed product clarification.

### REQ-LISTENING-07: At the end of a deliberately bounded library snapshot, playback stops after the last loaded take and reports that further takes were not loaded.
Quelle: DESK — Issue #20, “Plan-Review-Klärung: Skip und Window-Ende”, independently reviewed product clarification.

### REQ-PLAYER-01: While a take is playing, the signed-in player identifies the current song and gives access to its single Now Playing surface.
Quelle: OPERATOR — Issue #15, “Verhalten”, operator request dated 2026-08-20.

### REQ-PLAYER-02: On every player surface, while audio is loading, a first Play request queues playback and a second Play request cancels it.
Quelle: OPERATOR — Issue #15, “Verhalten” and “Acceptance”, operator request dated 2026-08-20.

## Non-goals

- Pick and Keep meanings and their independence are governed by
  `0001-creative-catalog-and-takes.md`; this document only defines their use in
  library listening pools.
- This revision does not define album, playlist, or public-share queue
  membership or traversal; the common loading-intent rule still applies to
  every player surface.
- This revision does not define the contents of Now Playing or synchronize
  lyrics with playback.
- This document does not prescribe queue APIs, storage mechanisms, audio
  frameworks, rendering layout, or a shuffle algorithm.
