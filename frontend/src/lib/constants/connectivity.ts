export const OFFLINE_STRIP_MESSAGE = "You're offline — retrying";

// While the offline strip is not showing, a load that could not reach the
// server runs again on this bounded backoff before its surface names the
// failure with a Retry (connectivity.ts reloadWhileUnreachable).
export const UNREACHABLE_RELOAD_DELAYS_MS: readonly number[] = [2_000, 5_000, 15_000];
