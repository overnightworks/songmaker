import type { JobItem } from '#lib/api/types.ts';
import { VERSIONS_SHEET_LABEL } from '#lib/constants/versions.ts';

export const APP_NAME = 'Hallucinai';
export const APP_REPOSITORY_URL = 'https://github.com/overnightworks/songmaker';

export const API_ERROR_GENERIC_MESSAGE = 'Something went wrong. Try again.';

export const DIALOG_CANCEL_LABEL = 'Cancel';
export const DIALOG_CONFIRM_LABEL = 'Confirm';

export const EXPIRY_WARN_DAYS = 3;

export const SONG_LINK_NOT_FOUND_TOAST = 'Song not found — it may have been deleted';

export const NOW_PLAYING_LABEL = 'Now Playing';

// The phone's mini player opens Now Playing from its cover and title. The
// name starts with the visible title so a voice command naming what is on
// screen reaches it (WCAG 2.5.3), then says what the tap opens.
export function openNowPlayingLabel(songTitle: string): string {
	return `${songTitle} — open ${NOW_PLAYING_LABEL}`;
}
// Swiping the mini player up opens Now Playing once the finger has risen
// this far, and further up than sideways; anything less is a tap or a slip.
export const NOW_PLAYING_SWIPE_RISE_PX = 40;
export const REDUCED_MOTION_MEDIA = '(prefers-reduced-motion: reduce)';
// Beside play's exact centre line a phone narrower than 360px leaves the
// mini player's left side too little room for cover and title, so the cover
// goes and the title takes the whole side. The query stays on max-width, like
// every other breakpoint, because iOS Safari before 16.4 ignores range syntax;
// the fraction also drops the cover on a sub-pixel viewport just under 360px.
const MINI_PLAYER_WITHOUT_COVER_MAX_VIEWPORT_PX = 359.98;
export const MINI_PLAYER_WITHOUT_COVER_MEDIA = `(max-width: ${MINI_PLAYER_WITHOUT_COVER_MAX_VIEWPORT_PX}px)`;

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
export const EDITOR_QUEUED_LABEL = 'Queued';
export const MODEL_REGISTRY_LOAD_FAILED = 'Cannot reach the registry API.';
export const TAKES_MOBILE_HINT = 'Tap play → details in Now Playing';

export const EDITOR_TAB_TAKES_LABEL = 'Takes';
export const EDITOR_TAB_EDIT_LABEL = 'Edit';
export const EDITOR_TABS_LABEL = 'Editor tabs';

export const PLACE_LINE_SEPARATOR = ' · ';
export const EDITOR_VIEW_COWRITER_LABEL = 'Co-writer';

export const EDITOR_GENERATE_LABEL = 'Generate';
export const TAKES_EMPTY = `No takes yet · ${EDITOR_GENERATE_LABEL} makes the first`;
export const EDITOR_GENERATE_QUEUED_TEMPLATE = `${EDITOR_QUEUED_LABEL} #{position}`;
export const EDITOR_GENERATE_TAKE_TEMPLATE = 'Take {index} of {count}';
export const EDITOR_OPEN_WORKER_POOL_LABEL = 'Open worker pool';

export const EDITOR_GENERATE_CANCEL_LABEL = 'Cancel generation';
// Offline a running take cannot report anything (#1039 O2): it says so and
// keeps the last progress it saw, instead of a percent and time that stand still.
export const EDITOR_GENERATE_RECONNECTING_LABEL = 'Reconnecting…';
export const EDITOR_GENERATE_LAST_SEEN_TEMPLATE = 'last seen at {percent}%';
export const EDITOR_GENERATE_CANCEL_OFFLINE_LABEL = 'Cancel generation (unavailable while offline)';
export const EDITOR_GENERATE_LAST_SEEN_PROGRESS_LABEL = 'Last known progress';
export const EDITOR_GENERATE_CANCEL_FAILED = 'Could not cancel generation';
export const EDITOR_SAVE_LABEL = 'Save';
export const EDITOR_SAVE_ACCESSIBLE_LABEL = 'Save changes';
export const EDITOR_GENERATING_LABEL = 'Generating...';
export const GENERATION_PHASE_LABELS: Record<NonNullable<JobItem['phase']>, string> = {
	loading_model: 'Loading model…',
	writing: 'Writing',
	rendering: 'Rendering',
	saving_take: 'Saving take'
};
export const EDITOR_NO_MODELS_WARNING = 'No models enabled. Ask admin to enable one.';
export const EDITOR_SELECT_MODEL_TITLE = 'Select a model first';
export const EDITOR_MISSING_CONTENT_TITLE = 'Add lyrics and style prompt first';
export const EDITOR_LYRICS_LABEL = 'Lyrics';
export const EDITOR_STYLE_PROMPT_LABEL = 'Style Prompt';
export const EDITOR_UNSAVED_TITLE = 'Unsaved changes';
export const EDITOR_UNSAVED_MESSAGE =
	'Save this draft as a new version before leaving, or discard it?';
export const EDITOR_UNSAVED_SAVE_LABEL = 'Save';
export const EDITOR_UNSAVED_DISCARD_LABEL = 'Discard';
export const EDITOR_SAVE_FAILED = 'Save failed';
const VERSION_CHIP_DRAFT_LABEL = 'draft';
export const TOAST_UNDO_LABEL = 'Undo';

export function versionLabel(versionNumber: number): string {
	return `v${versionNumber}`;
}

export function versionChipLabel(versionNumber: number, dirty: boolean): string {
	const version = versionLabel(versionNumber);
	return dirty ? `${version} · ${VERSION_CHIP_DRAFT_LABEL}` : version;
}

export function versionsChipAccessibleLabel(chipLabel: string): string {
	return `${VERSIONS_SHEET_LABEL}: ${chipLabel}`;
}

export function versionTakesLabel(count: number): string {
	if (count === 0) return 'no takes';
	return `${count} take${count === 1 ? '' : 's'}`;
}

export function versionDeleteLabel(versionNumber: number): string {
	return `Delete ${versionLabel(versionNumber)}`;
}

export function versionDeleteTitle(versionNumber: number, takeCount: number): string {
	const version = versionLabel(versionNumber);
	if (takeCount === 0) return `Delete ${version}?`;
	return `Delete ${version} and its ${versionTakesLabel(takeCount)}?`;
}

export function versionDeletePickWarning(takeCount: number): string {
	return takeCount === 1 ? 'It is the album pick.' : 'The album pick is one of them.';
}

export function versionDeleteReplacedBy(versionNumber: number): string {
	return `Its lyrics leave the editor; ${versionLabel(versionNumber)} replaces them.`;
}

export function versionDeleteLoadedDraftGoes(loadedFrom: number): string {
	return `The draft loaded from ${versionLabel(loadedFrom)} goes too.`;
}

export function versionDeleteLoadedDraftReplacedBy(loadedFrom: number, replacedBy: number): string {
	return `The draft loaded from ${versionLabel(loadedFrom)} leaves the editor; ${versionLabel(replacedBy)} replaces it.`;
}

export function versionLoadedFromLabel(versionNumber: number): string {
	return `Loaded from ${versionLabel(versionNumber)}`;
}

export function versionAlreadyTheDraftLabel(versionNumber: number): string {
	return `${versionLabel(versionNumber)} is already the draft`;
}

export function versionLoadedToastLabel(versionNumber: number): string {
	return `${versionLabel(versionNumber)} loaded`;
}

export function versionReplaceDraftMessage(versionNumber: number): string {
	return `Your draft has changes that are not in any version. Loading ${versionLabel(versionNumber)} replaces them. You can undo right after.`;
}

export const SONG_SHARE_LABEL = 'Share song';
export const SONG_TITLE_LABEL = 'Song title';
export const SONG_MENU_LABEL = 'Song menu';
export const SONG_MENU_SAVE_LABEL = 'Save version';
export const SONG_MENU_RENAME_LABEL = 'Rename';
export const SONG_MENU_ADD_TO_PLAYLIST_LABEL = 'Add to playlist';
export const SONG_MENU_DELETE_LABEL = 'Delete song';
export const SONG_MENU_MOVE_LABEL = 'Move';
export const SONG_MOVE_HEADING = 'Move to';
export const SONG_MOVE_BACK_LABEL = 'Back to song menu';
export const SONG_MOVE_FILTER_LABEL = 'Filter albums';
export const SONG_MOVE_FILTER_PLACEHOLDER = 'Filter';
export const SONG_MOVE_LOADING_LABEL = 'Looking…';
export const SONG_MOVE_NO_OTHER_ALBUM = 'No other album';
export const SONG_MOVE_NO_MATCH = 'No album matches';
export const SONG_MOVE_ALBUM_GONE = 'album gone';
export const SONG_MOVE_NO_CONNECTION = 'no connection';
export const SONG_MOVE_FAILED_REASON = 'something went wrong';
export const songMoveFailedLine = (reason: string) => `Not moved · ${reason}`;
export const SONG_MOVE_SHARED_TITLE = 'Move to a shared album?';
export function songMoveSharedMessage(songTitle: string, albumTitle: string): string {
	return `${songTitle} appears on ${albumTitle}'s public page`;
}

export function songMovedToastLabel(albumTitle: string): string {
	return `Moved to ${albumTitle}`;
}

export const LIBRARY_QUERY_REQUIRED = 'Search query is required';
export const SEARCH_OPEN_LABEL = 'Search';
export const LIBRARY_RETRY_LABEL = 'Retry';
export const LIBRARY_SEARCH_DEBOUNCE_MS = 200;
export const LIBRARY_ALBUM_PAGE_SIZE = 50;
export const LIBRARY_SONG_PAGE_SIZE = 200;
// While the offline strip is not showing, a load that could not reach the
// server runs again on this bounded backoff before its surface names the
// failure with a Retry (connectivity.ts reloadWhileUnreachable).
export const UNREACHABLE_RELOAD_DELAYS_MS: readonly number[] = [2_000, 5_000, 15_000];
export const LIBRARY_SEARCH_PAGE_SIZE = 50;

export const HITBOX_FREQUENT_PX = 44;
export const HITBOX_COMPACT_PX = 24;

export const COMPACT_LAYOUT_MAX_PX = 768;
export const COMPACT_LAYOUT_MEDIA = `(max-width: ${COMPACT_LAYOUT_MAX_PX}px), (any-pointer: coarse)`;
// A narrow desktop window is compact but still has a mouse — touch-only copy
// ("Tap play") asks this instead of the compact query.
export const COARSE_POINTER_MEDIA = '(any-pointer: coarse)';
export const LIBRARY_NARROW_MEDIA = `(max-width: ${COMPACT_LAYOUT_MAX_PX}px)`;
export const LIBRARY_ALBUM_CARD_TRACK_MAX_PX = 208;
export const LIBRARY_WALL_ORDERS = ['title', 'played'] as const;
export type LibraryWallOrder = (typeof LIBRARY_WALL_ORDERS)[number];
export const LIBRARY_WALL_ORDER_LABELS: Record<LibraryWallOrder, string> = {
	title: 'A–Z',
	played: 'Last played'
};
export const LIBRARY_PAGE_LABEL = 'Library';
export const LIBRARY_WALL_ORDER_GROUP_LABEL = 'Sort albums';
// Each page's head reads its name and count as one heading ('Library · 12').
export function wallHeadingLabel(pageLabel: string, count: number): string {
	return `${pageLabel} · ${count}`;
}
export const LIBRARY_WALL_EMPTY = 'No albums yet. + New on Home makes one.';
export const LIBRARY_NEW_FACE = 'New';
export const LIBRARY_NEW_MENU_LABEL = 'New album or playlist';
export const LIBRARY_NEW_MENU_CLOSE_LABEL = 'Close New in Library';
export const LIBRARY_NEW_ALBUM_LABEL = 'Album';
export const LIBRARY_NEW_PLAYLIST_LABEL = 'Playlist';

export function newSongCardLabel(albumTitle: string): string {
	return `New song in ${albumTitle}`;
}
// The listen endpoint's own ceiling (PAGE_MAX_LIMIT): Last played reads its places in pages this size.
export const LIBRARY_WALL_PLAYED_PAGE_SIZE = 200;

export function albumCoverSuggestionAlt(title: string): string {
	return `Cover suggestion for ${title}`;
}

export function albumCoverSuggestionPosition(shown: number, count: number): string {
	return `${shown} / ${count}`;
}

export function albumCoverStageLabel(shown: number, count: number): string {
	return `Cover suggestion ${shown} of ${count}`;
}

export function albumCoverSuggestionsLeftToday(used: number, limit: number): string {
	return `${Math.max(0, limit - used)} of ${limit} left today`;
}
export const SONG_COVER_ALT_TYPE = 'Song';
export const SONG_COVER_UPLOAD_LABEL = 'Upload song cover';
export const SONG_COVER_REPLACE_LABEL = 'Replace song cover';
export const SONG_COVER_REMOVE_LABEL = 'Remove song cover';
export const SONG_PREVIOUS_LABEL = 'Previous song';
export const SONG_NEXT_LABEL = 'Next song';

// Every row's PlayingMark reads this, in the rail, the detail views and the shared page.
export const PLAYING_MARK_LABEL = 'Playing';

// A song box's ✎: the box itself plays the song, so the pencil names the place it opens.
export function songEditorOpenLabel(songTitle: string): string {
	return `Open ${songTitle} in the song editor`;
}

export const LIBRARY_HISTORY_KIND = 'songmaker' as const;
export const LIBRARY_ALBUMS_LOADING = 'Loading albums…';
export const LIBRARY_PLAYLISTS_LOADING = 'Loading playlists…';
export const LIBRARY_PLAYLISTS_ERROR = 'Failed to load playlists';
export const LIBRARY_SHARES_COPY_LABEL = 'Copy link';

export const OFFLINE_STRIP_MESSAGE = "You're offline — retrying";
// `EventSource.CLOSED`, spelled out because the jsdom test runtime has no EventSource.
export const EVENT_SOURCE_CLOSED = 2;
