export const APP_NAME = 'Hallucinai';

export const DIALOG_CANCEL_LABEL = 'Cancel';
export const DIALOG_CONFIRM_LABEL = 'Confirm';

export const EXPIRY_WARN_DAYS = 3;

export const LORA_POLL_INTERVAL_MS = 5000;

export const LORA_MIN_SAMPLES_FOR_TRAINING = 3;

export const LORA_MAX_SAMPLES = 20;

export const LORA_AUDIO_EXTENSIONS = ['.wav', '.mp3', '.flac'] as const;

export const QUEUE_STREAM_EMPTY_POOL_PREFIX = 'No playable takes in pool';

export const LIBRARY_QUEUE_LOADING_TITLE = 'Loading';
export const LIBRARY_QUEUE_EMPTY_TITLE = 'No takes';
export const LIBRARY_QUEUE_RETRY_DETAIL = 'Press play to retry';
export const LIBRARY_QUEUE_PLAY_DETAIL = 'Play';
export const SHUFFLE_SCOPE_PLAYLIST = 'this playlist';
export const SHUFFLE_SCOPE_ALBUM = 'this album';
export const SHUFFLE_SCOPE_LIBRARY = 'all albums';

export const QUEUE_STREAM_UNPLAYABLE_START_DETAIL = 'Requested take is not playable';

export const QUEUE_TAKE_MISSING_TOAST = 'This take is not in the queue';

export const ALBUM_ROW_NO_TAKE_TOAST = 'No take to play for this song yet';
export const ALBUM_ROW_ARCHIVED_ONLY_TOAST = 'No playable take — all takes are archived';

// A collection row announces the action its click performs, then the title:
// "Play Tide", "Pause Tide". Every surface that renders such a row, and every
// flow that finds one by name, builds the label here.
export const COLLECTION_ROW_PLAY_ACTION = 'Play';
export const COLLECTION_ROW_PAUSE_ACTION = 'Pause';

export function collectionRowPlayLabel(title: string): string {
	return `${COLLECTION_ROW_PLAY_ACTION} ${title}`;
}

export function collectionRowPauseLabel(title: string): string {
	return `${COLLECTION_ROW_PAUSE_ACTION} ${title}`;
}

// The transport's play button is named after the state its click leaves:
// "Pause" while audio is really playing, "Retry" once it errored, otherwise
// "Play". A flow reads the name to tell a sounding take from a dead one.
export const TRANSPORT_PLAY_LABEL = 'Play';
export const TRANSPORT_PAUSE_LABEL = 'Pause';
export const TRANSPORT_RETRY_LABEL = 'Retry';

export const NOW_PLAYING_LABEL = 'Now Playing';
export const NOW_PLAYING_NO_LYRICS = 'No lyrics for this take';
export const NOW_PLAYING_GO_TO_SONG = 'Go to song';
export const NOW_PLAYING_CLOSE = 'Close';
export const NOW_PLAYING_TAKE_PREFIX = 'Take';

export const TAKE_AGAIN_LABEL = 'Generate again';
export const TAKE_USE_AS_REFERENCE_LABEL = 'Use as reference';
export const TAKE_PICK_LABEL = 'Pick';
export const TAKE_KEEP_LABEL = 'Keep';
export const TAKE_OVERFLOW_LABEL = 'More';
export const TAKE_SHARE_LABEL = 'Share take';
export const TAKE_UNSHARE_LABEL = 'Unshare';
export const TAKE_COPY_LINK_LABEL = 'Copy link';
export const TAKE_PIN_SEED_LABEL = 'Pin seed';
export const TAKE_PLAYLIST_LABEL = 'Add to playlist';
export const TAKE_REMASTER_LABEL = 'Remaster';
export const TAKE_RESTORE_LABEL = 'Restore';
export const TAKE_ARCHIVED_TITLE = 'Archived take — restore to play';
export const TAKE_DELETE_LABEL = 'Delete';
export const TAKE_SCORE_LABEL = 'Score';
export const TAKE_SCORING_LABEL = 'Scoring...';
export const TAKES_EMPTY = 'No takes yet';
export const TAKES_LOADING = 'Loading takes…';
export const TAKES_ERROR = 'Failed to load takes';
// {version} is replaced with the version number Generate would create next.
export const TAKES_DRAFT_BANNER_TEMPLATE = 'Draft — unsaved changes. Generate creates v{version}.';
export const TAKES_GENERATING_LABEL = 'generating';
export const TAKES_MOBILE_HINT = 'Tap play → details in Now Playing';
export const TAKES_DELETE_VERSION_LABEL = 'Delete version…';

export const EDITOR_TABS_LABEL = 'Editor tabs';
export const EDITOR_TAB_WRITE_LABEL = 'Write';
export const EDITOR_TAB_TAKES_LABEL = 'Takes';
export const EDITOR_VIEWS_LABEL = 'Editor views';
export const EDITOR_VIEW_COWRITER_LABEL = 'Co-Writer';
export const EDITOR_VIEW_RECIPE_LABEL = 'Recipe';
export const EDITOR_GENERATE_LABEL = 'Generate';
export const EDITOR_GENERATING_LABEL = 'Generating...';
export const EDITOR_QUEUED_LABEL = 'Queued...';
export const EDITOR_NO_MODELS_WARNING = 'No models enabled. Ask admin to enable one.';
export const EDITOR_SELECT_MODEL_TITLE = 'Select a model first';
export const EDITOR_MISSING_CONTENT_TITLE = 'Add lyrics and style prompt first';
export const EDITOR_QUEUE_BUSY_TITLE = 'System busy — submit may be rejected';
export const EDITOR_CHAT_LABEL = 'Chat';
export const EDITOR_LYRICS_LABEL = 'Lyrics';
export const EDITOR_STYLE_LABEL = 'Style';
export const EDITOR_STYLE_PROMPT_LABEL = 'Style Prompt';
export const EDITOR_UNSAVED_TITLE = 'Unsaved changes';
export const EDITOR_UNSAVED_MESSAGE =
	'Save this draft as a new version before leaving, or discard it?';
export const EDITOR_UNSAVED_SAVE_LABEL = 'Save';
export const EDITOR_UNSAVED_DISCARD_LABEL = 'Discard';
export const EDITOR_NETWORK_ERROR = 'Network error. Check connection and retry.';

export const SONG_MENU_SAVE_VERSION_LABEL = 'Save version';
export const SONG_MENU_SHARE_LABEL = 'Share song';
export const SONG_MENU_RENAME_LABEL = 'Rename';
export const SONG_MENU_ADD_TO_PLAYLIST_LABEL = 'Add to playlist';
export const SONG_MENU_DELETE_LABEL = 'Delete song';

export const RECIPE_PANEL_LABEL = 'Recipe';
export const RECIPE_SAVED_HINT = 'Saved with the version. Changes mark the draft.';
export const RECIPE_COLLAPSE_LABEL = 'Collapse';
export const RECIPE_GROUP_SOUND_LABEL = 'Sound';
export const RECIPE_GROUP_TEXT_LABEL = 'Text';
export const RECIPE_GROUP_REPRODUCE_LABEL = 'Reproduce';
export const RECIPE_PRESET_LABEL = 'Preset';
export const RECIPE_PRESET_DEFAULT_OPTION = 'Default';
export const RECIPE_SAVE_AS_PRESET_LABEL = 'Save as preset';
export const RECIPE_MANAGE_PRESETS_LABEL = 'Manage in Settings → Generation';
export const RECIPE_SAVE_AS_PRESET_NAME_PROMPT = 'Name this preset';
export const RECIPE_SEED_RANDOM_LABEL = 'Random';
export const RECIPE_SEED_PINNED_LABEL = 'Pinned';
export const RECIPE_REPAINT_OFF_LABEL = 'Off';
export const RECIPE_SOURCE_LABEL = 'Source';
export const RECIPE_USES_LABEL = 'Generate uses this recipe';
// A freshly pinned seed with no prior value starts at 0 rather than a random
// number, so pinning is deterministic and immediately editable.
export const RECIPE_DEFAULT_PINNED_SEED = 0;
// Shown instead of the full panel when Co-Writer and Recipe are both open, so
// the chat column stays above the fold; "Edit" reveals the full panel.
export const RECIPE_STACKED_LABEL = 'Recipe summary';
export const RECIPE_STACKED_EDIT_LABEL = 'Edit';

export const LIBRARY_QUERY_REQUIRED = 'Search query is required';
export const LIBRARY_SEARCH_PLACEHOLDER = 'Search albums and songs';
export const LIBRARY_PLAYLISTS_SEARCH_PLACEHOLDER = 'Search playlists';
export const LIBRARY_SHARED_SEARCH_PLACEHOLDER = 'Search shared';
export const LIBRARY_SEARCH_EMPTY = 'No albums or songs match';
export const LIBRARY_PLAYLISTS_SEARCH_EMPTY = 'No playlists match';
export const LIBRARY_SHARED_SEARCH_EMPTY = 'No shared items match';
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
// A narrow desktop window is compact but still has a mouse — touch-only copy
// ("Tap play") asks this instead of the compact query.
export const COARSE_POINTER_MEDIA = '(any-pointer: coarse)';
export const LIBRARY_NARROW_MEDIA = `(max-width: ${COMPACT_LAYOUT_MAX_PX}px)`;
export const LIBRARY_ALBUM_CARD_TRACK_MAX_PX = 208;
export const ALBUM_ART_EMPTY_INITIALS = '?';
export const ALBUM_ART_INITIAL_COUNT = 2;
export const ALBUM_COVER_ACCEPT = 'image/jpeg,image/png';
export const ALBUM_COVER_ALT_TYPE = 'Album';
export const ALBUM_COVER_UPLOAD_LABEL = 'Upload album cover';
export const ALBUM_COVER_REPLACE_LABEL = 'Replace album cover';
export const ALBUM_COVER_REMOVE_LABEL = 'Remove album cover';
export const SONG_COVER_ALT_TYPE = 'Song';
export const SONG_COVER_UPLOAD_LABEL = 'Upload song cover';
export const SONG_COVER_REPLACE_LABEL = 'Replace song cover';
export const SONG_COVER_REMOVE_LABEL = 'Remove song cover';
export const SONG_PREVIOUS_LABEL = 'Previous song';
export const SONG_NEXT_LABEL = 'Next song';

export const SETTINGS_NAV_LABEL = 'Settings sections';
export const ADMIN_TABS_LABEL = 'Admin sections';

export const COLLECTION_MENU_LABEL = 'More';
export const COLLECTION_MENU_CLOSE_LABEL = 'Close menu';
export const COLLECTION_MENU_SHARE_PREFIX = 'Share';
export const COLLECTION_MENU_DELETE_PREFIX = 'Delete';
export const COLLECTION_MENU_COVER_LABEL = 'Cover…';
export const COLLECTION_MENU_COVER_REMOVE_LABEL = 'Remove cover';
export const COLLECTION_MENU_RENAME_LABEL = 'Rename';
export const COLLECTION_MENU_ADD_TO_PLAYLIST_LABEL = 'Add to playlist';
export const COLLECTION_MENU_SAVE_OFFLINE_LABEL = 'Save offline';
export const COLLECTION_MENU_SAVE_OFFLINE_SAVING_LABEL = 'Saving…';
export const COLLECTION_MENU_SAVE_OFFLINE_REMOVE_LABEL = 'Saved offline · Remove';
// The album header's create action. On a narrow header the glyph stands
// alone — the word would otherwise squeeze the album title out of the row.
export const ALBUM_ADD_SONG_LABEL = '+ Song';
export const ALBUM_ADD_SONG_GLYPH = '+';

export const ALBUM_SUBTITLE_LABEL = 'Album subtitle';
export const ALBUM_SUBTITLE_PLACEHOLDER = 'Add subtitle';
export const ALBUM_YEAR_LABEL = 'Album year';
export const ALBUM_YEAR_PLACEHOLDER = 'Add year';
export const ALBUM_YEAR_MIN = 1900;
export const ALBUM_YEAR_MAX = 2100;

export const RAIL_LIBRARY_LABEL = 'Library';
export const RAIL_SETTINGS_LABEL = 'Settings';
export const RAIL_SUMMARY_LOADING = '…';
// The drawer the compact shell puts the rail in — its accessible name, which
// is how a flow scopes to it while another overlay may be open.
export const RAIL_DRAWER_LABEL = 'Navigation';
export const RAIL_DRAWER_OPEN_LABEL = 'Open menu';
export const RAIL_DRAWER_CLOSE_LABEL = 'Close menu';
export const RAIL_CONTEXT_NO_TAKES = '—';
export const RAIL_CONTEXT_EMPTY = 'No album or playlist open — its tracks appear here.';

export const LIBRARY_FILTERS = ['albums', 'playlists', 'shared'] as const;
export type LibraryFilter = (typeof LIBRARY_FILTERS)[number];
export const LIBRARY_DEFAULT_FILTER: LibraryFilter = 'albums';
export const LIBRARY_FILTER_LABELS: Record<LibraryFilter, string> = {
	albums: 'Albums',
	playlists: 'Playlists',
	shared: 'Shared'
};
export const LIBRARY_FILTER_NAV_LABEL = 'Library filter';
export const LIBRARY_HISTORY_KIND = 'songmaker' as const;
export const LIBRARY_ALBUMS_EMPTY = 'No albums yet';
export const LIBRARY_ALBUMS_LOADING = 'Loading albums…';
export const LIBRARY_PLAYLISTS_EMPTY = 'No playlists yet';
export const LIBRARY_PLAYLISTS_LOADING = 'Loading playlists…';
export const LIBRARY_PLAYLISTS_ERROR = 'Failed to load playlists';
export const PLAYLIST_ENTRY_OVERFLOW_LABEL = 'More';

export function playlistEntryOverflowLabel(songTitle: string): string {
	return `${PLAYLIST_ENTRY_OVERFLOW_LABEL} for ${songTitle}`;
}
export const PLAYLIST_ENTRY_OPEN_SONG_LABEL = 'Open song in editor';
export const PLAYLIST_ENTRY_MOVE_UP_LABEL = 'Move up';
export const PLAYLIST_ENTRY_MOVE_DOWN_LABEL = 'Move down';
export const PLAYLIST_ENTRY_REMOVE_LABEL = 'Remove from playlist';
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
export const LIBRARY_NEW_ALBUM_LABEL = 'New album';

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
