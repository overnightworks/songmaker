const PLAYLIST_ENTRY_OVERFLOW_LABEL = 'More';

export function playlistEntryOverflowLabel(songTitle: string): string {
	return `${PLAYLIST_ENTRY_OVERFLOW_LABEL} for ${songTitle}`;
}
export const PLAYLIST_ENTRY_MOVE_UP_LABEL = 'Move up';
export const PLAYLIST_ENTRY_MOVE_DOWN_LABEL = 'Move down';
export const PLAYLIST_ENTRY_REMOVE_LABEL = 'Remove from playlist';
export const LIBRARY_PLAYLISTS_LOADING = 'Loading playlists…';
export const LIBRARY_PLAYLISTS_ERROR = 'Failed to load playlists';
