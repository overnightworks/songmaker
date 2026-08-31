import { describe, expect, it } from 'vitest';
import type { SongItem } from '$lib/api/types';
import {
	cowriterHeaderLabel,
	cowriterThinkingLabel,
	cowriterToolCallTarget,
	cowriterUnavailableLabel
} from './cowriter-ui';

describe('co-writer provider copy', () => {
	it('uses the active provider instead of a hardcoded Claude name', () => {
		expect(cowriterHeaderLabel('grok', 'grok-4.6')).toBe('grok · grok-4.6');
		expect(cowriterThinkingLabel('codex')).toBe('codex is thinking...');
		expect(cowriterUnavailableLabel('grok')).toBe('grok is currently unavailable');
		expect(cowriterThinkingLabel('claude')).not.toContain('Claude Co-Writer');
	});
});

function song(overrides: Partial<SongItem> = {}): SongItem {
	return {
		id: 's1',
		slug: 'open-song',
		title: 'Open Song',
		album_id: 'a1',
		album_title: 'Album',
		artist: 'Artist',
		track_number: 1,
		vocal_language: 'en',
		lyrics: '',
		prompt: '',
		version_count: 1,
		generation_count: 0,
		is_shared: false,
		created_at: '2026-01-01T00:00:00+00:00',
		generations: [],
		...overrides
	};
}

describe('cowriterToolCallTarget', () => {
	const allSongs = [
		song({ id: 's1', title: 'Open Song' }),
		song({ id: 's2', title: 'Other Song' })
	];

	it('resolves a write-tool target and flags it foreign when it is not the open song', () => {
		expect(cowriterToolCallTarget('update_song_lyrics', { song_id: 's2' }, allSongs, 's1')).toEqual(
			{ title: 'Other Song', foreign: true }
		);
	});

	it('resolves a write-tool target without the foreign flag when it targets the open song', () => {
		expect(cowriterToolCallTarget('update_song_prompt', { song_id: 's1' }, allSongs, 's1')).toEqual(
			{ title: 'Open Song', foreign: false }
		);
	});

	it('treats create_song as always foreign since it is not the song currently open', () => {
		expect(cowriterToolCallTarget('create_song', { title: 'Brand New' }, allSongs, 's1')).toEqual({
			title: 'Brand New',
			foreign: true
		});
	});

	it('returns null for read-only tools that carry no song target', () => {
		expect(cowriterToolCallTarget('list_songs', {}, allSongs, 's1')).toBeNull();
		expect(cowriterToolCallTarget('search_songs', { query: 'x' }, allSongs, 's1')).toBeNull();
	});

	it('returns null when the referenced song_id is not among the loaded songs', () => {
		expect(
			cowriterToolCallTarget('rename_song', { song_id: 's-missing' }, allSongs, 's1')
		).toBeNull();
	});
});
