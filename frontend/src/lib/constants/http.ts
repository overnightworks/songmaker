// The edge's own answers for a server it cannot reach (down or restarting).
// Only these, besides a request the network never carried, read as offline:
// a 429 or a 500 comes from a server that is there.
export const SERVER_UNREACHABLE_STATUSES: ReadonlySet<number> = new Set([502, 503, 504]);
export const SERVER_ERROR_STATUS_FLOOR = 500;
// A rate limit passes, like a failing server: a request it refused can be
// asked again, no sooner than its `Retry-After`.
export const RATE_LIMITED_STATUS = 429;

// Shown when the backend's IP rate limiter (`webauth.middleware.rate_limit`)
// rejects a request with 429 — the budget classes it enforces
// (API/Media/Stream) mean this is now rare during ordinary use, but a
// burst can still happen, and a client that silently stalls reads as
// broken. A few paths already surface their own 429 copy some other way
// and are exempted from this toast — see `RATE_LIMIT_TOAST_EXEMPT_PATHS`
// in `lib/stores/rateLimitNotice.ts` for exactly which, and why.
export const RATE_LIMITED_TOAST_MESSAGE =
	'Too many requests — hang on, it will continue in a moment.';

export const API_ERROR_GENERIC_MESSAGE = 'Something went wrong. Try again.';
