import { describe, expect, it } from 'vitest';
import type { SongItem, VersionItem } from '$lib/api/types';
import {
	formatSongContext,
	formatVersionContext,
	buildFullContext,
	buildConversation,
	cleanDisplayText,
	extractAllApplyData,
	isCurrentSong,
	type ApplyData
} from './chat-context';

function makeSong(overrides: Partial<SongItem> = {}): SongItem {
	return {
		id: 'song-1',
		title: 'Test Song',
		album_id: 'album-1',
		album_title: 'Test Album',
		artist: '',
		track_number: 1,
		prompt: '',
		lyrics: '',
		bpm: 0,
		duration: 180,
		key: '',
		language: '',
		version_count: 0,
		generation_count: 0,
		is_shared: false,
		generations: [],
		...overrides
	};
}

function makeVersion(overrides: Partial<VersionItem> = {}): VersionItem {
	return {
		id: 'ver-1',
		version_number: 1,
		lyrics: '',
		prompt: '',
		bpm: 0,
		duration: 180,
		key: '',
		generation_params: null,
		created_at: null,
		...overrides
	};
}

describe('formatSongContext', () => {
	it('formats a song with all fields', () => {
		const s = makeSong({ title: 'My Song', prompt: 'rock', key: 'Am', bpm: 120, duration: 200, lyrics: 'hello' });
		const result = formatSongContext(s);
		expect(result).toContain('[Track 1] My Song');
		expect(result).toContain('Style: rock');
		expect(result).toContain('Key: Am');
		expect(result).toContain('BPM: 120');
		expect(result).toContain('Duration: 200s');
		expect(result).toContain('Lyrics:\nhello');
	});

	it('omits empty fields', () => {
		const s = makeSong({ title: 'Empty', prompt: '', key: '', bpm: 0, duration: 0, lyrics: '' });
		const result = formatSongContext(s);
		expect(result).toBe('[Track 1] Empty');
	});
});

describe('formatVersionContext', () => {
	it('formats a version with fields', () => {
		const v = makeVersion({ version_number: 3, prompt: 'jazz', key: 'C', bpm: 100 });
		const result = formatVersionContext(v);
		expect(result).toContain('[Version 3]');
		expect(result).toContain('Style: jazz');
		expect(result).toContain('Key: C');
	});
});

describe('buildFullContext', () => {
	const songs = [
		makeSong({ id: 's1', title: 'Song A', album_id: 'a1', track_number: 1 }),
		makeSong({ id: 's2', title: 'Song B', album_id: 'a1', track_number: 2 }),
		makeSong({ id: 's3', title: 'Song C', album_id: 'a2', track_number: 1 })
	];

	it('includes current song context', () => {
		const result = buildFullContext('my context', 's1', 'a1', songs, [], false);
		expect(result).toContain('[Current Song]\nmy context');
	});

	it('adds album songs when albumMentioned is true', () => {
		const result = buildFullContext('ctx', 's1', 'a1', songs, [], true);
		expect(result).toContain('Song B');
		expect(result).not.toContain('Song C');
	});

	it('does not add album songs when albumMentioned is false', () => {
		const result = buildFullContext('ctx', 's1', 'a1', songs, [], false);
		expect(result).not.toContain('Song B');
	});

	it('adds mentioned songs by id', () => {
		const result = buildFullContext('ctx', 's1', 'a1', songs, ['s3'], false);
		expect(result).toContain('Song C');
	});

	it('deduplicates album songs and mentioned songs', () => {
		const result = buildFullContext('ctx', 's1', 'a1', songs, ['s2'], true);
		const matches = result.match(/Song B/g);
		expect(matches).toHaveLength(1);
	});

	it('includes mentioned versions', () => {
		const versions = [makeVersion({ version_number: 1 }), makeVersion({ id: 'v2', version_number: 2, prompt: 'v2 style' })];
		const result = buildFullContext('ctx', 's1', 'a1', songs, [], false, versions, [2]);
		expect(result).toContain('[Version 2]');
		expect(result).toContain('v2 style');
		expect(result).not.toContain('[Version 1]');
	});
});

describe('buildConversation', () => {
	it('builds conversation with user and assistant messages', () => {
		const msgs = [
			{ role: 'user' as const, text: 'hello' },
			{ role: 'assistant' as const, text: 'hi there' }
		];
		const result = buildConversation(msgs, 'new message');
		expect(result).toContain('User: hello');
		expect(result).toContain('Assistant: hi there');
		expect(result).toContain('User: new message');
	});

	it('strips songmaker blocks from history', () => {
		const msgs = [
			{ role: 'assistant' as const, text: 'Here you go\n```songmaker\n{"lyrics": "test"}\n```' }
		];
		const result = buildConversation(msgs, 'thanks');
		expect(result).not.toContain('songmaker');
		expect(result).toContain('Here you go');
	});
});

describe('cleanDisplayText', () => {
	it('removes songmaker blocks', () => {
		const text = 'Here are lyrics\n```songmaker\n{"lyrics": "test"}\n```\nEnjoy!';
		expect(cleanDisplayText(text)).toBe('Here are lyrics\n\nEnjoy!');
	});

	it('removes multiple songmaker blocks', () => {
		const text = 'A\n```songmaker\n{"lyrics": "a"}\n```\nB\n```songmaker\n{"lyrics": "b"}\n```\nC';
		expect(cleanDisplayText(text)).toBe('A\n\nB\n\nC');
	});

	it('returns text unchanged without blocks', () => {
		expect(cleanDisplayText('hello world')).toBe('hello world');
	});
});

describe('extractAllApplyData', () => {
	const songs = [
		makeSong({ id: 's1', title: 'Existing Song', album_id: 'a1' }),
		makeSong({ id: 's2', title: 'Another Song', album_id: 'a1' })
	];

	it('extracts a single block', () => {
		const text = 'text\n```songmaker\n{"lyrics": "hello", "bpm": 120}\n```';
		const result = extractAllApplyData(text, 'a1', songs);
		expect(result).toHaveLength(1);
		expect(result[0].lyrics).toBe('hello');
		expect(result[0].bpm).toBe(120);
	});

	it('extracts multiple blocks', () => {
		const text = [
			'```songmaker\n{"lyrics": "verse 1"}\n```',
			'```songmaker\n{"song": "Another Song", "lyrics": "verse 2"}\n```'
		].join('\n');
		const result = extractAllApplyData(text, 'a1', songs);
		expect(result).toHaveLength(2);
		expect(result[0].lyrics).toBe('verse 1');
		expect(result[1].lyrics).toBe('verse 2');
		expect(result[1].songId).toBe('s2');
	});

	it('marks unknown song as create', () => {
		const text = '```songmaker\n{"song": "Brand New Song", "lyrics": "new lyrics"}\n```';
		const result = extractAllApplyData(text, 'a1', songs);
		expect(result).toHaveLength(1);
		expect(result[0].create).toBe(true);
		expect(result[0].title).toBe('Brand New Song');
		expect(result[0].lyrics).toBe('new lyrics');
		expect(result[0].songId).toBeUndefined();
	});

	it('matches existing song by title (case insensitive)', () => {
		const text = '```songmaker\n{"song": "existing song", "lyrics": "updated"}\n```';
		const result = extractAllApplyData(text, 'a1', songs);
		expect(result).toHaveLength(1);
		expect(result[0].songId).toBe('s1');
		expect(result[0].create).toBeUndefined();
	});

	it('prefers album match over global match', () => {
		const songsMultiAlbum = [
			makeSong({ id: 's-a1', title: 'Dupe', album_id: 'a1' }),
			makeSong({ id: 's-a2', title: 'Dupe', album_id: 'a2' })
		];
		const text = '```songmaker\n{"song": "Dupe", "lyrics": "x"}\n```';
		const result = extractAllApplyData(text, 'a1', songsMultiAlbum);
		expect(result[0].songId).toBe('s-a1');
	});

	it('returns empty array for no blocks', () => {
		expect(extractAllApplyData('just text', 'a1', songs)).toEqual([]);
	});

	it('skips malformed JSON', () => {
		const text = '```songmaker\n{invalid json}\n```';
		expect(extractAllApplyData(text, 'a1', songs)).toEqual([]);
	});

	it('skips blocks with only song/songId (no actual fields)', () => {
		const text = '```songmaker\n{"song": "Existing Song"}\n```';
		const result = extractAllApplyData(text, 'a1', songs);
		expect(result).toEqual([]);
	});

	it('allows create block with only a title and lyrics', () => {
		const text = '```songmaker\n{"song": "New One", "lyrics": "hello"}\n```';
		const result = extractAllApplyData(text, 'a1', songs);
		expect(result).toHaveLength(1);
		expect(result[0].create).toBe(true);
	});

	it('validates field bounds', () => {
		const text = '```songmaker\n{"bpm": 1500, "duration": -1, "key": "this is way too long key"}\n```';
		const result = extractAllApplyData(text, 'a1', songs);
		expect(result).toEqual([]);
	});

	it('extracts valid fields and ignores invalid ones', () => {
		const text = '```songmaker\n{"lyrics": "good", "bpm": 9999}\n```';
		const result = extractAllApplyData(text, 'a1', songs);
		expect(result).toHaveLength(1);
		expect(result[0].lyrics).toBe('good');
		expect(result[0].bpm).toBeUndefined();
	});
});

describe('isCurrentSong', () => {
	it('returns true when no songId set', () => {
		expect(isCurrentSong({}, 's1')).toBe(true);
	});

	it('returns true when songId matches', () => {
		expect(isCurrentSong({ songId: 's1' }, 's1')).toBe(true);
	});

	it('returns false when songId differs', () => {
		expect(isCurrentSong({ songId: 's2' }, 's1')).toBe(false);
	});

	it('returns false for create actions', () => {
		expect(isCurrentSong({ create: true, title: 'New' }, 's1')).toBe(false);
	});
});
