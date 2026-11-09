export const JOB_TYPE_GENERATE = 'generate';
export const JOB_TYPE_SCORE = 'score';
export const JOB_TYPE_COVER = 'cover';

// A job stream stops trusting its stream and reads the job over REST on this
// many consecutive connection errors. Twenty-four retries at the delays in
// `constants/sse-reconnect.ts` (2 + 4 + 8 + 21 * 8s = 182s) keep the roughly three minutes the former 30s
// ceiling gave ten attempts. Only timed retries that fail while the page is
// online count: a reopen on returning to the app never spends one, so
// frequent returns never shorten the three minutes (#1032), nor does a
// failure while offline, so no number of outages drops a running take (#1141).
export const JOB_STREAM_MAX_CONNECTION_ERRORS = 25;
// How long a finished generate job keeps its card, counted only while the page
// is online, when the song refresh its end asked for has not run (#1039 O3):
// offline the card stays however long the network is away; back online this is
// long enough for the page to resync, short enough that a refresh that never
// runs does not leave a card behind.
export const GENERATE_TAKE_ARRIVAL_WAIT_MS = 30_000;
