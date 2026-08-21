# Sharing and administration

## Intent

A musician can publish selected albums, songs, audio takes, and playlists as
public shares that a visitor can reach without an account, see a complete
honest inventory of what is currently reachable, and revoke a share so the
previous public link stops working. A visitor cannot edit the shared work,
start generation, or change Pick or Keep. A musician who is not an
administrator cannot reach another musician's private albums, songs, takes, or
playlists except through a currently active public share. Administration is a
closed signup: completing setup creates the first administrator; later users
are created by an administrator with role administrator or user. A successful
login on another device adds a session and does not sign every other device of
that account out.

## Rules

### REQ-SHARE-01: A musician can enable a public share of an owned album, song, audio take, or playlist.
Quelle: DESK — CLAUDE.md, “Sharing via ShareMixin”; corroborated by Issue #70 Locked-in types and the current share endpoints.

### REQ-SHARE-02: A public share is reachable without signing in.
Quelle: OPERATOR — Issue #51, “Grenzen”: no login required for public shares; corroborated by unauthenticated `/shared/...` and `/share/...` routes.

### REQ-SHARE-03: A public share does not allow editing, generating, or changing Pick or Keep.
Quelle: DESK — current unauthenticated public share routes are read-only; corroborated by the current `/shared/...` JSON and audio routes.

### REQ-SHARE-04: Ending a share makes that public link unreachable.
Quelle: OPERATOR — Issue #51 (invalid or removed share) and Issue #70 Unshare; corroborated by current unshare clearing the share and 404 after revoke.

### REQ-SHARE-05: Enabling a share after it was ended does not restore the previous public link.
Quelle: DESK — current disable clears the slug and the next enable issues a new public link; corroborated by revoke-then-404 tests.

### REQ-SHARE-06: Ending a share is authorized on that album, song, take, or playlist; Songmaker does not provide a generic unshare action.
Quelle: OPERATOR — Issue #70 Locked-in and comment 5371114070.

### REQ-SHARE-07: A musician's share inventory lists every currently public share of that musician's albums, songs, audio takes, and playlists, including a shared take whose song was never opened in the library.
Quelle: OPERATOR — Issue #70 Locked-in and Acceptance.

### REQ-SHARE-08: Share-inventory membership is exactly currently public shares: shared and publicly reachable, not soft-deleted; an archived take remains if it is still public.
Quelle: OPERATOR — Issue #70 comment 5371114070; corroborated by inventory tests for archived takes and soft-delete exclusion.

### REQ-SHARE-09: Share-inventory truth comes from the musician's own share state, not from whichever library pages the client has loaded.
Quelle: OPERATOR — Issue #70 Herkunft/Ziel and Locked-in.

### REQ-SHARE-10: Share inventory and its total count include only the signed-in user's shares; they never include another user's shares, including when the signed-in user is an administrator.
Quelle: OPERATOR — Issue #70 Acceptance and comment 5371114070 (`user.id` only, never `owner_filter`).

### REQ-SHARE-11: The unfiltered share-inventory total is the true count of that user's public shares; a type filter pages a subset and does not change that total.
Quelle: OPERATOR — Issue #70 Locked-in.

### REQ-SHARE-12: Each inventory entry identifies its resource form, title, needed parent context, and public link.
Quelle: OPERATOR — Issue #70 Locked-in.

### REQ-SHARE-13: A musician can open a listed share, copy its public link, and end that share.
Quelle: OPERATOR — Issue #70 Locked-in.

### REQ-SHARE-14: Ending a listed share confirms that the public link will stop working.
Quelle: OPERATOR — Issue #70 Locked-in (“bestätigt die konkrete Konsequenz”).

### REQ-SHARE-15: Share inventory is a secondary status and entry to the inventory, not a peer library working mode.
Quelle: OPERATOR — Issue #70 Locked-in. Exact header chrome and Studio/Listen placement remain #39.

### REQ-SHARE-16: “Nothing shared” appears only after a complete server inventory response.
Quelle: OPERATOR — Issue #70 Locked-in.

### REQ-SHARE-17: Loading, empty, partial, and failed inventory states are distinct; a partial page is not presented as the complete inventory.
Quelle: OPERATOR — Issue #70 Locked-in.

### REQ-SHARE-18: An invalid or removed public share names the missing resource type and does not disclose internal identifiers, paths, or authorization details.
Quelle: OPERATOR — Issue #51 Locked-in.

### REQ-SHARE-19: An invalid or removed public share offers exactly one primary recovery action to the public start or login surface.
Quelle: OPERATOR — Issue #51 Locked-in.

### REQ-SHARE-20: Retry is offered only for a retryable technical failure of a public share, not for an invalid or removed link.
Quelle: OPERATOR — Issue #51 Locked-in.

### REQ-SHARE-21: For each song included in an album or song public share, when that song has an unarchived Pick, Songmaker presents that Pick.
Quelle: DESK — current album and song public-share presentation of the Pick; corroborated by the current shared album and song routes.

### REQ-SHARE-22: A take public share presents that shared take.
Quelle: DESK — current take public-share routes; corroborated by `/shared/gen/{slug}`.

### REQ-SHARE-23: A playlist public share presents the take of each playlist entry that still has a take; it does not substitute a different take for a missing entry.
Quelle: DESK — current playlist public-share routes; corroborated by `/shared/playlist/{slug}`.

### REQ-SHARE-24: A public share does not include scores or edit history.
Quelle: DESK — current public share JSON isolation; corroborated by public share responses omitting scores and edit history.

### REQ-SHARE-25: A musician who is not an administrator cannot reach another musician's private albums, songs, takes, or playlists except through a currently active public share.
Quelle: DESK — CLAUDE.md ownership checks on every resource endpoint; corroborated by Issue #70 isolation and current 404 on foreign resources.

### REQ-ADMIN-01: A user has exactly one role: administrator or user.
Quelle: DESK — current create and update user role is administrator or user.

### REQ-ADMIN-02: When no users exist, completing setup creates the first administrator.
Quelle: DESK — current first-run setup creates the first administrator.

### REQ-ADMIN-03: After at least one user exists, Songmaker does not offer an open signup.
Quelle: DESK — setup refuses once users exist; corroborated by the invite-only deployment (not an invite-token feature).

### REQ-ADMIN-04: An administrator can create a user with a username, password, and role of administrator or user.
Quelle: DESK — current admin create-user workflow.

### REQ-ADMIN-05: A user cannot create another user.
Quelle: DESK — admin endpoints require administrator role; corroborated by current admin-role tests.

### REQ-ADMIN-06: Songmaker refuses to demote or deactivate the last active administrator.
Quelle: DESK — current last-admin guards.

### REQ-ADMIN-07: An administrator cannot deactivate or permanently delete their own account.
Quelle: DESK — current admin user endpoints and self-deactivation refusal.

### REQ-ADMIN-08: A successful login adds an independent session and does not end every other valid session of the same account.
Quelle: OPERATOR — Issue #67, “Festgelegtes Verhalten”.

### REQ-ADMIN-09: Logout ends only the current session.
Quelle: OPERATOR — Issue #67, “Festgelegtes Verhalten”.

### REQ-ADMIN-10: Changing a user's password, deactivating a user, or deleting a user ends every session of that user.
Quelle: OPERATOR — Issue #67, “Festgelegtes Verhalten”.

### REQ-ADMIN-11: When a user's concurrent sessions exceed Songmaker's concurrent-session cap, Songmaker ends the oldest sessions until the cap is met and does not end every session.
Quelle: OPERATOR — Issue #67, “Festgelegtes Verhalten”.

### REQ-ADMIN-12: An administrator can revoke a listed session without being shown that session's raw token.
Quelle: OPERATOR — Issue #67, “Festgelegtes Verhalten”.

## Non-goals

- Library, Studio, and Listen information architecture and exact header chrome
  belong to Issue #39.
- Recipe versus Takes naming belongs to Issue #69; this document uses “audio
  take”.
- This revision does not define public-share player queue membership, order, or
  windowing.
- Pick and Keep meanings belong to `0001-creative-catalog-and-takes.md`; this
  document only uses Pick as a public-share presentation fact.
- Sung transcription as information versus lyrics remains REQ-SCORE-02.
- Auth, rate-limit, cookie, CSRF, Redis, and slug-entropy internals belong to
  `docs/security.md`, including the concurrent-session cap number.
- Which take an album or song public share presents when there is no
  unarchived Pick, including whether Songmaker may substitute the latest
  unarchived take that has audio; this revision does not freeze a silent
  substitute take.
- Whether a public share presents lyrics or sung transcription.
- Whether enabling a share must mark a presented take as Keep.
- Whether an administrator may open another musician's private studio catalog.
- Which role may change Co-Writer provider, model, or tail budget.
- Invite tokens, email invites, or any join path other than first-run setup
  plus administrator-created username and password.
- MFA, social features, collaboration, or recipient management.
- A claimed share time.
- The fate of a permanently deleted user's public shares.
- Exact inventory sort keys, token-count algorithms, and other mechanisms.
- This document does not prescribe database, API, or storage mechanisms.
