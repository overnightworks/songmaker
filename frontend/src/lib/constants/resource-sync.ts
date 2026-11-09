export const RESOURCE_EVENT_STREAM_PATH = '/api/resource-events/stream';
export const RESOURCE_EVENT_HELLO = 'hello';
export const RESOURCE_EVENT_RESYNC = 'resync';
export const RESOURCE_EVENT_GENERATION_CREATED = 'generation.created';
export const RESOURCE_SYNC_ERROR = "Couldn't reach your library";
export const RESOURCE_SYNC_BOOTSTRAP_ERROR_LIMIT = 3;
export const RESOURCE_SYNC_FETCH_CONCURRENCY = 4;
export const RESOURCE_SYNC_VISIBILITY_DEBOUNCE_MS = 250;
// While the server cannot be reached, a cheap auth probe asks this often
// whether it is back, so the offline strip goes within ~2s of its return
// rather than after the stream's up-to-10s backoff. Only a request
// the edge answers itself costs anything while the server is down, and the
// first answer ends the probing.
export const RESOURCE_SYNC_RETURN_PROBE_INTERVAL_MS = 1000;
export const RESOURCE_SYNC_TRACKED_EVENT_LIMIT = 256;
