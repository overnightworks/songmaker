import type { SongItem } from '$lib/api/types';

export interface ApplyData {
	song?: string;
	songId?: string;
	lyrics?: string;
	prompt?: string;
	bpm?: number;
	audio_duration?: number;
	key_scale?: string;
	create?: boolean;
	title?: string;
}

export function cleanDisplayText(text: string): string {
	return text.replaceAll(/```songmaker\s*\n[\s\S]*?```/g, '').trim();
}

function parseSongmakerBlock(
	raw: Record<string, unknown>,
	currentAlbumId: string,
	allSongs: SongItem[]
): ApplyData | undefined {
	const data: ApplyData = {};
	applyValidSongmakerFields(data, raw);
	applySongTarget(data, raw.song, currentAlbumId, allSongs);
	const hasFields = Object.keys(data).some(
		(k) => k !== 'song' && k !== 'songId' && k !== 'create' && k !== 'title'
	);
	return hasFields || data.create ? data : undefined;
}

function applyValidSongmakerFields(data: ApplyData, raw: Record<string, unknown>): void {
	if (isTextWithinLimit(raw.lyrics, 50_000)) data.lyrics = raw.lyrics;
	if (isTextWithinLimit(raw.prompt, 5_000)) data.prompt = raw.prompt;
	if (isTextWithinLimit(raw.key_scale, 10)) data.key_scale = raw.key_scale;
	if (isNumberWithinRange(raw.bpm, 0, 999)) data.bpm = raw.bpm;
	if (isNumberWithinRange(raw.audio_duration, 1, 600)) data.audio_duration = raw.audio_duration;
}

function isTextWithinLimit(value: unknown, maximumLength: number): value is string {
	return typeof value === 'string' && value.length <= maximumLength;
}

function isNumberWithinRange(value: unknown, minimum: number, maximum: number): value is number {
	return typeof value === 'number' && value >= minimum && value <= maximum;
}

function applySongTarget(
	data: ApplyData,
	song: unknown,
	currentAlbumId: string,
	allSongs: SongItem[]
): void {
	if (typeof song !== 'string') return;

	data.song = song;
	const target = findSongByTitle(song, currentAlbumId, allSongs);
	if (target) {
		data.songId = target.id;
		return;
	}
	data.create = true;
	data.title = song;
}

function findSongByTitle(
	song: string,
	currentAlbumId: string,
	allSongs: SongItem[]
): SongItem | undefined {
	const normalizedTitle = song.toLowerCase();
	const albumMatch = currentAlbumId
		? allSongs.find(
				(song) => song.title.toLowerCase() === normalizedTitle && song.album_id === currentAlbumId
			)
		: undefined;
	return albumMatch ?? allSongs.find((song) => song.title.toLowerCase() === normalizedTitle);
}

export function extractAllApplyData(
	text: string,
	currentAlbumId: string,
	allSongs: SongItem[]
): ApplyData[] {
	const results: ApplyData[] = [];
	const re = /```songmaker\s*\n([\s\S]*?)```/g;
	let match;
	while ((match = re.exec(text)) !== null) {
		try {
			const raw = JSON.parse(match[1].trim());
			const data = parseSongmakerBlock(raw, currentAlbumId, allSongs);
			if (data) results.push(data);
		} catch {
			/* invalid JSON in songmaker block — skip */
		}
	}
	return results;
}

export function isCurrentSong(data: ApplyData, songId: string): boolean {
	return !data.create && (!data.songId || data.songId === songId);
}
