# Library and listening

For anyone building or reviewing library playback pools, shuffle and the player: the ruled product sentences, each under the ID its test cites.

### REQ-LIBRARY-01: A musician can choose one library listening pool on one inclusivity scale: Picks, + Keeps (Picks and Keeps) or All takes.

### REQ-LIBRARY-02: When no prior choice exists in the browser profile, the default library listening pool is Picks.

### REQ-LIBRARY-03: + Keeps is exactly the set union of playable Picks and playable Keeps, deduplicated by take.

### REQ-LIBRARY-04: Picks is exactly the set of playable Picks.

### REQ-LIBRARY-05: Keeps is exactly the set of playable Keeps.

### REQ-LIBRARY-06: All is exactly the set of playable audio takes.

### REQ-LIBRARY-07: Archived takes and takes whose audio is missing or unreadable are excluded from library playback.

### REQ-LIBRARY-08: A library listening pool may contain multiple takes of the same song when those takes are eligible for that pool.

### REQ-LISTENING-01: With Shuffle off, library playback is ordered by album title, track number, and then the song's takes from newest to oldest, with a stable identifier as the final tie-breaker.

### REQ-LISTENING-02: With Shuffle on, library playback randomizes the order of the selected pool without changing its membership.

### REQ-LISTENING-03: After reload or reopening in the same browser profile, Songmaker restores the last selected library pool and Shuffle state.

### REQ-LISTENING-04: Changing the library pool or Shuffle state while a take is playing does not interrupt that take, and following takes reflect the new selection.

### REQ-LISTENING-05: A library candidate with a missing audio path, missing audio file, or unreadable audio file is identified together with the applicable reason.

### REQ-LISTENING-06: Songmaker does not select a different take as a replacement for a library candidate whose audio is unavailable.

### REQ-LISTENING-07: At the end of a deliberately bounded library snapshot, playback stops after the last loaded take and reports that further takes were not loaded.

### REQ-PLAYER-01: While a take is playing, the signed-in player identifies the current song and gives access to its single Now Playing surface.

### REQ-PLAYER-02: On every player surface, while audio is loading, a first Play request queues playback and a second Play request cancels it.
