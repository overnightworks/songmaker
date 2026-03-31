import type { SongItem, VersionItem } from '$lib/api/types';

export interface ApplyData {
	song?: string;
	songId?: string;
	lyrics?: string;
	prompt?: string;
	bpm?: number;
	duration?: number;
	key?: string;
}

export function formatSongContext(s: SongItem): string {
	const parts = [`[Track ${s.track_number}] ${s.title}`];
	if (s.prompt) parts.push(`Style: ${s.prompt}`);
	const meta: string[] = [];
	if (s.key) meta.push(`Key: ${s.key}`);
	if (s.bpm) meta.push(`BPM: ${s.bpm}`);
	if (s.duration) meta.push(`Duration: ${s.duration}s`);
	if (meta.length) parts.push(meta.join(' | '));
	if (s.lyrics) parts.push(`Lyrics:\n${s.lyrics}`);
	return parts.join('\n');
}

export function formatVersionContext(v: VersionItem): string {
	const parts = [`[Version ${v.version_number}]`];
	if (v.created_at) parts.push(`Date: ${new Date(v.created_at).toLocaleDateString()}`);
	if (v.prompt) parts.push(`Style: ${v.prompt}`);
	const meta: string[] = [];
	if (v.key) meta.push(`Key: ${v.key}`);
	if (v.bpm) meta.push(`BPM: ${v.bpm}`);
	if (v.duration) meta.push(`Duration: ${v.duration}s`);
	if (meta.length) parts.push(meta.join(' | '));
	if (v.lyrics) parts.push(`Lyrics:\n${v.lyrics}`);
	return parts.join('\n');
}

export function buildFullContext(
	songContext: string,
	songId: string,
	contextScope: 'song' | 'album',
	currentAlbumId: string,
	allSongs: SongItem[],
	mentionedSongIds: string[],
	versions: VersionItem[] = [],
	mentionedVersionNumbers: number[] = []
): string {
	const parts: string[] = [];

	if (songContext) {
		parts.push(`[Current Song]\n${songContext}`);
	}

	const extraSongs: SongItem[] = [];

	if (contextScope === 'album' && currentAlbumId) {
		const albumSongs = allSongs
			.filter((s) => s.album_id === currentAlbumId && s.id !== songId)
			.sort((a, b) => a.track_number - b.track_number);
		extraSongs.push(...albumSongs);
	}

	for (const id of mentionedSongIds) {
		if (!extraSongs.some((s) => s.id === id)) {
			const s = allSongs.find((s) => s.id === id);
			if (s) extraSongs.push(s);
		}
	}

	if (extraSongs.length > 0) {
		parts.push('--- Other songs ---\n\n' + extraSongs.map(formatSongContext).join('\n\n'));
	}

	if (mentionedVersionNumbers.length > 0) {
		const versionContexts = mentionedVersionNumbers
			.map((vn) => versions.find((v) => v.version_number === vn))
			.filter((v): v is VersionItem => !!v)
			.map(formatVersionContext);
		if (versionContexts.length > 0) {
			parts.push('--- Referenced versions ---\n\n' + versionContexts.join('\n\n'));
		}
	}

	return parts.join('\n\n');
}

interface ChatMessage {
	role: 'user' | 'assistant';
	text: string;
}

export function buildConversation(messages: ChatMessage[], newMessage: string): string {
	const parts: string[] = [];
	for (const msg of messages) {
		const prefix = msg.role === 'user' ? 'User' : 'Assistant';
		parts.push(`${prefix}: ${cleanDisplayText(msg.text)}`);
	}
	parts.push(`User: ${newMessage}`);
	return parts.join('\n\n');
}

export function cleanDisplayText(text: string): string {
	return text.replace(/```songmaker\s*\n[\s\S]*?```/, '').trim();
}

export function extractApplyData(
	text: string,
	currentAlbumId: string,
	allSongs: SongItem[]
): ApplyData | undefined {
	const match = text.match(/```songmaker\s*\n([\s\S]*?)```/);
	if (!match) return undefined;
	try {
		const raw = JSON.parse(match[1].trim());
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
			if (target) data.songId = target.id;
		}
		return Object.keys(data).filter((k) => k !== 'song' && k !== 'songId').length > 0
			? data
			: undefined;
	} catch {
		return undefined;
	}
}

export function isCurrentSong(data: ApplyData, songId: string): boolean {
	return !data.songId || data.songId === songId;
}
