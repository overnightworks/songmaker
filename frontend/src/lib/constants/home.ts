// Home's head, and what a page's ‹ calls it (#1354 rules 25 and 31).
export const HOME_PAGE_LABEL = 'Home';

export const HOME_WRITE_LABEL = 'Write';
export const HOME_WRITE_EMPTY = 'Songs you work on will appear here.';
export const HOME_WRITE_LOADING = 'Loading Write…';
export const HOME_WRITE_ERROR = 'Could not load Write.';
// The row body and its pencil both open the editor; distinct names keep them apart for a screen reader.
export function homeWriteOpenLabel(songTitle: string): string {
	return `Open song ${songTitle}`;
}
export const HOME_WRITE_WORK_LABELS = {
	created: 'new song',
	lyrics: 'lyrics edited',
	style: 'style edited',
	renamed: 'renamed',
	take: 'new take',
	cowriter: 'co-writer',
	edited: 'edited'
} as const;
export const HOME_LISTEN_LABEL = 'Listen';
export const HOME_LISTEN_LIMIT = 3;
export const HOME_LISTEN_EMPTY = 'Albums and playlists you play will appear here.';
export const HOME_LISTEN_LOADING = 'Loading Listen…';
export const HOME_LISTEN_ERROR = 'Could not load Listen.';
