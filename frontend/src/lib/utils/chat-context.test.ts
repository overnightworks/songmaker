import { describe, expect, it } from 'vitest';
import type { SongItem } from '$lib/api/types';
import { cleanDisplayText, extractAllApplyData, isCurrentSong } from './chat-context';

function makeSong(overrides: Partial<SongItem> = {}): SongItem {
	return {
		id: 'song-1',
		slug: 'test-song',
		title: 'Test Song',
		album_id: 'album-1',
		album_title: 'Test Album',
		artist: '',
		track_number: 1,
		prompt: '',
		lyrics: '',
		bpm: 0,
		audio_duration: 180,
		key_scale: '',
		vocal_language: '',
		version_count: 0,
		generation_count: 0,
		is_shared: false,
		generations: [],
		created_at: '',
		...overrides
	};
}

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
		const text =
			'```songmaker\n{"bpm": 1500, "audio_duration": -1, "key_scale": "this is way too long key"}\n```';
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
