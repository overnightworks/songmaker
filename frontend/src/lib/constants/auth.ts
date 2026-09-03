// Auth-check failure copy (issue #117). Kept separate from lib/constants.ts,
// which another lane owns for the same landing window.

export const AUTH_SESSION_EXPIRED_MESSAGE = 'Your session has expired.';
export const AUTH_ACCOUNT_DISABLED_MESSAGE = 'Your account has been disabled.';

export const AUTH_CHECK_RATE_LIMITED_ERROR =
	'Too many requests. Retry in a moment to check your session.';
export const AUTH_CHECK_SERVER_ERROR = 'Could not verify your session. Retry to try again.';
export const AUTH_CHECK_NETWORK_ERROR = 'Network error. Retry to check your session.';
export const AUTH_CHECK_RETRY_LABEL = 'Retry';
