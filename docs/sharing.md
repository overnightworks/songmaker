# Sharing and administration

For anyone building or reviewing public shares and administration: the ruled product sentences, each under the ID its test cites.

### REQ-SHARE-01: A musician can enable a public share of an owned album, song, audio take, or playlist.

### REQ-SHARE-02: A public share is reachable without signing in.

### REQ-SHARE-03: A public share does not allow editing, generating, or changing Pick or Keep.

### REQ-SHARE-04: Ending a share makes that public link unreachable.

### REQ-SHARE-05: Enabling a share after it was ended does not restore the previous public link.

### REQ-SHARE-06: Ending a share is authorized on that album, song, take, or playlist; Songmaker does not provide a generic unshare action.

### REQ-SHARE-18: An invalid or removed public share names the missing resource type and does not disclose internal identifiers, paths, or authorization details.

### REQ-SHARE-19: An invalid or removed public share offers exactly one primary recovery action to the public start or login surface.

### REQ-SHARE-20: Retry is offered only for a retryable technical failure of a public share, not for an invalid or removed link.

### REQ-SHARE-21: For each song included in an album or song public share, when that song has an unarchived Pick, Songmaker presents that Pick.

### REQ-SHARE-22: A take public share presents that shared take.

### REQ-SHARE-23: A playlist public share presents the take of each playlist entry that still has a take; it does not substitute a different take for a missing entry.

### REQ-SHARE-24: A public share does not include scores or edit history.

### REQ-SHARE-25: A musician who is not an administrator cannot reach another musician's private albums, songs, takes, or playlists except through a currently active public share.

### REQ-SHARE-26: An agent with its own account can enable a public share of its own song.

### REQ-SHARE-27: A person's own agent cannot enable a public share.

### REQ-ADMIN-01: A user has exactly one role: administrator or user.

### REQ-ADMIN-05: A user cannot create another user.

### REQ-ADMIN-08: A successful login adds an independent session and does not end every other valid session of the same account.

### REQ-ADMIN-09: Logout ends only the current session.

### REQ-ADMIN-11: When a user's concurrent sessions exceed Songmaker's concurrent-session cap, Songmaker ends the oldest sessions until the cap is met and does not end every session.
