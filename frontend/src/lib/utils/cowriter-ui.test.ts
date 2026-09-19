import { makeSong as song } from '$lib/test-utils/factories';
import { describe, expect, it } from 'vitest';

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

describe('cowriterToolCallTarget', () => {
	const allSongs = [
		song({ slug: 'open-song', generation_count: 0, title: 'Open Song' }),
		song({ slug: 'open-song', generation_count: 0, id: 's2', title: 'Other Song' })
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
