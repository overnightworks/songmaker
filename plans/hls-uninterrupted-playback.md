# Uninterrupted playback: stream-by-default + honest recovery + offline

**Status:** planned (rev 3 — both review passes folded)
**Date:** 2026-07-07

Felix's live complaint: playback stops on his phone (locked screen, cycling),
buttons intermittently dead. Rev-1 of this plan proposed HLS on a wrong root
cause; the plan review corrected it against the real code. **The repo already
has the right transport**: queue-stream mode concatenates the whole queue into
ONE MP3 server-side (`queue_streams.py:397-437`) and plays it as one media
element — media-engine continuity, no JS between tracks. It fails Felix
anyway because:

1. **Classic per-track mode is the default** (`playbackSettings.ts:8-14`) and
   the library queue context is ALWAYS classic (`player.ts:255-300`) — the
   JS `ended → playNextSong` advance (`player.ts:550-554`) is what locked
   phones kill.
2. **The trapdoor:** any media error or 5s stall in stream mode silently
   falls back to classic (`fallbackFromStream`, `audioPlayer.svelte.ts:404-415`)
   — one network blip mid-ride reinstates the death mode for the rest of the
   session.
3. Dead-button candidate: `toggle()` early-returns while `status ===
   'loading'` (`audioPlayer.svelte.ts:139`), which classic enters on every
   track change.

HLS is REJECTED for now, with reasons recorded: the concat stream already
gives engine-owned continuity; HLS adds segment-cache ownership, auth, and
rate-limit complexity the review enumerated, and on iOS native-HLS fetches
bypass the service worker, contradicting the offline story. Revisit only if
the fixed stream mode still fails on-device.

## Story A — the good path becomes THE path (small, ship first)

- Stream mode is the default for all queue playback, including the library
  queue context via a NEW server-side library scope on snapshot build (the
  frontend cannot enumerate lazily-loaded generations, `player.ts:58-70`;
  the server can). Oversize queues (> `QUEUE_STREAM_MAX_TRACKS`/6h caps,
  `queue_streams.py:31-32`) get a WINDOWED snapshot (first window + honest
  "queued the first N tracks" notice), never a silent classic fallback —
  the build-time classic fallback at `player.ts:143-146` is replaced by
  window-or-honest-error+retry. Shuffle re-keys the content hash → full
  re-encode; accepted with a visible "building stream…" state (windowing
  bounds the cost); smarter shuffle is out of scope.
- **Persisted-classic migration:** `playbackSettings.ts:12` eagerly wrote
  `'classic'` on every first visit — that was never a user choice. One-time
  migration flips stored `'classic'` to `'stream'`; from then on, a mode
  set through Settings writes an explicit-choice flag and IS respected
  (a deliberate classic survives future migrations).
- **Remove the classic trapdoor — recovery is STATUS-AWARE, in-stream:**
  probe on stall/error; 404 (snapshot TTL-reaped, `queue_streams.py:305-308`)
  → rebuild the snapshot from the manifest track list
  (`createQueueStreamSnapshot`) and seek to the tracked absolute position
  (`lastObservedTime`, `audioPlayer.svelte.ts:399`; pending-seek mechanism
  `queueStreamEngine.ts:82-92` gains a resume-at API); 401 → `onAuthLost`
  (parity with classic, `audioPlayer.svelte.ts:439-441`); otherwise bounded
  reload+seek with backoff (cap ~30s), cache-buster as classic recovery
  does (`:304-307`). Falling back to classic per-track playback is deleted.
- Fix the toggle dead-button: a press during `loading` queues intent with
  flip semantics (second press cancels), riding the existing
  `autoplayPending` machinery (`:245-248`).
- Classic remains only as an explicit Settings choice; editor single-track
  preview untouched (`load()` path); shared pages (`routes/share/*`) drive
  their own player and are OUT of Story A scope.
- On-device acceptance (Felix's actual failures): locked screen → full queue
  plays; brief network loss mid-track → playback self-resumes; snapshot
  expiry mid-play → seamless rebuild+resume; every lock-screen button press
  acts.

## Story B — offline for dead zones (PWA over the concat MP3)

- The single concatenated MP3 is the ideal offline artifact (one cacheable
  file; no HLS/SW-bypass problem on any platform).
- Backend: explicit routes for `/service-worker.js`, web-app manifest, and
  icons — the SPA fallback serves index.html for unknown root paths
  (`server.py:202-228`), so registration needs real routes.
- "Save for offline" on a playlist: SW caches the stream MP3 + manifest +
  artwork via Cache API, cache-first fetch for saved streams; visible size,
  progress, and a remove-download control.
- **Offline lifetime vs the 8h snapshot TTL** (`queue_streams.py:29,
  305-308`): a saved stream PINS its snapshot server-side. Pins are exempt
  from TTL, from quota eviction (`queue_streams.py:444-474`), and from the
  orphan sweep (`:344-356`); pinned bytes get their own config-owned cap;
  pin/unpin requires the same scope-ownership auth as the audio route
  (`queue_stream_api.py:100-102`); abandoned pins reap after a config-owned
  max age (default 30d) so cleared-browser clients can't make them immortal.
- **iOS/CSP realities (from review):** CSP gains `manifest-src 'self'`
  (`middleware/security_headers.py:17-26` is default-src 'none'); the SW
  synthesizes 206 partial responses from the cached MP3 — iOS media fetches
  use Range and will not play a cached file without it.
- Airplane-mode acceptance: saved playlist plays end-to-end with radios off.

## Verification

Repo gates (uv tests, lint, frontend checks) per story; the on-device
checklists above are the acceptance — a desktop pass does not close either
story. Plan review demands from rev-1 that survive (offsets from
segmentation, cache ownership, limiter sizing) apply only if HLS is ever
revisited and are recorded here for that day.
