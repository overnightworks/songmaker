import type { SongItem } from '$lib/api/types';

export interface ApplyData {
	song?: string;
	songId?: string;
	lyrics?: string;
	prompt?: string;
	bpm?: number;
	duration?: number;
	key?: string;
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
	if (typeof raw.lyrics === 'string' && raw.lyrics.length <= 50_000) data.lyrics = raw.lyrics;
	if (typeof raw.prompt === 'string' && raw.prompt.length <= 5_000) data.prompt = raw.prompt;
	if (typeof raw.key === 'string' && raw.key.length <= 10) data.key = raw.key;
	if (typeof raw.bpm === 'number' && raw.bpm >= 0 && raw.bpm <= 999) data.bpm = raw.bpm;
	if (typeof raw.duration === 'number' && raw.duration >= 1 && raw.duration <= 600)
		data.duration = raw.duration;
	if (typeof raw.song === 'string') {
		data.song = raw.song;
		const q = raw.song.toLowerCase();
		const albumMatch = currentAlbumId
			? allSongs.find((s) => s.title.toLowerCase() === q && s.album_id === currentAlbumId)
			: undefined;
		const target = albumMatch ?? allSongs.find((s) => s.title.toLowerCase() === q);
		if (target) {
			data.songId = target.id;
		} else {
			data.create = true;
			data.title = raw.song;
		}
	}
	const hasFields = Object.keys(data).some(
		(k) => k !== 'song' && k !== 'songId' && k !== 'create' && k !== 'title'
	);
	return hasFields || data.create ? data : undefined;
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
		}
	}
	return results;
}

export function isCurrentSong(data: ApplyData, songId: string): boolean {
	return !data.create && (!data.songId || data.songId === songId);
}
