export const SONG_LINK_NOT_FOUND_TOAST = 'Song not found — it may have been deleted';

export const EDITOR_QUEUED_LABEL = 'Queued';

export const EDITOR_TAB_TAKES_LABEL = 'Takes';
export const EDITOR_TAB_EDIT_LABEL = 'Edit';
export const EDITOR_TABS_LABEL = 'Editor tabs';

export const EDITOR_VIEW_COWRITER_LABEL = 'Co-writer';

export const EDITOR_GENERATE_LABEL = 'Generate';
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
export const SONG_COVER_ALT_TYPE = 'Song';
export const SONG_COVER_UPLOAD_LABEL = 'Upload song cover';
export const SONG_COVER_REPLACE_LABEL = 'Replace song cover';
export const SONG_COVER_REMOVE_LABEL = 'Remove song cover';

// Every row's PlayingMark reads this, in the rail, the detail views and the shared page.
export const PLAYING_MARK_LABEL = 'Playing';

// A song box's ✎: the box itself plays the song, so the pencil names the place it opens.
export function songEditorOpenLabel(songTitle: string): string {
	return `Open ${songTitle} in the song editor`;
}
