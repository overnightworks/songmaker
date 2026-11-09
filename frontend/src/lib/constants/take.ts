import { EDITOR_GENERATE_LABEL } from '#lib/constants/song.ts';

export const TAKE_REPAINT_LABEL = 'Repaint';
export const TAKE_COVER_LABEL = 'Cover';
export const TAKE_PROVENANCE_REPAINT_PREFIX = 'Repaint from';
export const TAKE_PROVENANCE_COVER_PREFIX = 'Cover from';
export const TAKE_PICK_LABEL = 'Pick';
export const TAKE_OVERFLOW_LABEL = 'More';
export const TAKE_SHARE_LABEL = 'Share';
export const TAKE_PLAYLIST_LABEL = 'Add to playlist';
export const TAKE_RESTORE_LABEL = 'Restore';
export const TAKE_ARCHIVED_TITLE = 'Archived take';
export const TAKE_DELETE_LABEL = 'Delete';
export const TAKE_KEEP_LABEL = 'Keep';
export const TAKE_UNKEEP_LABEL = 'Unkeep';
export const TAKE_DELETE_TITLE_TEMPLATE = 'Delete take {number}?';
export const TAKE_DELETE_MESSAGE = 'Audio files will be permanently deleted';
export const TAKE_RESCORE_LABEL = 'Re-score';
export const TAKE_RESCORING_LABEL = 'Re-scoring…';
export const TAKE_RESCORE_QUEUED_TOAST = 'Re-scoring this take…';
export const TAKES_LOADING = 'Loading takes…';
export const TAKES_ERROR = 'Failed to load takes';
export const TAKES_RETRY_LABEL = 'Try again';
export function takesDraftBanner(
	latestVersionNumber: number | null,
	nextVersionNumber: number
): string {
	const differs =
		latestVersionNumber === null ? 'unsaved changes' : `differs from v${latestVersionNumber}`;
	return `Draft — ${differs}. Generate creates v${nextVersionNumber}.`;
}
export const TAKES_MOBILE_HINT = 'Tap play → details in Now Playing';
export const TAKES_EMPTY = `No takes yet · ${EDITOR_GENERATE_LABEL} makes the first`;
