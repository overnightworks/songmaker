import type { JobItem } from '#lib/api/types.ts';

export const JOB_TYPE_GENERATE = 'generate';
export const JOB_TYPE_SCORE = 'score';
export const JOB_TYPE_COVER = 'cover';

// A job stream reads the job over REST after this many consecutive connection
// errors. At the delays in `constants/sse-reconnect.ts` that is about three
// minutes. Only timed retries that fail while the page is online count: a
// reopen on returning to the app and a failure while offline never spend one,
// so neither frequent returns nor an outage drops a running take.
export const JOB_STREAM_MAX_CONNECTION_ERRORS = 25;
// How long a finished generate job keeps its card, counted only while the page
// is online, when the song refresh its end asked for has not run:
// offline the card stays however long the network is away; back online this is
// long enough for the page to resync, short enough that a refresh that never
// runs does not leave a card behind.
export const GENERATE_TAKE_ARRIVAL_WAIT_MS = 30_000;
export const GENERATION_PHASE_LABELS: Record<NonNullable<JobItem['phase']>, string> = {
	loading_model: 'Loading model…',
	writing: 'Writing',
	rendering: 'Rendering',
	saving_take: 'Saving take'
};
