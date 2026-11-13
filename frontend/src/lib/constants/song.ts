export const SONG_LINK_NOT_FOUND_TOAST = 'Song not found — it may have been deleted';

export const EDITOR_QUEUED_LABEL = 'Queued';

export const EDITOR_GENERATE_LABEL = 'Generate';
export const EDITOR_GENERATE_QUEUED_TEMPLATE = `${EDITOR_QUEUED_LABEL} #{position}`;
export const EDITOR_GENERATE_TAKE_TEMPLATE = 'Take {index} of {count}';
export const EDITOR_OPEN_WORKER_POOL_LABEL = 'Open worker pool';

export const EDITOR_GENERATE_CANCEL_LABEL = 'Cancel generation';
// Offline a running take cannot report anything: it says so and
// keeps the last progress it saw, instead of a percent and time that stand still.
export const EDITOR_GENERATE_RECONNECTING_LABEL = 'Reconnecting…';
export const EDITOR_GENERATE_LAST_SEEN_TEMPLATE = 'last seen at {percent}%';
export const EDITOR_GENERATE_CANCEL_OFFLINE_LABEL = 'Cancel generation (unavailable while offline)';
export const EDITOR_GENERATE_LAST_SEEN_PROGRESS_LABEL = 'Last known progress';
export const EDITOR_GENERATE_CANCEL_FAILED = 'Could not cancel generation';
export const EDITOR_GENERATING_LABEL = 'Generating...';
export const EDITOR_NO_MODELS_WARNING = 'No models enabled. Ask admin to enable one.';
export const EDITOR_SELECT_MODEL_TITLE = 'Select a model first';
export const EDITOR_MISSING_CONTENT_TITLE = 'Add lyrics and style prompt first';

export const SONG_PREVIOUS_LABEL = 'Previous song';
export const SONG_NEXT_LABEL = 'Next song';

// Every row's PlayingMark reads this, in the rail, the detail views and the shared page.
export const PLAYING_MARK_LABEL = 'Playing';
