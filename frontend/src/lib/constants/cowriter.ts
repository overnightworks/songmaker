export const COWRITER_TURN_TIMEOUT_MS = 600_000;
export const COWRITER_RUNNING_TURN_POLL_MS = 2_000;
export const COWRITER_RUNNING_TURN_POLL_FAILURE_LIMIT = 3;
export const COWRITER_BUSY_WAIT_CEILING_SECONDS = 300;
export const COWRITER_TURN_PATH = '/api/chat/turn';

/** The text a mention of the album or of a version inserts into a message; the co-writer reads it there. */
export const cowriterMentionToken = (
	mention: { type: 'album' } | { type: 'version'; item: { version_number: number } }
): string => (mention.type === 'album' ? '@album' : `@v${mention.item.version_number}`);
