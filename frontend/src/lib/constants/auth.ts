// The route a sign-out posts to; the server answers the page that ends the identity provider's session.
export const LOGOUT_ADDRESS = '/auth/logout';

// A session check the server did not answer asks again this often, the same
// cadence the library's return probe keeps, so the app loads within about a
// second of the server's return (#1118).
export { RESOURCE_SYNC_RETURN_PROBE_INTERVAL_MS as AUTH_CHECK_RETURN_PROBE_INTERVAL_MS } from '#lib/constants/resource-sync.ts';

// The server's sign-in start (`GET /login/oidc?next=`) reads the address to
// return to from this param.
export const SIGN_IN_NEXT_PARAM = 'next';
