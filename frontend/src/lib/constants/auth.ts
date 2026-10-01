import { RESOURCE_SYNC_RETURN_PROBE_INTERVAL_MS } from '$lib/constants';

// Auth-check failure copy (issue #117). Kept separate from lib/constants.ts,
// which another lane owns for the same landing window.

export const AUTH_SESSION_EXPIRED_MESSAGE = 'Your session has expired.';
// The server's 401 detail for a cookie whose session no longer exists
// (`webauth.dependencies.SESSION_EXPIRED_DETAIL`); a request without a session
// cookie is refused with a different detail (#1215).
export const AUTH_SESSION_EXPIRED_DETAIL = 'Session expired';
export const AUTH_ACCOUNT_DISABLED_MESSAGE = 'Your account has been disabled.';

export const AUTH_CHECK_RATE_LIMITED_ERROR =
	'Too many requests. Retry in a moment to check your session.';
export const AUTH_CHECK_SERVER_ERROR = 'Could not verify your session. Retry to try again.';
export const AUTH_CHECK_NETWORK_ERROR = 'Network error. Retry to check your session.';
export const AUTH_CHECK_RETRY_LABEL = 'Retry';

// A session check the server did not answer asks again this often, the same
// cadence the library's return probe keeps, so the app loads within about a
// second of the server's return (#1118).
export const AUTH_CHECK_RETURN_PROBE_INTERVAL_MS = RESOURCE_SYNC_RETURN_PROBE_INTERVAL_MS;
