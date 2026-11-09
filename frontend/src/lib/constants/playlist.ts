// The Playlists page: its head, which search names it by too, and the
// count beside it, read as one heading ('Playlists · 3').
export const PLAYLISTS_PAGE_LABEL = 'Playlists';
export const PLAYLISTS_WALL_ORDER_GROUP_LABEL = 'Sort playlists';
export const PLAYLISTS_WALL_EMPTY = 'No playlists yet. + New on Home makes one.';
const PLAYLIST_ENTRY_OVERFLOW_LABEL = 'More';

export function playlistEntryOverflowLabel(songTitle: string): string {
	return `${PLAYLIST_ENTRY_OVERFLOW_LABEL} for ${songTitle}`;
}
export const PLAYLIST_ENTRY_MOVE_UP_LABEL = 'Move up';
export const PLAYLIST_ENTRY_MOVE_DOWN_LABEL = 'Move down';
export const PLAYLIST_ENTRY_REMOVE_LABEL = 'Remove from playlist';
export const LIBRARY_PLAYLISTS_LOADING = 'Loading playlists…';
export const LIBRARY_PLAYLISTS_ERROR = 'Failed to load playlists';
