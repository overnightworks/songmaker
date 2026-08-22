export const APP_NAME = 'Hallucinai';

export const EXPIRY_WARN_DAYS = 3;

export const LORA_POLL_INTERVAL_MS = 5000;

export const LORA_MIN_SAMPLES_FOR_TRAINING = 3;

export const LORA_MAX_SAMPLES = 20;

export const LORA_AUDIO_EXTENSIONS = ['.wav', '.mp3', '.flac'] as const;

export const QUEUE_STREAM_EMPTY_POOL_PREFIX = 'No playable takes in pool';

export const LIBRARY_QUEUE_LOADING_TITLE = 'Loading';
export const LIBRARY_QUEUE_EMPTY_TITLE = 'No takes';
export const LIBRARY_QUEUE_RETRY_DETAIL = 'Tap play';
export const LIBRARY_QUEUE_PLAY_DETAIL = 'Play';
export const SHUFFLE_SCOPE_PLAYLIST = 'this playlist';
export const SHUFFLE_SCOPE_ALBUM = 'this album';
export const SHUFFLE_SCOPE_LIBRARY = 'all albums';
export const LIBRARY_POOL_HELP =
	'Mix: Picks and Keeps. Picks: the album take. Keeps: favorites, more than one per song. All: every playable take.';
export const LIBRARY_POOL_HELP_LABEL = 'What Mix Picks Keeps All mean';

export const QUEUE_STREAM_UNPLAYABLE_START_DETAIL = 'Requested take is not playable';

export const QUEUE_TAKE_MISSING_TOAST = 'This take is not in the queue';

export const NOW_PLAYING_LABEL = 'Now Playing';
export const NOW_PLAYING_NO_LYRICS = 'No lyrics for this take';
export const NOW_PLAYING_GO_TO_SONG = 'Go to song';
export const NOW_PLAYING_CLOSE = 'Close';
export const NOW_PLAYING_TAKE_PREFIX = 'Take';

export const SONG_SURFACE_RECIPE = 'Recipe';
export const SONG_SURFACE_TAKES = 'Takes';
export const SONG_SURFACE_COWRITER = 'Co-Writer';
export const SONG_SURFACE_SWITCH_LABEL = 'Song surfaces';
export const SONG_SPLIT_PANE_MIN_PX = 360;
export const SONG_SPLIT_PANE_GAP_PX = 16;

export function canSplitSongPanes(availableWidthPx: number): boolean {
	return availableWidthPx >= SONG_SPLIT_PANE_MIN_PX * 2 + SONG_SPLIT_PANE_GAP_PX;
}

export const TAKE_AGAIN_LABEL = 'Again';
export const TAKE_REPAINT_LABEL = 'Repaint';
export const TAKE_AUDIO_COVER_LABEL = 'Audio cover';
export const TAKE_PICK_LABEL = 'Pick';
export const TAKE_KEEP_LABEL = 'Keep';
export const TAKE_OVERFLOW_LABEL = 'More';
export const TAKE_SHARE_LABEL = 'Share';
export const TAKE_UNSHARE_LABEL = 'Unshare';
export const TAKE_COPY_LINK_LABEL = 'Copy link';
export const TAKE_PLAYLIST_LABEL = 'Playlist';
export const TAKE_REMASTER_LABEL = 'Remaster';
export const TAKE_RESTORE_LABEL = 'Restore';
export const TAKE_DELETE_LABEL = 'Delete';
export const TAKE_SCORE_LABEL = 'Score';
export const TAKE_SCORING_LABEL = 'Scoring...';
export const TAKES_EMPTY = 'No takes yet';
export const TAKES_LOADING = 'Loading takes…';
export const TAKES_ERROR = 'Failed to load takes';
export const TAKE_INSPECTOR_CLOSE = 'Close';
export const TAKE_FROM_RECIPE_PREFIX = 'from Recipe';

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

export const COMPACT_LAYOUT_MAX_PX = 768;
export const COMPACT_LAYOUT_MEDIA = `(max-width: ${COMPACT_LAYOUT_MAX_PX}px), (any-pointer: coarse)`;
export const LIBRARY_NARROW_MEDIA = `(max-width: ${COMPACT_LAYOUT_MAX_PX}px)`;
export const LIBRARY_ALBUM_CARD_TRACK_MAX_PX = 208;
export const ALBUM_ART_EMPTY_INITIALS = '?';
export const ALBUM_ART_INITIAL_COUNT = 2;
export const ALBUM_COVER_ACCEPT = 'image/jpeg,image/png';
export const ALBUM_COVER_ALT_TYPE = 'Album';
export const PLAYLIST_COVER_ALT_TYPE = 'Playlist';
export const ALBUM_COVER_UPLOAD_LABEL = 'Upload album cover';
export const ALBUM_COVER_REPLACE_LABEL = 'Replace album cover';
export const ALBUM_COVER_REMOVE_LABEL = 'Remove album cover';
export const SONG_COVER_ALT_TYPE = 'Song';
export const SONG_COVER_UPLOAD_LABEL = 'Upload song cover';
export const SONG_COVER_REPLACE_LABEL = 'Replace song cover';
export const SONG_COVER_REMOVE_LABEL = 'Remove song cover';
export const LIBRARY_KEEP_BROWSE_CLASS = 'keep-browse';
export const LIBRARY_SONG_WORKSPACE_AREAS = 'nav browse detail';
export const LIBRARY_DETAIL_WORKSPACE_AREAS = 'nav detail';
export const LIBRARY_BROWSE_WORKSPACE_AREAS = 'nav browse';
export const SONG_PREVIOUS_LABEL = 'Previous song';
export const SONG_NEXT_LABEL = 'Next song';

export const SETTINGS_NAV_LABEL = 'Settings sections';
export const ADMIN_TABS_LABEL = 'Admin sections';

export const LIBRARY_SECTIONS = ['albums', 'playlists'] as const;
export type LibrarySection = (typeof LIBRARY_SECTIONS)[number];
export const LIBRARY_DEFAULT_SECTION: LibrarySection = 'albums';
export const LIBRARY_SECTION_LABELS: Record<LibrarySection, string> = {
	albums: 'Studio',
	playlists: 'Listen'
};
export const LIBRARY_SECTION_NAV_LABEL = 'Library sections';
export const LIBRARY_HISTORY_KIND = 'songmaker' as const;
export const LIBRARY_SHARES_HISTORY_SECTION = 'shared' as const;
export type LibraryHistorySection = LibrarySection | typeof LIBRARY_SHARES_HISTORY_SECTION;
export const LIBRARY_ALBUMS_EMPTY = 'No albums yet';
export const LIBRARY_ALBUMS_LOADING = 'Loading albums…';
export const LIBRARY_LISTEN_EMPTY = 'No albums or playlists';
export const LIBRARY_PLAYLISTS_LOADING = 'Loading playlists…';
export const LIBRARY_PLAYLISTS_ERROR = 'Failed to load playlists';
export const LIBRARY_SHARES_LABEL = 'Shared';
export const LIBRARY_SHARES_COUNT_SEP = ' · ';
export const LIBRARY_SHARED_EMPTY = 'Nothing shared';
export const LIBRARY_SHARED_LOADING = 'Loading shares…';
export const LIBRARY_SHARES_ERROR = 'Failed to load shares';
export const LIBRARY_SHARES_COPY_LABEL = 'Copy link';
export const LIBRARY_SHARES_UNSHARE_LABEL = 'Unshare';
export const LIBRARY_SHARES_OPEN_LABEL = 'Open';
export const LIBRARY_SHARES_UNSHARE_TITLE = 'Unshare';
export const LIBRARY_SHARES_UNSHARE_WARNING = 'The public link will stop working.';
export const LIBRARY_SHARES_ALL_LABEL = 'All';
export const LIBRARY_SHARES_FILTER_LABEL = 'Share type';
export const LIBRARY_SHARES_PAGE_SIZE = 50;
export const LIBRARY_SHARES_TYPES = ['album', 'song', 'generation', 'playlist'] as const;
export type ShareInventoryType = (typeof LIBRARY_SHARES_TYPES)[number];
export const LIBRARY_SHARES_TYPE_LABELS: Record<ShareInventoryType, string> = {
	album: 'Album',
	song: 'Song',
	generation: NOW_PLAYING_TAKE_PREFIX,
	playlist: 'Playlist'
};
export const LIBRARY_SHARES_TYPE_EMPTY: Record<ShareInventoryType, string> = {
	album: 'No shared albums',
	song: 'No shared songs',
	generation: 'No shared takes',
	playlist: 'No shared playlists'
};
export const LIBRARY_NEW_PLAYLIST_LABEL = 'New playlist';
export const LIBRARY_NEW_SONG_LABEL = 'New Song';

export function librarySharesStatusLabel(total: number): string {
	return `${LIBRARY_SHARES_LABEL}${LIBRARY_SHARES_COUNT_SEP}${total}`;
}

export const RESOURCE_EVENT_STREAM_PATH = '/api/resource-events/stream';
export const RESOURCE_EVENT_HELLO = 'hello';
export const RESOURCE_EVENT_RESYNC = 'resync';
export const RESOURCE_EVENT_GENERATION_CREATED = 'generation.created';
export const RESOURCE_SYNC_ERROR = 'Library sync failed';
export const RESOURCE_SYNC_BOOTSTRAP_ERROR_LIMIT = 3;
export const RESOURCE_SYNC_FETCH_CONCURRENCY = 4;
export const RESOURCE_SYNC_VISIBILITY_DEBOUNCE_MS = 250;
export const JOB_TYPE_GENERATE = 'generate';
