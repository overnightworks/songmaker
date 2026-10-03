import type { JobItem } from '$lib/api/types';
import type { RepaintMode } from '$lib/stores/recipe';

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

export const VOICE_PICKER_LABEL = 'Your Voice';
export const VOICE_PICKER_NONE_LABEL = 'None';
export const VOICE_PICKER_CREATE_LABEL = 'Create a voice';
export const VOICE_PICKER_NOT_AVAILABLE_FOR_MODEL = 'not available for this model';
export const VOICE_PICKER_DELETED_LABEL = 'voice deleted';

export function voicePickerMobileLabel(modelMode: string): string {
	return `${VOICE_PICKER_LABEL} · ${modelMode} model`;
}

export const LORA_MIN_SAMPLES_FOR_TRAINING = 3;

export const LORA_MAX_SAMPLES = 20;

export const ADMIN_VOICES_TAB_LABEL = 'Voices';
export const ADMIN_VOICES_HEADING = 'Voice operations';
export const ADMIN_VOICES_LOADING = 'Loading voices...';
export const ADMIN_VOICES_EMPTY = 'No voices have been created.';
export const VOICES_LOAD_FAILED = 'Failed to load voices';
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
const LORA_TRAINING_QUEUE_POSITION_TEMPLATE = 'Position {position} in the queue';
const LORA_TRAINING_EPOCH_TEMPLATE = 'Epoch {current} of {total}';
export const LORA_TRAINING_REMAINING_CALCULATING = 'Calculating remaining time...';
const LORA_TRAINING_REMAINING_TEMPLATE = '~ {time} remaining';

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
export const PLAYLIST_LOADING_LABEL = 'Loading playlist…';
export const SHUFFLE_SCOPE_PLAYLIST = 'this playlist';
export const SHUFFLE_SCOPE_ALBUM = 'this album';
export const SHUFFLE_SCOPE_LIBRARY = 'all albums';

export const QUEUE_STREAM_UNPLAYABLE_START_DETAIL = 'Requested take is not playable';

export const QUEUE_TAKE_MISSING_TOAST = 'This take is not in the queue';

export const SONG_LINK_NOT_FOUND_TOAST = 'Song not found — it may have been deleted';

// A legacy `/?song=<id>&gen=<id>` link whose take is gone still opens the
// song (issue #284) -- the song is the durable value, and takes are pruned
// by ordinary cleanup, so a dead take is not the same failure a dead song
// is. Falling back silently would still hide a fact the app knows, so this
// says so instead of just landing on the song.
export const LEGACY_TAKE_LINK_NOT_FOUND_TOAST =
	'This take no longer exists — opened the song instead';

// A collection header's play circle and the shuffle square beside it name
// what they do to it by its kind: "Play album", "Pause playlist", "Shuffle
// album". Every surface that renders the header, and every flow that finds it
// by name, builds the label here.
export type CollectionPlayKind = 'album' | 'playlist' | 'song' | 'take';
const COLLECTION_PLAY_ACTION = 'Play';
const COLLECTION_PAUSE_ACTION = 'Pause';
const COLLECTION_SHUFFLE_ACTION = 'Shuffle';

export function collectionPlayLabel(kind: CollectionPlayKind): string {
	return `${COLLECTION_PLAY_ACTION} ${kind}`;
}

export function collectionPauseLabel(kind: CollectionPlayKind): string {
	return `${COLLECTION_PAUSE_ACTION} ${kind}`;
}

export function collectionShuffleLabel(kind: CollectionPlayKind): string {
	return `${COLLECTION_SHUFFLE_ACTION} ${kind}`;
}

// The transport's play button is named after the state its click leaves:
// "Pause" while the listener asked for sound — playing, a stalled take
// recovering, or one waiting for the network — "Retry" once it failed,
// otherwise "Play". A flow reads the name to tell a sounding take from a dead one.
export const TRANSPORT_PLAY_LABEL = 'Play';
export const TRANSPORT_PAUSE_LABEL = 'Pause';
export const TRANSPORT_RETRY_LABEL = 'Retry';
// What the transport says once it gave up on a take while the network was
// gone: its return retries the take by itself, so no Retry press is asked for.
export const PLAYER_WAITING_FOR_NETWORK = 'Waiting for the network.';

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
// A cut mini-player title scrolls once, slowly: it rests, travels to its end
// at this pace, rests again, and glides back to its start.
export const MINI_PLAYER_TITLE_SCROLL_PX_PER_SECOND = 30;
export const MINI_PLAYER_TITLE_SCROLL_REST_MS = 1500;
export const MINI_PLAYER_TITLE_SCROLL_RETURN_MS = 600;
export const REDUCED_MOTION_MEDIA = '(prefers-reduced-motion: reduce)';
// Beside play's exact centre line a phone narrower than 360px leaves the
// mini player's left side too little room for cover and title, so the cover
// goes and the title takes the whole side. The query stays on max-width, like
// every other breakpoint, because iOS Safari before 16.4 ignores range syntax;
// the fraction also drops the cover on a sub-pixel viewport just under 360px.
const MINI_PLAYER_WITHOUT_COVER_MAX_VIEWPORT_PX = 359.98;
export const MINI_PLAYER_WITHOUT_COVER_MEDIA = `(max-width: ${MINI_PLAYER_WITHOUT_COVER_MAX_VIEWPORT_PX}px)`;
export const NOW_PLAYING_NO_LYRICS = 'No lyrics for this take';
export const NOW_PLAYING_IMPORTED_TAKE_NO_LYRICS = 'Imported take — no lyrics were saved with it.';
export const NOW_PLAYING_GO_TO_SONG = 'Go to song';
export const NOW_PLAYING_CLOSE = 'Close';
export const NOW_PLAYING_TAKE_PREFIX = 'Take';

export const TAKE_REPAINT_LABEL = 'Repaint';
export const TAKE_COVER_LABEL = 'Cover';
export const TAKE_PROVENANCE_REPAINT_PREFIX = 'Repaint from';
export const TAKE_PROVENANCE_COVER_PREFIX = 'Cover from';
export const TAKE_PICK_LABEL = 'Pick';
export const TAKE_OVERFLOW_LABEL = 'More';
export const TAKE_SHARE_LABEL = 'Share';
export const TAKE_PLAYLIST_LABEL = 'Add to playlist';
export const TAKE_ARCHIVED_TITLE = 'Archived take';
export const TAKE_DELETE_LABEL = 'Delete';
export const TAKE_KEEP_LABEL = 'Keep';
export const TAKE_UNKEEP_LABEL = 'Unkeep';
export const TAKE_DELETE_TITLE_TEMPLATE = 'Delete take {number}?';
export const TAKE_DELETE_MESSAGE = 'Audio files will be permanently deleted';
export const TAKE_RESCORE_LABEL = 'Re-score';
export const TAKE_RESCORING_LABEL = 'Re-scoring…';
export const TAKE_RESCORE_QUEUED_TOAST = 'Re-scoring this take…';
export const TAKES_EMPTY = 'No takes yet · Generate on Write';
export const TAKES_LOADING = 'Loading takes…';
export const TAKES_ERROR = 'Failed to load takes';
export const TAKES_RETRY_LABEL = 'Try again';
// {version} is replaced with the version number Generate would create next.
export const TAKES_DRAFT_BANNER_TEMPLATE = 'Draft — unsaved changes. Generate creates v{version}.';
export const EDITOR_QUEUED_LABEL = 'Queued';
export const WORKER_TRAINING_REMAINING_TEMPLATE = 'Training ({seconds}s remaining)';
// Named when an admin panel's first read fails while no offline strip says why.
export const WORKER_POOL_LOAD_FAILED = 'Cannot reach the worker pool API.';
export const WORKER_POOL_REFRESH_FAILED = 'Worker pool not updating — retrying…';
export const MODEL_REGISTRY_LOAD_FAILED = 'Cannot reach the registry API.';
export const TAKES_MOBILE_HINT = 'Tap play → details in Now Playing';

export const EDITOR_TAB_TAKES_LABEL = 'Takes';
export const EDITOR_TAB_EDIT_LABEL = 'Edit';
export const EDITOR_TABS_LABEL = 'Editor tabs';

export const COWRITER_TURN_TIMEOUT_MS = 600_000;
export const COWRITER_RUNNING_TURN_POLL_MS = 2_000;
export const COWRITER_RUNNING_TURN_POLL_FAILURE_LIMIT = 3;
export const COWRITER_CLAUDE_UNVERIFIED_LABEL =
	"Claude's tools could not be verified yet — your next message checks again.";
export const COWRITER_CONVERSATION_MENU_LABEL = 'Conversation menu';
export const COWRITER_COMPOSER_PLACEHOLDER = 'Ask for a rewrite…';
export const COWRITER_SEND_LABEL = 'Send';
export const COWRITER_NEW_CONVERSATION_LABEL = 'New conversation';
export const COWRITER_MEMORY_LABEL = 'Memory';
export const COWRITER_MEMORY_PROPOSAL_WAITING_LABEL = 'Memory proposal waiting';
export const COWRITER_DELETE_CONVERSATION_TITLE = 'Delete conversation?';
export const COWRITER_DELETE_CONVERSATION_WARNING = "This can't be undone.";
export const DAY_LABEL_TODAY = 'today';
export const DAY_LABEL_YESTERDAY = 'yesterday';
export const DAY_LABEL_ADDED = 'added';
export const PLACE_KIND_PLAYLIST_LABEL = 'Playlist';
export const PLACE_LINE_SEPARATOR = ' · ';
export const COWRITER_NEW_CONVERSATION_LINE = 'new conversation';
export const COWRITER_CONVERSATION_SINCE_TEMPLATE = 'conversation since {day}';
export const COWRITER_ARCHIVED_CONVERSATION_TEMPLATE = 'archived conversation from {day}';
export const COWRITER_CONVERSATION_ROW_TEMPLATE = 'Conversation since {day} {time}';
export const COWRITER_ARCHIVED_CONVERSATION_ROW_TEMPLATE = 'Archived · {day} {time}';
export const COWRITER_MESSAGE_COUNT_TEMPLATE = '{count} msgs';
export const COWRITER_SINGLE_MESSAGE_COUNT = '1 msg';
export const COWRITER_CONVERSATION_CONFIRM_TEMPLATE = '{name} · {count}';
export const COWRITER_TURN_FAILURE_TEMPLATE = '{provider}: {reason}';
export const EDITOR_VIEWS_LABEL = 'Editor views';
export const EDITOR_VIEW_COWRITER_LABEL = 'Co-writer';
export const EDITOR_VIEW_RECIPE_LABEL = 'Recipe';

export const PROVIDER_CLI_LOGIN_LABELS: Record<string, string> = {
	claude_cli: 'Claude Code CLI login',
	grok_cli: 'Grok CLI login',
	codex_cli: 'Codex CLI login'
};
export const PROVIDER_UNVERIFIED_DETAIL = 'Provider check is still running in the background';
export const PROVIDER_STATUS_UNAVAILABLE_DETAIL = 'Provider status is unavailable';
export const PROVIDER_ROUTE_CLI_LABEL = 'CLI';
export const PROVIDER_ROUTE_API_LABEL = 'API';

export function providerMissingDependencyDetail(dependency: string | null | undefined): string {
	return `Missing ${dependency ?? 'required dependency'}`;
}

export function providerMissingRequirementDetail(requirement: string | null | undefined): string {
	return `Missing ${requirement ?? 'required API key'}`;
}

export function providerCliLoginNeedsApiKeyDetail(cliLogin: string | null | undefined): string {
	return `${cliLogin ?? 'required CLI login'} found — but answering needs its API key`;
}

export const MODELS_HEADING = 'Models';
export const MODELS_LOADING_LABEL = 'Loading…';
export const MODELS_TASK_COWRITER_LABEL = 'Co-Writer';
export const MODELS_TASK_COVER_LABEL = 'Cover';
export const MODELS_TASK_SCORING_LABEL = 'Scoring';
export const MODELS_COLUMN_TASK_LABEL = 'Task';
export const MODELS_COLUMN_PROVIDER_LABEL = 'Provider';
export const MODELS_COLUMN_ROUTE_LABEL = 'Route';
export const MODELS_COLUMN_MODEL_LABEL = 'Model';
export const MODELS_COLUMN_STATUS_LABEL = 'Status';
export const MODELS_STATUS_CHECKING_LABEL = 'Checking…';
export const MODELS_STATUS_READY_CLI_LABEL = 'Ready · CLI login';
export const MODELS_STATUS_READY_KEY_LABEL = 'Ready · key set';
export const MODELS_STATUS_NEEDS_API_KEY_LABEL = 'Needs its API key';
export const MODELS_STATUS_NOT_SAVED_LABEL = 'Not saved';
export const MODELS_OPTION_READY_LABEL = '✓ ready';
export const MODELS_OPTION_NEEDS_API_KEY_PHRASE = 'needs its API key';
export const MODELS_NO_MODELS_LABEL = 'No models';
export const MODELS_LIST_NEEDS_KEY_HINT = 'List needs the key';
export const MODELS_LIST_NEEDS_CLI_HINT = 'List needs the CLI';
export const MODELS_SAVED_LABEL = 'Saved.';
export const MODELS_RETRY_LABEL = 'Retry';
export const MODELS_ADVANCED_LABEL = 'Advanced';
export const MODELS_HISTORY_TAIL_LABEL = 'History tail (tokens)';
export const MODELS_ROUTE_KEY_SET_PHRASE = 'key set';
export const MODELS_ROUTE_KEY_NOT_SET_PHRASE = 'key not set';
export const MODELS_ROUTE_LOGGED_IN_PHRASE = 'logged in';
export const MODELS_ROUTE_NOT_LOGGED_IN_PHRASE = 'not logged in';
export const MODELS_ROUTE_NO_IMAGE_TOOL_PHRASE = 'no image tool';
export function modelsRouteNotAvailablePhrase(task: string): string {
	return `not available for ${task.toLowerCase()}`;
}

export function modelsCannotDrawHint(provider: string): string {
	return `${provider} cannot draw`;
}

export const MODELS_SAVE_FAILED_FALLBACK = 'The server rejected the change.';

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

export const EDITOR_GENERATE_MODE_LABELS = {
	generate: 'Generate',
	repaint: TAKE_REPAINT_LABEL,
	cover: TAKE_COVER_LABEL
};
export const EDITOR_GENERATE_QUEUED_TEMPLATE = `${EDITOR_QUEUED_LABEL} #{position}`;
export const EDITOR_GENERATE_TAKE_TEMPLATE = 'Take {index} of {count}';
export const EDITOR_GENERATE_CANCEL_LABEL = 'Cancel generation';
// Offline a running take cannot report anything (#1039 O2): it says so and
// keeps the last progress it saw, instead of a percent and time that stand still.
export const EDITOR_GENERATE_RECONNECTING_LABEL = 'Reconnecting…';
export const EDITOR_GENERATE_LAST_SEEN_TEMPLATE = 'last seen at {percent}%';
export const EDITOR_GENERATE_CANCEL_OFFLINE_LABEL = 'Cancel generation (unavailable while offline)';
export const EDITOR_GENERATE_LAST_SEEN_PROGRESS_LABEL = 'Last known progress';
export const EDITOR_GENERATE_CANCEL_FAILED = 'Could not cancel generation';
export const EDITOR_GENERATE_FAILURE_EXPAND_LABEL = 'Show generation error';
export const EDITOR_GENERATE_FAILURE_COLLAPSE_LABEL = 'Collapse generation error';
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
export const EDITOR_GPU_OFFLINE_TITLE = 'No GPU worker online';
export const EDITOR_LYRICS_LABEL = 'Lyrics';
export const EDITOR_STYLE_LABEL = 'Style';
export const EDITOR_STYLE_PROMPT_LABEL = 'Style Prompt';
export const EDITOR_UNSAVED_TITLE = 'Unsaved changes';
export const EDITOR_UNSAVED_MESSAGE =
	'Save this draft as a new version before leaving, or discard it?';
export const EDITOR_UNSAVED_SAVE_LABEL = 'Save';
export const EDITOR_UNSAVED_DISCARD_LABEL = 'Discard';
export const EDITOR_SAVE_FAILED = 'Save failed';
const VERSION_CHIP_DRAFT_LABEL = 'draft';
export const VERSIONS_SHEET_LABEL = 'Versions';
export const VERSIONS_SHEET_CLOSE_LABEL = 'Close versions';
export const VERSION_CURRENT_TAG = 'current';
export const VERSION_PICKED_LABEL = 'picked';
export const VERSION_REPLACE_DRAFT_TITLE = 'Replace your unsaved draft?';
export const VERSION_REPLACE_DRAFT_CONFIRM_LABEL = 'Replace';
export const VERSION_DELETE_CONFIRM_LABEL = 'Delete version';
export const VERSION_DELETE_PICK_WARNING = 'The album pick is one of them.';
export const VERSION_DELETE_DRAFT_GOES = 'Your unsaved draft goes too.';
export const VERSION_DELETE_EMPTIES_EDITOR = 'Its lyrics leave the editor, which will be empty.';
export const VERSION_NO_LYRICS = 'No lyrics';
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

export function versionDeleteReplacedBy(versionNumber: number): string {
	return `Its lyrics leave the editor; ${versionLabel(versionNumber)} takes their place.`;
}

export function versionLoadedFromLabel(versionNumber: number): string {
	return `Loaded from ${versionLabel(versionNumber)}`;
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

export const PHONE_RECIPE_LOADING = 'Loading…';
export const PHONE_RECIPE_LOADED = 'Loaded';
export const MODELS_LOAD_ERROR = 'Failed to load models';
export const PHONE_RECIPE_RETRY = 'Retry';
export const PHONE_RECIPE_PARAMETERS = 'LM / DiT';
export const PHONE_RECIPE_CUSTOM = 'Custom';
export const PHONE_RECIPE_REFERENCE = 'Reference';
export const PHONE_RECIPE_UPLOAD = 'Upload audio';
export const PHONE_RECIPE_UPLOAD_ERROR = 'Upload failed';
export const PHONE_RECIPE_REMOVE = 'Remove';
export const PHONE_RECIPE_DEFAULTS_ERROR = 'Failed to load generation defaults';
export const PHONE_RECIPE_REPAINT_STRENGTH = 'Repaint strength';
export const PHONE_RECIPE_COVER_STRENGTH = 'Cover strength';
export const PHONE_RECIPE_NOISE_STRENGTH = 'Noise strength';
export const PHONE_RECIPE_REPAINT_MODES: { value: RepaintMode; label: string }[] = [
	{ value: 'conservative', label: 'Conservative' },
	{ value: 'balanced', label: 'Balanced' },
	{ value: 'aggressive', label: 'Aggressive' }
];

// Shared with RecipePanel.svelte's own copy of these same limits (#924 tracks
// unifying the two into one owner).
export const RECIPE_BPM_MAX = 999;
export const RECIPE_DURATION_MAX_SECONDS = 600;
export const RECIPE_TAKES_PER_GENERATE_OPTIONS = [1, 2, 3, 5, 10] as const;
export const RECIPE_MAX_INFERENCE_STEPS_DEFAULT = 200;
export const RECIPE_SOURCE_DURATION_DEFAULT_SECONDS = 180;

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
export const RAIL_SEARCH_CLEAR_LABEL = 'Clear search';
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
export const LIBRARY_WALL_ORDERS = ['title', 'recent', 'added'] as const;
export type LibraryWallOrder = (typeof LIBRARY_WALL_ORDERS)[number];
export const LIBRARY_WALL_ORDER_LABELS: Record<LibraryWallOrder, string> = {
	title: 'A–Z',
	recent: 'Recent',
	added: 'Added'
};
export const LIBRARY_WALL_HEADING = 'Albums & playlists';
export const LIBRARY_WALL_ORDER_GROUP_LABEL = 'Sort albums and playlists';
export const LIBRARY_WALL_EMPTY = 'No albums yet.';
export const LIBRARY_NEW_FACE = 'New';
export const LIBRARY_NEW_MENU_LABEL = 'New album or playlist';
export const LIBRARY_NEW_MENU_CLOSE_LABEL = 'Close New in Library';
export const LIBRARY_NEW_ALBUM_LABEL = 'Album';
export const LIBRARY_NEW_PLAYLIST_LABEL = 'Playlist';
// The server's own ceiling on an album, playlist or song title (and an album's artist).
export const NEW_PLACE_TEXT_MAX_LENGTH = 200;
export const NEW_PLACE_CREATE_LABEL = 'Create';
export const NEW_PLACE_OFFLINE =
	"You're offline, so nothing was created. Try again once you're back online.";
export const NEW_ALBUM_CARD_LABEL = 'New album';
export const NEW_ALBUM_CLOSE_LABEL = 'Close new album';
export const NEW_ALBUM_TITLE_LABEL = 'Title';
export const NEW_ALBUM_ARTIST_LABEL = 'Artist';
export const NEW_ALBUM_ARTIST_OPTIONAL = 'optional';
export const NEW_ALBUM_HINT = 'Opens the album; add songs there.';
export const NEW_ALBUM_FAILED = 'The album could not be created. Try again.';
export const NEW_PLAYLIST_CARD_LABEL = 'New playlist';
export const NEW_PLAYLIST_CLOSE_LABEL = 'Close new playlist';
export const NEW_PLAYLIST_NAME_LABEL = 'Name';
export const NEW_PLAYLIST_HINT = 'Opens the playlist; add songs from any album.';
export const NEW_PLAYLIST_FAILED = 'The playlist could not be created. Try again.';
export const NEW_SONG_ROW_LABEL = 'New song';
export const NEW_SONG_CLOSE_LABEL = 'Close new song';
export const NEW_SONG_TITLE_LABEL = 'Title';
export const NEW_SONG_HINT = 'Opens the song on Write.';
export const NEW_SONG_FAILED = 'The song could not be created. Try again.';
export const ALBUM_NO_SONGS = 'No songs yet.';

export function newSongCardLabel(albumTitle: string): string {
	return `New song in ${albumTitle}`;
}
// The continue endpoint's own ceiling (PAGE_MAX_LIMIT): Recent reads its places in pages this size.
export const LIBRARY_WALL_RECENT_PAGE_SIZE = 200;
export const ALBUM_ART_EMPTY_INITIALS = '?';
export const ALBUM_ART_INITIAL_COUNT = 2;
export const ALBUM_COVER_ACCEPT = 'image/jpeg,image/png';
export const ALBUM_COVER_ALT_TYPE = 'Album';
export const ALBUM_COVER_UPLOAD_LABEL = 'Upload…';
export const ALBUM_COVER_ADD_LABEL = 'Add cover';
export const ALBUM_COVER_EDIT_LABEL = 'Edit cover';
export const ALBUM_COVER_EDITING_LABEL = 'Cover editing';
export const ALBUM_COVER_EDITING_CLOSE_LABEL = 'Close cover editing';
export const ALBUM_COVER_EDITING_UPLOAD_LABEL = 'Upload';
export const ALBUM_COVER_SUGGEST_LABEL = 'Suggest';
export const ALBUM_COVER_SUGGEST_ANOTHER_LABEL = 'Suggest another';
export const ALBUM_COVER_SUGGESTION_USE_LABEL = 'Use';
export const ALBUM_COVER_EDITING_REMOVE_LABEL = 'Remove';
export const ALBUM_COVER_PREVIOUS_SUGGESTION_LABEL = 'Previous suggestion';
export const ALBUM_COVER_NEXT_SUGGESTION_LABEL = 'Next suggestion';
export const ALBUM_COVER_SUGGESTIONS_LOADING = 'Loading cover suggestion…';
export const ALBUM_COVER_SUGGESTING_LABEL = 'Making your cover…';
export const ALBUM_COVER_SUGGESTION_FAILED_TITLE = 'Couldn’t make a cover suggestion';
export const ALBUM_COVER_SUGGESTION_FAILED_FALLBACK = 'The cover suggestion failed. Try again.';
// The server's own words for a spent daily limit, so the editor says it the
// same way whether it knew before asking or was refused.
export const ALBUM_COVER_DAILY_LIMIT_REACHED = 'Daily cover suggestion limit reached';
export const ALBUM_COVER_SUGGESTIONS_RETRY_LABEL = 'Try again';
// A sideways drag on the cover this far, and more sideways than up or down,
// shows the neighbouring suggestion; anything less is a tap or a scroll.
export const ALBUM_COVER_SWIPE_TRAVEL_PX = 40;

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

export const SETTINGS_NAV_LABEL = 'Settings sections';
export const ADMIN_TABS_LABEL = 'Admin sections';

// The phone's account circle and the menu it opens (issue #1158).
export const ACCOUNT_MENU_LABEL = 'Account';
export const ACCOUNT_MENU_CLOSE_LABEL = 'Close account menu';
export const ACCOUNT_MENU_SIGNED_IN_PREFIX = 'Signed in as';
export const ACCOUNT_MENU_LOGOUT_LABEL = 'Log out';
export const THEME_SWITCH_TO_LIGHT_LABEL = 'Light theme';
export const THEME_SWITCH_TO_DARK_LABEL = 'Dark theme';

export const COLLECTION_MENU_LABEL = 'More';
export const COLLECTION_MENU_CLOSE_LABEL = 'Close menu';
export const COLLECTION_MENU_SHARE_LABEL = 'Share';
export const COLLECTION_MENU_DELETE_LABEL = 'Delete';
export const COLLECTION_MENU_COVER_LABEL = 'Cover';
export const COLLECTION_MENU_COVER_HINT = 'upload · suggest';
export const COLLECTION_MENU_COVER_REMOVE_LABEL = 'Remove cover';
export const COLLECTION_MENU_RENAME_LABEL = 'Rename';
export const COLLECTION_MENU_EDIT_DETAILS_LABEL = 'Edit details';
export const COLLECTION_MENU_ADD_TO_PLAYLIST_LABEL = 'Add to playlist';
export const COLLECTION_MENU_ARCHIVE_LABEL = 'Archive';
export const COLLECTION_MENU_CURATE_LABEL = 'Curate';
export const COLLECTION_MENU_SAVE_OFFLINE_LABEL = 'Save offline';
export const COLLECTION_MENU_SAVE_OFFLINE_SAVING_LABEL = 'Saving…';
export const COLLECTION_MENU_SAVE_OFFLINE_REMOVE_LABEL = 'Saved offline · Remove';
export const ALBUM_DETAILS_CLOSE_LABEL = 'Close edit details';
export const ALBUM_DETAILS_SAVE_LABEL = 'Save';
export const ALBUM_DETAILS_TITLE_REQUIRED = 'Title cannot be empty';
export const ALBUM_DETAILS_SAVED = 'Details saved';
export const ALBUM_DETAILS_SAVE_FAILED = 'Saving the details failed';
export const ALBUM_SUBTITLE_LABEL = 'Subtitle';
export const ALBUM_SUBTITLE_MAX_LENGTH = 400;
export const ALBUM_YEAR_LABEL = 'Year';
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

// Every row's PlayingMark reads this, in the rail, the detail views and the shared page.
export const PLAYING_MARK_LABEL = 'Playing';
// Shown when ensureAllAlbumsLoaded fails outright, so a library the rail
// could not reach at all does not look like one that is merely empty.
export const RAIL_LIBRARY_LOAD_ERROR = "Couldn't load your library";

export const LIBRARY_HISTORY_KIND = 'songmaker' as const;
export const LIBRARY_ALBUMS_LOADING = 'Loading albums…';
export const LIBRARY_PLAYLISTS_LOADING = 'Loading playlists…';
export const LIBRARY_PLAYLISTS_ERROR = 'Failed to load playlists';
const PLAYLIST_ENTRY_OVERFLOW_LABEL = 'More';

export function playlistEntryOverflowLabel(songTitle: string): string {
	return `${PLAYLIST_ENTRY_OVERFLOW_LABEL} for ${songTitle}`;
}
export const PLAYLIST_ENTRY_OPEN_SONG_LABEL = 'Open song in editor';
export const PLAYLIST_ENTRY_MOVE_UP_LABEL = 'Move up';
export const PLAYLIST_ENTRY_MOVE_DOWN_LABEL = 'Move down';
export const PLAYLIST_ENTRY_REMOVE_LABEL = 'Remove from playlist';
export const LIBRARY_SHARES_COPY_LABEL = 'Copy link';

export const COWRITER_TURN_PATH = '/api/chat/turn';
export const RESOURCE_EVENT_STREAM_PATH = '/api/resource-events/stream';
export const PLAYBACK_DIAGNOSTICS_PATH = '/api/playback-diagnostics';
export const RESOURCE_EVENT_HELLO = 'hello';
export const RESOURCE_EVENT_RESYNC = 'resync';
export const RESOURCE_EVENT_GENERATION_CREATED = 'generation.created';
export const RESOURCE_SYNC_ERROR = 'Library sync failed';
export const OFFLINE_STRIP_MESSAGE = "You're offline — retrying";
// The edge's own answers for a server it cannot reach (down or restarting).
// Only these, besides a request the network never carried, read as offline:
// a 429 or a 500 comes from a server that is there (#1099).
export const SERVER_UNREACHABLE_STATUSES: ReadonlySet<number> = new Set([502, 503, 504]);
export const SERVER_ERROR_STATUS_FLOOR = 500;
// A rate limit passes: a song refresh it refused is fetched again on the
// song-refresh backoff, no sooner than its `Retry-After` (#1099).
export const RATE_LIMITED_STATUS = 429;
export const RESOURCE_SYNC_BOOTSTRAP_ERROR_LIMIT = 3;
// `EventSource.CLOSED`, spelled out because the jsdom test runtime has no EventSource.
export const EVENT_SOURCE_CLOSED = 2;
export const RESOURCE_SYNC_FETCH_CONCURRENCY = 4;
export const RESOURCE_SYNC_VISIBILITY_DEBOUNCE_MS = 250;
// While the server cannot be reached, a cheap auth probe asks this often
// whether it is back, so the offline strip goes within ~2s of its return
// rather than after the stream's up-to-10s backoff (#1099). Only a request
// the edge answers itself costs anything while the server is down, and the
// first answer ends the probing.
export const RESOURCE_SYNC_RETURN_PROBE_INTERVAL_MS = 1000;
export const RESOURCE_SYNC_TRACKED_EVENT_LIMIT = 256;
export const JOB_TYPE_GENERATE = 'generate';
export const JOB_TYPE_SCORE = 'score';
export const JOB_TYPE_COVER = 'cover';

// Shown when the backend's IP rate limiter (`webauth.middleware.rate_limit`)
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
// doubling from a floor up to an 8s ceiling, plus 0-20% jitter so
// concurrently-failing streams don't all reopen in lockstep. Jitter only
// adds to the delay, never subtracts, so it can only slow a stream down
// relative to the math below, never speed it up. A waiting stream also
// reopens at once when the page becomes visible, regains focus or the
// browser reports the network back (`watchReconnectOpportunities`); those
// reopens follow the musician's own actions, one per waiting stream each,
// and at most one per `SSE_IMMEDIATE_REOPEN_MIN_GAP_MS` per stream -- 20
// app switches in 3s once opened 40 streams (#1099). Only the reopen is
// spaced: inside the gap a waiting stream keeps its backoff, while the
// library's revalidation (debounced on its own) and the restart of a first
// sync that failed with a visible error (no backoff to wait on) still run.
// The gap never adds opens to the math below.
//
// The ruling on #1032 (26.09.2026) caps the wait at 10s: a phone whose
// network returned without an `online` event showed its new take 22-27s
// late, because the backoff had grown to ~30s. An 8s ceiling keeps the
// longest wait, jitter included, at 8 * 1.2 = 9.6s. With BASE=2000ms,
// FACTOR=2, CEILING=8000ms a failing stream reopens after 2, 4, 8, 8...
// seconds -- at t = 2, 6, 14, 22, 30, 38, 46, 54s, so 8 reopens in the first
// minute and 7.5/min once saturated.
//
// Against the backend's Stream class (45 opens/min/IP, `stream_rate_limit`
// in settings.py): the reported incident's 5 concurrently-failing streams
// (four `/api/jobs/{id}/stream` plus the resource stream) cost 5 * 8 = 40
// reopens in the first minute and 5 * 7.5 = 37.5/min after -- under budget.
// The theoretical ceiling of 11 streams (`max_user_active_jobs` (10) plus
// the resource stream) would cost 88 and 82.5/min, over it: at that extreme
// the server's limiter answers the excess with 429, which each stream
// counts as one more failed attempt and backs off from, so the limiter --
// not this client pacing -- holds the budget. That is the accepted price of
// a take arriving within seconds of the network's return. The resource
// stream's own per-user budget (`resource_event_stream_open_limit`, 12/min)
// takes one tab's 8 first-minute reopens plus its regular 60s
// reauthentication reopen. Do not lower BASE below 2000ms: the first-minute
// ramp, not the saturated rate, is what overran the budget at BASE=1000ms
// before an #257 review caught it.
export const SSE_RECONNECT_BASE_DELAY_MS = 2000;
export const SSE_RECONNECT_BACKOFF_FACTOR = 2;
export const SSE_RECONNECT_MAX_DELAY_MS = 8000;
export const SSE_RECONNECT_JITTER_RATIO = 0.2;
export const SSE_IMMEDIATE_REOPEN_MIN_GAP_MS = 2000;
// A job stream stops trusting its stream and reads the job over REST on this
// many consecutive connection errors. Twenty-four retries at the delays above
// (2 + 4 + 8 + 21 * 8s = 182s) keep the roughly three minutes the former 30s
// ceiling gave ten attempts. Only timed retries that fail while the page is
// online count: a reopen on returning to the app never spends one, so
// frequent returns never shorten the three minutes (#1032), nor does a
// failure while offline, so no number of outages drops a running take (#1141).
export const JOB_STREAM_MAX_CONNECTION_ERRORS = 25;
// How long a finished generate job keeps its card, counted only while the page
// is online, when the song refresh its end asked for has not run (#1039 O3):
// offline the card stays however long the network is away; back online this is
// long enough for the page to resync, short enough that a refresh that never
// runs does not leave a card behind.
export const GENERATE_TAKE_ARRIVAL_WAIT_MS = 30_000;
