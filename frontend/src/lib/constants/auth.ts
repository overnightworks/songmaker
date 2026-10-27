import { APP_NAME } from '$lib/constants';

// Auth copy kept apart from lib/constants.ts (issue #117).

// The sign-in pages (docs/design/sign-in.html, boards 2-4).
export const SIGNED_OUT_HEADING = 'You are logged out.';
export const SIGN_IN_ACTION_LABEL = 'Log in';
export const NO_ACCESS_HEADING = 'No access';
export const NO_ACCESS_MESSAGE = `You are signed in, but this account has no access to ${APP_NAME}.`;
export const NO_ACCESS_BACK_LABEL = 'Back';
export const SIGN_IN_FAILED_HEADING = 'Login failed';
export const SIGN_IN_FAILED_MESSAGE = 'Sign-in did not work. Please try again.';
export const SIGN_IN_RETRY_LABEL = 'Try again';
// The route a sign-out posts to; the server answers the page that ends the identity provider's session.
export const LOGOUT_ADDRESS = '/auth/logout';

export const AUTH_CHECK_RATE_LIMITED_ERROR =
	'Too many requests. Retry in a moment to check your session.';
export const AUTH_CHECK_SERVER_ERROR = 'Could not verify your session. Retry to try again.';
export const AUTH_CHECK_NETWORK_ERROR = 'Network error. Retry to check your session.';
export const AUTH_CHECK_RETRY_LABEL = 'Retry';

// A session check the server did not answer asks again this often, the same
// cadence the library's return probe keeps, so the app loads within about a
// second of the server's return (#1118).
export { RESOURCE_SYNC_RETURN_PROBE_INTERVAL_MS as AUTH_CHECK_RETURN_PROBE_INTERVAL_MS } from '$lib/constants';
