import { formatTime } from '#lib/utils/format.ts';
import { pageText } from '#lib/utils/page-words.ts';

// Now Playing layout constants and the take descriptions its surfaces share.

// Swiping the mini player up opens Now Playing once the finger has risen
// this far, and further up than sideways; anything less is a tap or a slip.
export const NOW_PLAYING_SWIPE_RISE_PX = 40;

// What separates the parts of a take's one-line description, everywhere one
// is written out.
const META_SEPARATOR = ' · ';

// The one take identifier shared by the queue row, mini-player and
// NowPlayingFrame: "v<N> · take <k>", or just "take <k>" when the row carries
// no version (library-pool items have version_number: null).
export function nowPlayingTakeLabel(
	versionNumber: number | null,
	generationNumber: number
): string {
	const take = String(generationNumber);
	return versionNumber != null
		? pageText('nowPlaying.takeVersioned', { version: String(versionNumber), take })
		: pageText('nowPlaying.takeUnversioned', { take });
}

export interface TakeVersion {
	versionId: string;
	versionNumber: number;
}

// The one place that decides whether a take has a version to open; null
// means it was imported.
export function takeVersion(
	versionId: string | null,
	versionNumber: number | null
): TakeVersion | null {
	return versionId === null || versionNumber === null ? null : { versionId, versionNumber };
}

interface TakeMetaParts {
	artist: string | null;
	versionNumber: number | null;
	generationNumber: number;
	durationSec: number | null;
	// Omitted by rows that don't carry per-take model info (e.g. a playlist
	// entry); those rows show no model label.
	modelMode?: string | null;
}

// The one place that decides what a take's model_mode reads as everywhere a
// take names its model — today the raw value already is the terse label
// (turbo, xl-turbo, xl-sft, sft, xl-base); this is where that would change if
// it ever stopped being terse.
function takeModelModeLabel(modelMode: string | null | undefined): string | null {
	return modelMode || null;
}

// A row's full description of a take — "Artist · v1 · take 1 · 3:15" — built
// here rather than in markup: a separator written at the start of an `{#if}`
// loses its leading space to the compiler and reads "take 1· 3:15". One owner,
// one spacing rule, whatever a given row happens to know.
export function nowPlayingTakeMeta(parts: TakeMetaParts): string {
	const written = [parts.artist, nowPlayingTakeLabel(parts.versionNumber, parts.generationNumber)];
	if (parts.durationSec !== null && parts.durationSec > 0) {
		written.push(formatTime(parts.durationSec));
	}
	written.push(takeModelModeLabel(parts.modelMode));
	return written.filter((part): part is string => Boolean(part)).join(META_SEPARATOR);
}

// Where the playing queue comes from — the album or playlist it was built
// from. A library queue has no source. The player store owns the answer
// (playbackSource); Now Playing adds how to go back there.
type PlaybackSourceKind = 'album' | 'playlist';

export interface PlaybackSource {
	kind: PlaybackSourceKind;
	id: string;
	title: string;
}

export interface NowPlayingSource extends PlaybackSource {
	open: () => void;
}

export function nowPlayingFromLabel(title: string): string {
	return pageText('nowPlaying.fromSource', { title });
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
// A cut mini-player title scrolls once, slowly: it rests, travels to its end
// at this pace, rests again, and glides back to its start.
export const MINI_PLAYER_TITLE_SCROLL_PX_PER_SECOND = 30;
export const MINI_PLAYER_TITLE_SCROLL_REST_MS = 1500;
export const MINI_PLAYER_TITLE_SCROLL_RETURN_MS = 600;
