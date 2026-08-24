import type { SongItem } from '$lib/api/types';

const SONG_ID_TARGETING_TOOLS = new Set([
	'update_song_lyrics',
	'update_song_prompt',
	'update_song_style',
	'rename_song'
]);

export interface CowriterToolCallTarget {
	title: string;
	/** True when this proposal targets a song other than the one currently open. */
	foreign: boolean;
}

/**
 * The co-writer is one global conversation (REQ-COWRITER-01): a tool call
 * streamed while song X is open can still target song Y. Resolve which song
 * a write tool call actually targets from the data the frontend already
 * carries (the tool's own arguments plus the songs already loaded into the
 * editor), so a proposal for another song is visibly attributed instead of
 * looking like it applies to whatever is open.
 */
export function cowriterToolCallTarget(
	toolName: string,
	toolInput: Record<string, unknown>,
	allSongs: SongItem[],
	currentSongId: string
): CowriterToolCallTarget | null {
	if (toolName === 'create_song') {
		return typeof toolInput.title === 'string' ? { title: toolInput.title, foreign: true } : null;
	}
	if (!SONG_ID_TARGETING_TOOLS.has(toolName)) return null;
	const songId = typeof toolInput.song_id === 'string' ? toolInput.song_id : null;
	if (!songId) return null;
	const song = allSongs.find((candidate) => candidate.id === songId);
	if (!song) return null;
	return { title: song.title, foreign: songId !== currentSongId };
}

export function cowriterThinkingLabel(provider: string): string {
	return `${provider} is thinking...`;
}

export function cowriterUnavailableLabel(provider: string): string {
	return `${provider} is currently unavailable`;
}

export function cowriterHeaderLabel(provider: string, model: string): string {
	if (!model) return 'Co-Writer';
	return `${provider} · ${model}`;
}
