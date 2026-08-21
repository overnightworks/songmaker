export const APP_NAME = 'Hallucinai';

export const EXPIRY_WARN_DAYS = 3;

export const LORA_POLL_INTERVAL_MS = 5000;

export const LORA_MIN_SAMPLES_FOR_TRAINING = 3;

export const LORA_MAX_SAMPLES = 20;

export const LORA_AUDIO_EXTENSIONS = ['.wav', '.mp3', '.flac'] as const;

export const QUEUE_STREAM_EMPTY_POOL_PREFIX = 'No playable takes in pool';

export const QUEUE_STREAM_UNPLAYABLE_START_DETAIL = 'Requested take is not playable';

export const QUEUE_TAKE_MISSING_TOAST = 'This take is not in the queue';

export const LIBRARY_QUERY_REQUIRED = 'Search query is required';
export const LIBRARY_SEARCH_PLACEHOLDER = 'Search albums and songs';
export const LIBRARY_SEARCH_EMPTY = 'No albums or songs match';
export const LIBRARY_SEARCH_LOADING = 'Searching…';
export const LIBRARY_SEARCH_ERROR = 'Search failed';
export const LIBRARY_RETRY_LABEL = 'Retry';
export const LIBRARY_LOAD_MORE = 'Load more';
export const LIBRARY_SEARCH_DEBOUNCE_MS = 200;
export const LIBRARY_ALBUM_PAGE_SIZE = 50;
export const LIBRARY_SONG_PAGE_SIZE = 200;
export const LIBRARY_SEARCH_PAGE_SIZE = 50;

export const HITBOX_FREQUENT_PX = 44;
export const HITBOX_COMPACT_PX = 24;

export const LIBRARY_SECTIONS = ['albums', 'playlists', 'shared'] as const;
export type LibrarySection = (typeof LIBRARY_SECTIONS)[number];
export const LIBRARY_DEFAULT_SECTION: LibrarySection = 'albums';
export const LIBRARY_SECTION_LABELS: Record<LibrarySection, string> = {
	albums: 'Albums',
	playlists: 'Playlists',
	shared: 'Shared'
};
export const LIBRARY_SECTION_NAV_LABEL = 'Library sections';
export const LIBRARY_HISTORY_KIND = 'songmaker' as const;
export const LIBRARY_ALBUMS_EMPTY = 'No albums yet';
export const LIBRARY_ALBUMS_LOADING = 'Loading albums…';
export const LIBRARY_PLAYLISTS_EMPTY = 'No playlists';
export const LIBRARY_PLAYLISTS_LOADING = 'Loading playlists…';
export const LIBRARY_PLAYLISTS_ERROR = 'Failed to load playlists';
export const LIBRARY_SHARED_EMPTY = 'Nothing shared';
export const LIBRARY_SHARED_LOADING = 'Loading shared…';
export const LIBRARY_NEW_PLAYLIST_LABEL = 'New playlist';
export const LIBRARY_NEW_SONG_LABEL = 'New Song';

export const RESOURCE_EVENTS_PATH = '/api/resource-events/stream';
export const RESOURCE_SYNC_ERROR = 'Could not sync new takes';
export const RESOURCE_SYNC_RECONNECT_BASE_MS = 500;
export const RESOURCE_SYNC_RECONNECT_MAX_MS = 15000;
