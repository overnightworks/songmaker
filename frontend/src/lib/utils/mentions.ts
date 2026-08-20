import type { SongItem, VersionItem } from '$lib/api/types';

export type MentionItem =
	| { type: 'album' }
	| { type: 'version'; item: VersionItem }
	| { type: 'song'; item: SongItem };

const VERSION_MENTION_RE = /^v(?:ersion)?\s*(\d*)$/i;

export function mentionQueryAtCursor(
	text: string,
	cursor: number
): { query: string; atIndex: number } | null {
	const before = text.slice(0, cursor);
	const match = before.match(/@([^@\n]*)$/);
	if (!match) return null;
	return { query: match[1], atIndex: before.lastIndexOf('@') };
}

export function replaceMentionToken(
	text: string,
	cursor: number,
	insertion: string
): string {
	const found = mentionQueryAtCursor(text, cursor);
	if (!found) return text;
	return text.slice(0, found.atIndex) + insertion + text.slice(cursor);
}

export function filterMentionItems(args: {
	query: string;
	albumMentioned: boolean;
	currentAlbumId: string;
	currentSongId: string;
	versions: VersionItem[];
	allSongs: SongItem[];
	mentionedSongIds: string[];
	mentionedVersionIds: string[];
}): MentionItem[] {
	const results: MentionItem[] = [];
	const query = args.query;
	const lower = query.toLowerCase();

	if (!args.albumMentioned && args.currentAlbumId && 'album'.startsWith(lower)) {
		results.push({ type: 'album' });
	}

	if (VERSION_MENTION_RE.test(query)) {
		const prefix = query.match(VERSION_MENTION_RE)?.[1] ?? '';
		const mentioned = new Set(args.mentionedVersionIds);
		results.push(
			...args.versions
				.filter(
					(version) =>
						!mentioned.has(version.id) && String(version.version_number).startsWith(prefix)
				)
				.slice(0, 8)
				.map((item) => ({ type: 'version' as const, item }))
		);
	}

	const mentionedSongs = new Set(args.mentionedSongIds);
	const songs = args.allSongs.filter(
		(song) => song.id !== args.currentSongId && !mentionedSongs.has(song.id)
	);
	if (query) {
		results.push(
			...songs
				.filter((song) => song.title.toLowerCase().includes(lower))
				.slice(0, 8)
				.map((item) => ({ type: 'song' as const, item }))
		);
	} else {
		results.push(...songs.slice(0, 5).map((item) => ({ type: 'song' as const, item })));
	}
	return results;
}
