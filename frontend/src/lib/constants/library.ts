import type { Key } from '#lib/words/en.ts';

export const LIBRARY_QUERY_REQUIRED = 'Search query is required';
export const LIBRARY_SEARCH_DEBOUNCE_MS = 200;
export const LIBRARY_ALBUM_PAGE_SIZE = 50;
export const LIBRARY_SONG_PAGE_SIZE = 200;
export const LIBRARY_SEARCH_PAGE_SIZE = 50;

export const LIBRARY_ALBUM_CARD_TRACK_MAX_PX = 208;
export const LIBRARY_WALL_ORDERS = ['title', 'played'] as const;
export type LibraryWallOrder = (typeof LIBRARY_WALL_ORDERS)[number];
export const LIBRARY_WALL_ORDER_KEYS = {
	title: 'libraryWall.orderTitle',
	played: 'libraryWall.orderPlayed'
} as const satisfies Record<LibraryWallOrder, Key>;
export const LIBRARY_NEW_FACE = 'New';
export const LIBRARY_NEW_MENU_LABEL = 'New album or playlist';
export const LIBRARY_NEW_MENU_CLOSE_LABEL = 'Close New in Library';
export const LIBRARY_NEW_ALBUM_LABEL = 'Album';
export const LIBRARY_NEW_PLAYLIST_LABEL = 'Playlist';
// The listen endpoint's own ceiling (PAGE_MAX_LIMIT): Last played reads its places in pages this size.
export const LIBRARY_WALL_PLAYED_PAGE_SIZE = 200;
export const LIBRARY_HISTORY_KIND = 'songmaker' as const;
export const LIBRARY_ALBUMS_LOADING = 'Loading albums…';
export const LIBRARY_SHARES_COPY_LABEL = 'Copy link';
export const LIBRARY_RETRY_LABEL = 'Retry';
