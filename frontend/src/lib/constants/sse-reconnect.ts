// SSE reconnection backoff: jobs.ts (one EventSource per job)
// and resourceSync.ts (the one live-sync stream) both own their `/api/*`
// stream connection and must not lean on the browser's flat ~3s native
// EventSource retry, which produced an ERR_QUIC storm
// (~80 opens/min across a handful of concurrently-reconnecting streams).
// Both close the failed connection themselves and reopen it after
// `nextReconnectDelayMs(attempt)` (see `lib/stores/sseReconnect.ts`):
// doubling from a floor up to an 8s ceiling, plus 0-20% jitter so
// concurrently-failing streams don't all reopen in lockstep. Jitter only
// adds to the delay, never subtracts, so it can only slow a stream down
// relative to the math below, never speed it up. A waiting stream also
// reopens at once when the page becomes visible, regains focus or the
// browser reports the network back (`watchReconnectOpportunities`); those
// reopens follow the musician's own actions, one per waiting stream each,
// and at most one per `SSE_IMMEDIATE_REOPEN_MIN_GAP_MS` per stream -- 20
// app switches in 3s once opened 40 streams. Only the reopen is
// spaced: inside the gap a waiting stream keeps its backoff, while the
// library's revalidation (debounced on its own) and the restart of a first
// sync that failed with a visible error (no backoff to wait on) still run.
// The gap never adds opens to the math below.
//
// The wait is capped at 10s: a phone whose
// network returned without an `online` event showed its new take 22-27s
// late, because the backoff had grown to ~30s. An 8s ceiling keeps the
// longest wait, jitter included, at 8 * 1.2 = 9.6s. With BASE=2000ms,
// FACTOR=2, CEILING=8000ms a failing stream reopens after 2, 4, 8, 8...
// seconds -- at t = 2, 6, 14, 22, 30, 38, 46, 54s, so 8 reopens in the first
// minute and 7.5/min once saturated.
//
// Against the backend's Stream class (45 opens/min/IP, `stream_rate_limit`
// in settings.py): the reported incident's 5 concurrently-failing streams
// (four `/api/jobs/{id}/stream` plus the resource stream) cost 5 * 8 = 40
// reopens in the first minute and 5 * 7.5 = 37.5/min after -- under budget.
// The theoretical ceiling of 11 streams (`max_user_active_jobs` (10) plus
// the resource stream) would cost 88 and 82.5/min, over it: at that extreme
// the server's limiter answers the excess with 429, which each stream
// counts as one more failed attempt and backs off from, so the limiter --
// not this client pacing -- holds the budget. That is the accepted price of
// a take arriving within seconds of the network's return. The resource
// stream's own per-user budget (`resource_event_stream_open_limit`, 12/min)
// takes one tab's 8 first-minute reopens plus its regular 60s
// reauthentication reopen. Do not lower BASE below 2000ms: the first-minute
// ramp, not the saturated rate, is what overran the budget at BASE=1000ms.
export const SSE_RECONNECT_BASE_DELAY_MS = 2000;
export const SSE_RECONNECT_BACKOFF_FACTOR = 2;
export const SSE_RECONNECT_MAX_DELAY_MS = 8000;
export const SSE_RECONNECT_JITTER_RATIO = 0.2;
export const SSE_IMMEDIATE_REOPEN_MIN_GAP_MS = 2000;
