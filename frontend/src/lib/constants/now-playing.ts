import type { GenerationParams } from '$lib/api/types';
import { formatTime } from '$lib/utils/format';

// Now Playing copy and layout constants (issue #101). Kept separate from
// lib/constants.ts, which #100 owns for the same landing window — see the
// epic's file-split rule.

export const NOW_PLAYING_QUEUE_TAB = 'Queue';
export const NOW_PLAYING_TAKE_TAB = 'This take';
export const NOW_PLAYING_RIGHT_PANEL_LABEL = 'Now Playing panel';

// What separates the parts of a take's one-line description, everywhere one
// is written out.
const META_SEPARATOR = ' · ';

// Queue row take label: "v<N> · take <k>", or just "take <k>" when the row
// carries no version (library-pool items have version_number: null).
export function nowPlayingTakeLabel(
	versionNumber: number | null,
	generationNumber: number
): string {
	const takePart = `take ${generationNumber}`;
	return versionNumber != null ? `v${versionNumber}${META_SEPARATOR}${takePart}` : takePart;
}

export interface TakeMetaParts {
	artist: string | null;
	versionNumber: number | null;
	generationNumber: number;
	durationSec: number | null;
	// Omitted by rows that don't carry per-take model info (e.g. a playlist
	// entry) — those rows read exactly as before (#212).
	modelMode?: string | null;
}

// The one place that decides what a take's model_mode reads as everywhere a
// take names its model — today the raw value already is the terse label
// (turbo, xl-turbo, xl-sft, sft, xl-base); this is where that would change if
// it ever stopped being terse.
export function takeModelModeLabel(modelMode: string | null | undefined): string | null {
	return modelMode || null;
}

// ACE-Step's VRAM guard can quietly cut a requested batch size down before
// generation runs — issue #211's "2 asked, 1 delivered" case. The backend
// only ever persists delivered_batch_size when it actually diverges from
// batch_size, so presence alone would already be a safe signal — this still
// checks both explicitly rather than trusting that invariant from the UI.
export function takeBatchReductionLabel(
	generationParams: GenerationParams | null | undefined
): string | null {
	const requested = generationParams?.batch_size;
	const delivered = generationParams?.delivered_batch_size;
	if (requested == null || delivered == null || requested === delivered) return null;
	return `${delivered} of ${requested}`;
}

// A row's full description of a take — "Artist · v1 · take 1 · 3:15" — built
// here rather than in markup: a separator written at the start of an `{#if}`
// loses its leading space to the compiler, which is how the playlist row came
// to read "take 1· 3:15" (#163/5). One owner, one spacing rule, whatever a
// given row happens to know.
export function nowPlayingTakeMeta(parts: TakeMetaParts): string {
	const written = [parts.artist, nowPlayingTakeLabel(parts.versionNumber, parts.generationNumber)];
	if (parts.durationSec !== null && parts.durationSec > 0) {
		written.push(formatTime(parts.durationSec));
	}
	written.push(takeModelModeLabel(parts.modelMode));
	return written.filter((part): part is string => Boolean(part)).join(META_SEPARATOR);
}

export const NOW_PLAYING_UP_NEXT_PREFIX = 'Up next:';
export const NOW_PLAYING_SHUFFLE_LABEL_PREFIX = 'Shuffle';
export const NOW_PLAYING_SHUFFLE_DISABLE_PREFIX = 'Disable shuffle';

export function nowPlayingQueueHeading(contextLabel: string | null): string {
	return contextLabel
		? `${NOW_PLAYING_QUEUE_TAB}${META_SEPARATOR}${contextLabel}`
		: NOW_PLAYING_QUEUE_TAB;
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

// Curation mode (issue #228): walking an album's per-song candidate takes
// one after another, right from the cover column's transport row so it never
// hides behind the mobile sheet tap the queue/take tabs otherwise need.
export const NOW_PLAYING_CURATE_GROUP_LABEL = 'Curate this album';
export const NOW_PLAYING_CURATE_SKIP_LABEL = 'Skip';
export const NOW_PLAYING_CURATE_DONE_LABEL = 'Done curating';

export function nowPlayingCurateProgress(index: number, total: number): string {
	return `Song ${index + 1} of ${total}`;
}

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
