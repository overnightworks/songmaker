// Now Playing copy and layout constants (issue #101). Kept separate from
// lib/constants.ts, which #100 owns for the same landing window — see the
// epic's file-split rule.

export const NOW_PLAYING_QUEUE_TAB = 'Queue';
export const NOW_PLAYING_TAKE_TAB = 'This take';
export const NOW_PLAYING_RIGHT_PANEL_LABEL = 'Now Playing panel';

// Queue row take label: "v<N> · take <k>", or just "take <k>" when the row
// carries no version (library-pool items have version_number: null).
export function nowPlayingTakeLabel(
	versionNumber: number | null,
	generationNumber: number
): string {
	const takePart = `take ${generationNumber}`;
	return versionNumber != null ? `v${versionNumber} · ${takePart}` : takePart;
}

export const NOW_PLAYING_UP_NEXT_PREFIX = 'Up next:';
export const NOW_PLAYING_SHUFFLE_LABEL_PREFIX = 'Shuffle';
export const NOW_PLAYING_SHUFFLE_DISABLE_PREFIX = 'Disable shuffle';

export function nowPlayingQueueHeading(contextLabel: string | null): string {
	return contextLabel ? `${NOW_PLAYING_QUEUE_TAB} · ${contextLabel}` : NOW_PLAYING_QUEUE_TAB;
}

export const NOW_PLAYING_SCORES_LABEL = 'Scores';
export const NOW_PLAYING_SCORES_EMPTY = 'No scores yet';
export const NOW_PLAYING_DEVIATIONS_LABEL = 'Sung vs. lyrics';
export const NOW_PLAYING_DEVIATIONS_EMPTY = 'Sung text matches the lyrics';
export const NOW_PLAYING_DEVIATIONS_UNAVAILABLE = 'No transcript to compare against yet';
export const NOW_PLAYING_LYRICS_ROW_LABEL = 'Lyrics';
// #45: a take scored before #44 landed has whisper_text but no whisper_cues,
// so its lyrics stay static instead of following the audio. The lyrics panel
// only names that state — it also renders for a public share listener, who
// cannot re-score anything. The take panel owns the action that fixes it.
export const NOW_PLAYING_LYRICS_UNSYNCED_NOTE = "Lyrics aren't synced for this take.";
export const NOW_PLAYING_RESCORE_ACTION_LABEL = 'Re-score this take to follow the lyrics.';

export const NOW_PLAYING_PICK_LABEL = 'Pick';
export const NOW_PLAYING_UNPICK_LABEL = 'Unpick';
export const NOW_PLAYING_KEEP_LABEL = 'Keep';
export const NOW_PLAYING_UNKEEP_LABEL = 'Unkeep';
export const NOW_PLAYING_RATING_LABEL = 'Your rating';
export const NOW_PLAYING_RATING_NOTES_PLACEHOLDER = 'Notes (optional)';
export const NOW_PLAYING_RATING_SAVE = 'Save rating';
export const NOW_PLAYING_RATING_SAVING = 'Saving…';
export const NOW_PLAYING_PIN_SEED_PREFIX = 'Pin seed';
export const NOW_PLAYING_DEVIATION_ADDED_TITLE = 'Not in lyrics';

export const NOW_PLAYING_Z_INDEX = 350;
// Below this width the three columns (cover, lyrics, right panel) stack, and
// the right panel becomes a sheet the listener opens explicitly. Matches
// PlayerBar's coarse-pointer override so a touch device always gets the
// stacked layout regardless of viewport width.
export const NOW_PLAYING_STACKED_MAX_PX = 1099;
export const NOW_PLAYING_STACKED_MEDIA = `(max-width: ${NOW_PLAYING_STACKED_MAX_PX}px), (any-pointer: coarse)`;

// The two surfaces Now Playing can show as. The player store adds 'closed'
// on top of them; the frame only ever renders one of these two.
export const NOW_PLAYING_SURFACE_KINDS = ['docked', 'full'] as const;
export type NowPlayingSurfaceKind = (typeof NOW_PLAYING_SURFACE_KINDS)[number];

// Docking beside the workspace instead of covering it costs the workspace
// NOW_PLAYING_DOCKED_WIDTH_PX. The editor's takes column and its header do not
// survive that below 1440 — at 1280 a take row's Pick/Keep/… actions fall
// outside `main`, which is `overflow: hidden`, so they become unreachable
// rather than scrollable (browser gate on #140, 2026-08-23). Hence a dock
// threshold of its own rather than reusing the stacking breakpoint: narrower
// than this, Now Playing takes the whole screen, where it costs the editor
// nothing. Issue #185 makes the editor answer to its own width, and lowers
// this again.
export const NOW_PLAYING_DOCK_MIN_PX = 1440;
// Phrased as "cannot dock" so it reads like NOW_PLAYING_STACKED_MEDIA and
// composes with subscribeCompactLayout, which ORs in the data-pointer='coarse'
// override: too narrow, or any touch pointer, and there is no docked panel.
export const NOW_PLAYING_UNDOCKED_MEDIA = `(max-width: ${NOW_PLAYING_DOCK_MIN_PX - 1}px), (any-pointer: coarse)`;
export const NOW_PLAYING_DOCKED_WIDTH_PX = 400;
export const NOW_PLAYING_EXPAND_LABEL = 'Expand';
export const NOW_PLAYING_COLLAPSE_LABEL = 'Collapse';

// Queue-stream skip/progress feedback (QueueStreamFeedback). One owner for
// this surface's copy, kept alongside the rest of Now Playing's strings.
export const NOW_PLAYING_STREAM_SKIPPED_SUFFIX = 'takes skipped';
export const NOW_PLAYING_STREAM_CHECK_INCOMPLETE = 'Check incomplete';
export const NOW_PLAYING_STREAM_ENDED = 'End of stream';
export const NOW_PLAYING_STREAM_MISSING_PATH_SUFFIX = 'no audio file';
export const NOW_PLAYING_STREAM_MISSING_FILE_SUFFIX = 'file not found';
export const NOW_PLAYING_STREAM_UNREADABLE_FILE_SUFFIX = 'file unreadable';
export const NOW_PLAYING_STREAM_MORE_NOT_CHECKED = 'More takes not checked';
export const NOW_PLAYING_STREAM_MORE_NOT_LOADED = 'More takes not loaded';
