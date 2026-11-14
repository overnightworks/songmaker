// The edge's own answers for a server it cannot reach (down or restarting).
// Only these, besides a request the network never carried, read as offline:
// a 429 or a 500 comes from a server that is there.
export const SERVER_UNREACHABLE_STATUSES: ReadonlySet<number> = new Set([502, 503, 504]);
export const SERVER_ERROR_STATUS_FLOOR = 500;
// A rate limit passes, like a failing server: a request it refused can be
// asked again, no sooner than its `Retry-After`.
export const RATE_LIMITED_STATUS = 429;
