# Catalog and take curation

For anyone building or reviewing how songs, versions, takes, Pick and Keep behave: the ruled product sentences, each under the ID its test cites.

### REQ-CATALOG-01: Every song belongs to exactly one album.

### REQ-VERSION-01: A musician can save lyrics, a style prompt, and generation settings together as a song version.

### REQ-GENERATION-01: Each audio take produced by Songmaker's generation workflow is initially associated with the song and song version requested for that generation.

### REQ-CURATION-01: A song has at most one Pick, which is its selected album take.

### REQ-CURATION-02: Selecting a new Pick replaces the same song's previous Pick.

### REQ-CURATION-03: Changing a song's Pick does not change whether any audio take is a Keep.

### REQ-CURATION-04: More than one audio take from the same song may be a Keep.

### REQ-CURATION-05: Changing whether an audio take is a Keep does not change the song's Pick.

### REQ-CURATION-06: Running take cleanup for a song or album preserves every Pick and Keep.

### REQ-CURATION-07: Automatic retention never deletes an audio take that is a Pick or a Keep, even when it was archived before it was marked.

### REQ-CURATION-08: Stage 1 of automatic retention re-checks Pick and Keep when it writes, so a Keep that commits between selection and write wins.

### REQ-CURATION-09: An archived audio take cannot be made a Pick or a Keep, shared, or added to a playlist until it is restored.
