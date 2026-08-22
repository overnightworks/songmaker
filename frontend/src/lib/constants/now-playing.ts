// Now Playing copy and layout constants (issue #101). Kept separate from
// lib/constants.ts, which #100 owns for the same landing window — see the
// epic's file-split rule.

export const NOW_PLAYING_QUEUE_TAB = 'Queue';
export const NOW_PLAYING_TAKE_TAB = 'This take';
export const NOW_PLAYING_RIGHT_PANEL_LABEL = 'Now Playing panel';

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
export const NOW_PLAYING_SUNG_ROW_LABEL = 'Sung';

export const NOW_PLAYING_PICK_LABEL = 'Pick';
export const NOW_PLAYING_UNPICK_LABEL = 'Unpick';
export const NOW_PLAYING_KEEP_LABEL = 'Keep';
export const NOW_PLAYING_UNKEEP_LABEL = 'Unkeep';
export const NOW_PLAYING_RATING_LABEL = 'Your rating';
export const NOW_PLAYING_RATING_SAVE = 'Save rating';
export const NOW_PLAYING_RATING_SAVING = 'Saving…';
export const NOW_PLAYING_PIN_SEED_PREFIX = 'Pin seed';

export const NOW_PLAYING_Z_INDEX = 350;
// Below this width the three columns (cover, lyrics, right panel) stack, and
// the right panel becomes a sheet the listener opens explicitly. Matches
// PlayerBar's coarse-pointer override so a touch device always gets the
// stacked layout regardless of viewport width.
export const NOW_PLAYING_STACKED_MEDIA = '(max-width: 1099px), (any-pointer: coarse)';
