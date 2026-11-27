# Now Playing and its queue: frozen pictures

These pictures fix content, order, wording and rough layout, never pixels, fonts
or colours.

- `sung-marks.png` fixes the sung marks (#3389, ruled point 4).
- `phone-queue.png` fixes the phone Queue (#3389, line 2 A): it has no "Add a song"
  field, and its head reads "from ‹album›".
- `fable-add.png` fixes the Add to… picker (‹ Add to back, the playlists with cover
  and count, the New playlist… field); it has no Queue row until a later slice adds it.
- "✦ KI-generiert" stays under the title.
- `fable-np.png` fixes the content, order, wording and rough layout of the desktop Now Playing (the take column with its judging card, the lyrics column, the Queue column). It is overridden by #3389: line 6 A removes the Re-score link and the ↻ (Re-score is a row of the take menu); sung marks follow `sung-marks.png`; the Queue head reads "from ‹album›"; "✦ KI-generiert" stays under the title.
- `fable-np-phone.png` fixes the same for the phone, with the same overrides.
- `fable-album.png` fixes the content, order, wording and rough layout of the album page: the amber No Pick badge after a title (a song with takes and no Pick, none without takes) and the header line "9 songs · 2 without a Pick"; the row ⋯ and its song menu belong to the song-menu slice, not this one.

The judging-card slice (#3471) proves the take column of `fable-np.png` and `fable-np-phone.png` only: the Recipe strip and the Queue column belong to later slices of #3389.
