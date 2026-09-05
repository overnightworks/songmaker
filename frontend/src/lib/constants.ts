export const APP_NAME = 'Hallucinai';

export const API_ERROR_GENERIC_MESSAGE = 'Something went wrong. Try again.';

// Cross-file contract: fetch.ts's handleSessionLost writes this param,
// whatever reads it back (the login page) must use the same name.
export const SESSION_LOST_REDIRECT_PARAM = 'redirect';

// The share succeeded server-side even when the follow-up clipboard write
// throws (no permission, no focus, etc.) — that toast must never read as a
// share failure, since the link exists and only the copy step didn't.
export const SHARE_BUTTON_COPY_FAILED_TOAST =
	'Shared — copy the link manually, clipboard write failed';

export const SHARE_LINK_COPIED_TOAST = 'Link copied';
export const SHARE_LINK_COPY_FAILED_TOAST = 'Copy failed';

export const DIALOG_CANCEL_LABEL = 'Cancel';
export const DIALOG_CONFIRM_LABEL = 'Confirm';

export const EXPIRY_WARN_DAYS = 3;

export const LORA_POLL_INTERVAL_MS = 5000;

export const LORA_MIN_SAMPLES_FOR_TRAINING = 3;

export const LORA_MAX_SAMPLES = 20;

export const ADMIN_VOICES_TAB_LABEL = 'Voices';
export const ADMIN_VOICES_HEADING = 'Voice operations';
export const ADMIN_VOICES_LOADING = 'Loading voices...';
export const ADMIN_VOICES_EMPTY = 'No voices have been created.';
export const ADMIN_VOICES_LOAD_FAILED = 'Failed to load voices';
export const ADMIN_VOICES_NAME_LABEL = 'Voice';
export const ADMIN_VOICES_OWNER_LABEL = 'Owner';
export const ADMIN_VOICES_STATUS_LABEL = 'Status';

export const LORA_AUDIO_EXTENSIONS = ['.wav', '.mp3', '.flac'] as const;

export const LORA_OWN_TAKES_LABEL = 'Your takes';
export const LORA_OWN_TAKES_LOADING = 'Loading your takes...';
export const LORA_OWN_TAKES_EMPTY = 'No playable takes yet.';
export const LORA_OWN_TAKES_LOAD_FAILED = 'Could not load takes';
export const LORA_OWN_TAKES_USE = 'Use as sample';
export const LORA_OWN_TAKES_CLOSE = 'Close takes';
export const LORA_OWN_TAKES_OPEN = 'Use a take';
export const LORA_TAKE_LABEL_PREFIX = 'Take';
export const LORA_SAMPLE_ADDING = 'Adding...';
export const LORA_SAMPLE_COPY_FAILED = 'Could not add take';
export const LORA_SAMPLE_UPLOAD_FAILED = 'Upload failed';
export const LORA_CREATE_FAILED = 'Could not create voice';
export const LORA_TRAINING_QUEUED_TOAST = 'Training queued';
export const LORA_TRAINING_STARTING = 'Starting...';
export const LORA_TRAINING_FAILED_LABEL = 'Training failed';
export const LORA_TRAINING_RETRY_LABEL = 'Train again';
export const LORA_TRAINING_START_FAILED = 'Training failed to start';
export const LORA_TRAINING_CANCEL_LABEL = 'Cancel';
export const LORA_TRAINING_CANCELLED = 'Training cancelled';
export const LORA_TRAINING_CANCEL_FAILED = 'Could not cancel training';
export const LORA_TRAINING_PROGRESS_LOAD_FAILED = 'Could not load training progress';
export const LORA_TRAINING_PROGRESS_LABEL = 'Training progress';
export const LORA_TRAINING_STATUS_LABEL = 'Training';
export const LORA_TRAINING_WAITING_LABEL = 'Waiting';
export const LORA_TRAINING_WAITING_DEFAULT_REASON = 'Waiting for the worker.';
export const LORA_TRAINING_QUEUE_POSITION_TEMPLATE = 'Position {position} in the queue';
export const LORA_TRAINING_EPOCH_TEMPLATE = 'Epoch {current} of {total}';
export const LORA_TRAINING_REMAINING_CALCULATING = 'Calculating remaining time...';
export const LORA_TRAINING_REMAINING_TEMPLATE = '~ {time} remaining';

export function loraTrainingQueuePositionLabel(position: number): string {
	return LORA_TRAINING_QUEUE_POSITION_TEMPLATE.replace('{position}', String(position));
}

export function loraTrainingEpochLabel(current: number, total: number): string {
	return LORA_TRAINING_EPOCH_TEMPLATE.replace('{current}', String(current)).replace(
		'{total}',
		String(total)
	);
}

export function loraTrainingRemainingLabel(seconds: number): string {
	const totalMinutes = Math.max(1, Math.ceil(seconds / 60));
	const hours = Math.floor(totalMinutes / 60);
	const minutes = totalMinutes % 60;
	const time = hours > 0 ? `${hours}h ${minutes}m` : `${Math.max(minutes, 1)}m`;
	return LORA_TRAINING_REMAINING_TEMPLATE.replace('{time}', time);
}

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

export const SONG_LINK_NOT_FOUND_TOAST = 'Song not found — it may have been deleted';

// A legacy `/?song=<id>&gen=<id>` link whose take is gone still opens the
// song (issue #284) -- the song is the durable value, and takes are pruned
// by ordinary cleanup, so a dead take is not the same failure a dead song
// is. Falling back silently would still hide a fact the app knows, so this
// says so instead of just landing on the song.
export const LEGACY_TAKE_LINK_NOT_FOUND_TOAST =
	'This take no longer exists — opened the song instead';

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
export const TAKE_REPAINT_LABEL = 'Repaint';
export const TAKE_COVER_LABEL = 'Cover';
export const TAKE_PROVENANCE_REPAINT_PREFIX = 'Repaint from';
export const TAKE_PROVENANCE_COVER_PREFIX = 'Cover from';
export const TAKE_ARCHIVED_SOURCE_TITLE =
	"Archived takes are scheduled for deletion and can't be used as a source";
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
export const TAKE_RESCORE_LABEL = 'Re-score';
export const TAKE_RESCORING_LABEL = 'Re-scoring…';
export const TAKE_RESCORE_QUEUED_TOAST = 'Re-scoring this take…';
export const TAKES_EMPTY = 'No takes yet';
export const TAKES_LOADING = 'Loading takes…';
export const TAKES_ERROR = 'Failed to load takes';
// {version} is replaced with the version number Generate would create next.
export const TAKES_DRAFT_BANNER_TEMPLATE = 'Draft — unsaved changes. Generate creates v{version}.';
export const TAKES_GENERATING_LABEL = 'generating';
export const TAKES_QUEUED_LABEL = 'queued';
export const EDITOR_QUEUED_LABEL = 'Queued';
export const EDITOR_QUEUE_POSITION_TEMPLATE = `${EDITOR_QUEUED_LABEL} (#{position})`;
export const WORKER_TRAINING_REMAINING_TEMPLATE = 'Training ({seconds}s remaining)';
export const TAKES_MOBILE_HINT = 'Tap play → details in Now Playing';
export const TAKES_DELETE_VERSION_LABEL = 'Delete version…';

export const EDITOR_TABS_LABEL = 'Editor tabs';
export const EDITOR_TAB_WRITE_LABEL = 'Write';
export const EDITOR_TAB_TAKES_LABEL = 'Takes';

export const COWRITER_TURN_TIMEOUT_MS = 600_000;
export const EDITOR_VIEWS_LABEL = 'Editor views';
export const EDITOR_VIEW_COWRITER_LABEL = 'Co-Writer';
export const EDITOR_VIEW_RECIPE_LABEL = 'Recipe';

export const PROVIDER_CLI_LOGIN_LABELS: Record<string, string> = {
	claude_cli: 'Claude Code CLI login',
	grok_cli: 'Grok CLI login',
	codex_cli: 'Codex CLI login'
};
export const PROVIDER_CONFIGURED_LABEL = 'configured';
export const PROVIDER_NOT_CONFIGURED_LABEL = 'not configured';
export const PROVIDER_LOGIN_ONLY_LABEL = 'login only';
export const PROVIDER_KEY_ONLY_LABEL = 'key only';
export const PROVIDER_MISSING_DEPENDENCY_LABEL = 'missing dependency';
export const PROVIDER_UNVERIFIED_LABEL = 'Unchecked';
export const PROVIDER_UNVERIFIED_DETAIL = 'Provider check is still running in the background';
export const PROVIDER_STATUS_DESCRIPTION =
	"Each provider's real reachability — whether it can answer you, by what means, and what is still missing when it cannot.";
export const PROVIDER_STATUS_REFRESHING_MESSAGE = 'Refreshing provider status...';
export const PROVIDER_STATUS_EMPTY_MESSAGE = 'No provider status is available.';
export const PROVIDER_STATUS_UNAVAILABLE_DETAIL = 'Provider status is unavailable';
export const PROVIDER_COWRITER_SURFACE_PREFIX = 'co-writer:';
export const PROVIDER_JUDGE_SURFACE_PREFIX = 'judge:';
export const COWRITER_MODEL_CURRENT_NOT_IN_CATALOG = 'current, not in catalog';
export const COWRITER_SAVE_NOTHING_CHANGED = 'Nothing changed.';
export const COWRITER_SAVE_CHANGED = 'Changed, not saved yet.';
export const COWRITER_SAVE_MODEL_REQUIRED = 'Choose a model before saving.';
export const PROVIDER_ROUTE_CLI_LABEL = 'CLI';
export const PROVIDER_ROUTE_API_LABEL = 'API';
export const PROVIDER_ROUTE_READY_LABEL = 'ready';
export const PROVIDER_ROUTE_NOT_SET_UP_LABEL = 'not set up';
export const PROVIDER_ROUTE_BROKEN_LABEL = 'broken';
export const PROVIDER_ROUTE_KEY_SET_LABEL = 'key: set';
export const PROVIDER_ROUTE_KEY_NOT_SET_LABEL = 'key: not set';
export const PROVIDER_ROUTE_MODELS_LABEL = 'Provider routes';
export const PROVIDER_ROUTE_MODEL_LABEL = 'model';
export const PROVIDER_ROUTE_NO_MODELS_LABEL = 'No models available';
export const PROVIDER_ROUTE_STATUS_UNAVAILABLE_LABEL = 'status unavailable';
export const PROVIDER_ROUTE_ACTIVE_LABEL = 'Active route';
export const PROVIDER_ROUTE_STILL_ACTIVE_LABEL = 'Still active route';
export const PROVIDER_ROUTE_UNAVAILABLE_LABEL = 'Provider unavailable';
export const PROVIDER_ROUTE_UNAVAILABLE_DETAIL =
	'No ready route is configured. A new turn cannot start.';
export const PROVIDER_ROUTE_CONFIGURATION_REQUIRED =
	'Select CLI or API for every provider before saving.';
export const PROVIDER_ROUTE_TURN_BLOCKED_LABEL = 'Turn blocked';
export const PROVIDER_ROUTE_TURN_BLOCKED_NEXT_STEP = 'Choose a ready route to continue.';

export function providerRouteModelLabel(route: 'cli' | 'api' | undefined): string {
	return route
		? `${route === 'cli' ? PROVIDER_ROUTE_CLI_LABEL : PROVIDER_ROUTE_API_LABEL} ${PROVIDER_ROUTE_MODEL_LABEL}`
		: 'Model';
}

export function providerRouteBlockedDetail(
	provider: string,
	route: 'cli' | 'api',
	state: string,
	reason: string
): string {
	return `${provider} ${route === 'cli' ? PROVIDER_ROUTE_CLI_LABEL : PROVIDER_ROUTE_API_LABEL} · ${state} — ${reason} ${PROVIDER_ROUTE_TURN_BLOCKED_NEXT_STEP}`;
}

export function providerMissingDependencyDetail(dependency: string | null | undefined): string {
	return `Missing ${dependency ?? 'required dependency'}`;
}

export function providerMissingRequirementDetail(requirement: string | null | undefined): string {
	return `Missing ${requirement ?? 'required API key'}`;
}

export function providerCliLoginNeedsApiKeyDetail(cliLogin: string | null | undefined): string {
	return `${cliLogin ?? 'required CLI login'} found — but answering needs its API key`;
}

export const PROVIDER_API_KEY_NEEDS_CLI_LOGIN_DETAIL =
	'Key is set, but answering needs the Claude Code CLI login';

export function providerConfiguredDetail(
	cliLogin: string | null | undefined,
	environmentKey: string | null | undefined
): string {
	return `Configured via ${cliLogin ?? environmentKey ?? 'provider credentials'}`;
}

// The co-writer is one global conversation (REQ-COWRITER-01): a proposal
// streamed while song X is open can target song Y. Every tool-call badge
// that attributes a proposal to its target song shares this copy.
export const COWRITER_TOOL_CALL_TARGET_PREFIX = 'for:';
export const COWRITER_TOOL_CALL_FOREIGN_TARGET_TITLE =
	'This proposal applies to a different song than the one you have open';

export const EDITOR_GENERATE_LABEL = 'Generate';
export const EDITOR_GENERATE_REPAINT_LABEL = 'Generate Repaint';
export const EDITOR_GENERATE_COVER_LABEL = 'Generate Cover';
export const EDITOR_SAVE_LABEL = 'Save';
export const EDITOR_SAVE_ACCESSIBLE_LABEL = 'Save changes';
export const EDITOR_GENERATING_LABEL = 'Generating...';
export const EDITOR_NO_MODELS_WARNING = 'No models enabled. Ask admin to enable one.';
export const EDITOR_SELECT_MODEL_TITLE = 'Select a model first';
export const EDITOR_MISSING_CONTENT_TITLE = 'Add lyrics and style prompt first';
export const EDITOR_QUEUE_BUSY_TITLE = 'System busy — submit may be rejected';
export const EDITOR_GPU_OFFLINE_LABEL = 'GPU offline';
export const EDITOR_GPU_OFFLINE_TITLE = 'No ACE-Step worker online — generation unavailable';
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
export const RECIPE_SOURCE_MODE_HINT =
	"Paints using the lyrics and style currently in the editor — not the source take's own.";
export const RECIPE_USES_LABEL = 'Generate uses this recipe';
// A freshly pinned seed with no prior value starts at 0 rather than a random
// number, so pinning is deterministic and immediately editable.
export const RECIPE_DEFAULT_PINNED_SEED = 0;
// Shown instead of the full panel when Co-Writer and Recipe are both open, so
// the chat column stays above the fold; "Edit" reveals the full panel.
export const RECIPE_STACKED_LABEL = 'Recipe summary';
export const RECIPE_STACKED_EDIT_LABEL = 'Edit';

export const LIBRARY_QUERY_REQUIRED = 'Search query is required';
export const RAIL_SEARCH_LABEL = 'Search or go to…';
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
export const ALBUM_COVER_UPLOAD_LABEL = 'Upload…';
export const ALBUM_COVER_REPLACE_LABEL = 'Replace album cover';
export const ALBUM_COVER_REMOVE_LABEL = 'Remove album cover';
export const ALBUM_COVER_SUGGEST_LABEL = 'Suggest cover';
export const ALBUM_COVER_SUGGESTIONS_LOADING = 'Loading cover suggestions…';
export const ALBUM_COVER_SUGGESTING_LABEL = 'Making your covers…';
export const ALBUM_COVER_SUGGESTIONS_TITLE = 'Choose a cover';
export const ALBUM_COVER_SUGGESTIONS_DETAIL = 'Three suggestions from this album’s metadata';
export const ALBUM_COVER_SUGGESTION_USE_LABEL = 'Use this';
export const ALBUM_COVER_SUGGESTIONS_DISCARD_LABEL = 'Discard all';
export const ALBUM_COVER_SUGGESTIONS_FAILED_TITLE = 'Couldn’t make cover suggestions';
export const ALBUM_COVER_SUGGESTIONS_FAILED_FALLBACK = 'Cover suggestions failed. Try again.';
export const ALBUM_COVER_SUGGESTIONS_PROGRESS_TEMPLATE =
	'Creating 3 suggestions · {used} of {limit} today';
export const ALBUM_COVER_SUGGESTIONS_REPLACE_LABEL = 'Replace…';
export const ALBUM_COVER_SUGGESTIONS_RETRY_LABEL = 'Try again';

export function albumCoverSuggestionAlt(title: string): string {
	return `Cover suggestion for ${title}`;
}
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
export const COLLECTION_MENU_COVER_REMOVE_LABEL = 'Remove cover';
export const COLLECTION_MENU_RENAME_LABEL = 'Rename';
export const COLLECTION_MENU_ADD_TO_PLAYLIST_LABEL = 'Add to playlist';
export const COLLECTION_MENU_ARCHIVE_LABEL = 'Archive album';
export const COLLECTION_MENU_CURATE_LABEL = 'Curate album';
export const COLLECTION_MENU_SAVE_OFFLINE_LABEL = 'Save offline';
export const COLLECTION_MENU_SAVE_OFFLINE_SAVING_LABEL = 'Saving…';
export const COLLECTION_MENU_SAVE_OFFLINE_REMOVE_LABEL = 'Saved offline · Remove';
// The album header's create action. On a narrow header the glyph stands
// alone — the word would otherwise squeeze the album title out of the row.
export const ALBUM_ADD_SONG_LABEL = '+ Song';
export const ALBUM_ADD_SONG_GLYPH = '+';

export const ALBUM_SUBTITLE_LABEL = 'Album subtitle';
export const ALBUM_SUBTITLE_PLACEHOLDER = 'Add subtitle';
export const ALBUM_SUBTITLE_MAX_LENGTH = 400;
export const ALBUM_YEAR_LABEL = 'Album year';
export const ALBUM_YEAR_PLACEHOLDER = 'Add year';
export const ALBUM_YEAR_MIN = 1900;
export const ALBUM_YEAR_MAX = 2100;
export const ALBUM_YEAR_MAX_LENGTH = String(ALBUM_YEAR_MAX).length;

// The rail's own accessible name — the one navigation landmark that stands on
// every private route, settings included (issue #263).
export const RAIL_NAV_LABEL = 'Primary';
export const RAIL_LIBRARY_LABEL = 'Library';
export const RAIL_ALL_ALBUMS_LABEL = 'All albums';
export const RAIL_PLAYLISTS_LABEL = 'Playlists';
export const RAIL_SETTINGS_LABEL = 'Settings';
// The drawer the compact shell puts the rail in — its accessible name, which
// is how a flow scopes to it while another overlay may be open.
export const RAIL_DRAWER_LABEL = 'Navigation';
export const RAIL_DRAWER_OPEN_LABEL = 'Open menu';
export const RAIL_DRAWER_CLOSE_LABEL = 'Close menu';
export const RAIL_CONTEXT_NO_TAKES = '—';
// Remembers whether the rail's Settings disclosure was left open, so it
// doesn't snap shut the moment the viewer navigates back into the library.
export const RAIL_SETTINGS_OPEN_STORAGE_KEY = 'songmaker.rail-settings-open';
// The LIBRARY and PLAYLISTS groups' own nested navigation landmarks --
// distinct accessible names so a flow (or a screen reader) can tell them
// apart from the rail's outer RAIL_NAV_LABEL and from each other.
export const RAIL_LIBRARY_NAV_LABEL = 'Library albums';
export const RAIL_PLAYLISTS_NAV_LABEL = 'Rail playlists';
export const RAIL_PLAYING_MARKER_LABEL = 'Playing';
// Shown when ensureAllAlbumsLoaded fails outright, so a library the rail
// could not reach at all does not look like one that is merely empty.
export const RAIL_LIBRARY_LOAD_ERROR = "Couldn't load your library";

export const LIBRARY_FILTERS = ['albums', 'playlists', 'shared'] as const;
export type LibraryFilter = (typeof LIBRARY_FILTERS)[number];
export const LIBRARY_DEFAULT_FILTER: LibraryFilter = 'albums';
export const LIBRARY_FILTER_LABELS: Record<LibraryFilter, string> = {
	albums: 'Albums',
	playlists: 'Playlists',
	shared: 'Shared'
};
export const LIBRARY_FILTER_NAV_LABEL = 'Library filter';

export const LIBRARY_ROW_COLLAPSE_LABEL = 'Collapse albums';
export const LIBRARY_ROW_EXPAND_LABEL = 'Expand albums';
// Match the mobile shell: without a stored choice, its song and take row
// starts collapsed so the editor remains the first surface to read.
export const LIBRARY_ROW_COMPACT_MAX_PX = 390;
export const LIBRARY_ROW_COMPACT_MEDIA = `(max-width: ${LIBRARY_ROW_COMPACT_MAX_PX}px)`;

export const LIBRARY_HISTORY_KIND = 'songmaker' as const;
export const LIBRARY_ALBUMS_EMPTY = 'No albums yet';
export const LIBRARY_ALBUMS_LOADING = 'Loading albums…';
export const LIBRARY_ARCHIVED_TOGGLE_LABEL = 'Archived';
export const LIBRARY_ARCHIVED_EMPTY = 'No archived albums';
export const LIBRARY_ARCHIVED_LOADING = 'Loading archived albums…';
export const LIBRARY_ARCHIVED_ERROR = 'Failed to load archived albums';
export const LIBRARY_ARCHIVED_UNARCHIVE_LABEL = 'Unarchive';
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
export const RESOURCE_SYNC_TRACKED_EVENT_LIMIT = 256;
export const JOB_TYPE_GENERATE = 'generate';
export const JOB_TYPE_SCORE = 'score';

// Shown when the backend's IP rate limiter (`middleware/rate_limit.py`)
// rejects a request with 429 — the budget classes it enforces
// (API/Media/Stream) mean this is now rare during ordinary use, but a
// burst can still happen, and a client that silently stalls reads as
// broken. A few paths already surface their own 429 copy some other way
// and are exempted from this toast — see `RATE_LIMIT_TOAST_EXEMPT_PATHS`
// in `lib/api/fetch.ts` for exactly which, and why.
export const RATE_LIMITED_TOAST_MESSAGE =
	'Too many requests — hang on, it will continue in a moment.';

// SSE reconnection backoff (issue #257): jobs.ts (one EventSource per job)
// and resourceSync.ts (the one live-sync stream) both own their `/api/*`
// stream connection and must not lean on the browser's flat ~3s native
// EventSource retry, which is what produced the operator's ERR_QUIC storm
// (~80 opens/min across a handful of concurrently-reconnecting streams).
// Both close the failed connection themselves and reopen it after
// `nextReconnectDelayMs(attempt)` (see `lib/stores/sseReconnect.ts`):
// doubling from a floor up to a 30s ceiling, plus 0-20% jitter so
// concurrently-failing streams don't all reopen in lockstep. Jitter only
// adds to the delay, never subtracts, so it can only slow a stream down
// relative to the math below, never speed it up.
//
// Both curves below matter, not just the saturated one — the pre-saturation
// ramp during a synchronized failure's first minute is its own worst case
// and is checked separately from the long-run steady state.
//
// Steady state, against the backend's Stream class (45 opens/min/IP,
// `stream_rate_limit` in settings.py): once backoff has saturated at the
// ceiling, a stream reopens at most 60_000 / SSE_RECONNECT_MAX_DELAY_MS = 2
// times/min, independent of the base delay below. The reported incident (4
// concurrently-failing job streams -- four `/api/jobs/{id}/stream`
// connections with `ERR_QUIC_PROTOCOL_ERROR` -- alongside the one
// resource-events stream = 5 streams) is 5 * 2 = 10 opens/min in steady
// state. The theoretical ceiling (`max_user_active_jobs` (10) concurrent
// job streams plus the resource stream = 11) is 11 * 2 = 22/min. Both well
// under the 45/min budget and the 33/min legitimate-use baseline the
// backend sized that budget against.
//
// Minute-1 transient, i.e. before the ceiling is reached: a stream that
// starts failing reconnects faster than the saturated rate until backoff
// catches up, so the first 60 seconds after a synchronized failure need
// their own check -- checking only the saturated rate above missed this
// and is why the base delay was 1000ms before an #257 review caught it.
// With BASE=2000ms, FACTOR=2, CEILING=30000ms, a failing stream's reopen
// delays are 2000, 4000, 8000, 16000, 32000(capped to 30000)ms, landing at
// cumulative t = 2s, 6s, 14s, 30s, 60s after it starts failing. Four of
// those (2s, 6s, 14s, 30s) land inside the first 60 seconds; the fifth
// lands right at the boundary. Counting only these storm-driven reopens
// (each stream's own one-time initial connection is a separate,
// already-legitimate open, already priced into the 33/min legitimate-use
// baseline above, not into this reconnect-storm's own contribution), the
// theoretical ceiling of 11 concurrently-failing streams contributes
// 11 * 4 = 44 reopens in that first minute -- under the 45/min budget, with
// 1 to spare. The reported incident's 5 streams contribute 5 * 4 = 20 in
// that same window, comfortably under budget.
//
// At the previous BASE=1000ms, the same transient was 5 reopens/stream (at
// t = 1s, 3s, 7s, 15s, 31s): 11 * 5 = 55, already over the 45/min budget by
// the time the fourth reopen lands around t=15s -- the actual bug this
// constant's value fixes. Do not lower this base delay again without
// re-deriving both curves above; the steady-state math alone will look
// fine right up until the next synchronized failure's first minute.
export const SSE_RECONNECT_BASE_DELAY_MS = 2000;
export const SSE_RECONNECT_BACKOFF_FACTOR = 2;
export const SSE_RECONNECT_MAX_DELAY_MS = 30_000;
export const SSE_RECONNECT_JITTER_RATIO = 0.2;
